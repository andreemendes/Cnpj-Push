"""
Baixa os dados abertos de CNPJ da Receita Federal, filtra o estado configurado,
descobre quais empresas são NOVAS desde a última vez e atualiza o mapa.

Uso:
  python scripts/atualizar.py                 # baixa da Receita (se houver mês novo)
  python scripts/atualizar.py --forcar        # reprocessa mesmo se o mês já foi visto
  python scripts/atualizar.py --pasta-local P --mes 2026-11   # usa zips já baixados (teste)

Variáveis de ambiente: SENHA_MAPA (protege o mapa), NTFY_TOPICO (notificações).
"""
import argparse
import csv
import datetime as dt
import hashlib
import io
import math
import os
import re
import shutil
import sys
import tempfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from comum import (carregar_config, carregar_estado, salvar_estado, carregar_fila, salvar_fila,
                   salvar_mapa, notificar, log)

csv.field_size_limit(10**7)
DIAS_DETECCAO = 120   # empresas abertas há até 120 dias ainda podem "aparecer" como novas
DIAS_MEMORIA = 150    # por quanto tempo lembramos dos CNPJs já vistos


# ------------------------------------------------------------------ fonte
class Receita:
    def __init__(self, cfg):
        self.base = cfg["receita_webdav"].rstrip("/")
        self.token = cfg["receita_share_token"]
        self.dav = f"https://arquivos.receitafederal.gov.br/public.php/dav/files/{self.token}/Dados/Cadastros/CNPJ"

    def _propfind(self, url):
        import requests
        from xml.etree import ElementTree
        r = requests.request("PROPFIND", url, auth=(self.token, ""), headers={"Depth": "1"}, timeout=60)
        r.raise_for_status()
        return [e.text for e in ElementTree.fromstring(r.content).iter("{DAV:}href")]

    def ultimo_mes(self):
        meses = sorted({m.group(1) for h in self._propfind(self.base + "/")
                        if (m := re.search(r"(\d{4}-\d{2})/?$", h))})
        if not meses:
            raise RuntimeError("Nenhum mês encontrado na Receita (o link pode ter mudado; veja o README).")
        return meses[-1]

    def arquivos(self, mes):
        return sorted({m.group(1) for h in self._propfind(f"{self.base}/{mes}/")
                       if (m := re.search(r"/([^/]+\.zip)$", h, re.I))})

    def baixar(self, mes, nome, pasta):
        import requests
        destino = Path(pasta) / nome
        url = f"{self.dav}/{mes}/{nome}"
        for tentativa in range(1, 6):
            try:
                log(f"  baixando {nome} (tentativa {tentativa})...")
                with requests.get(url, auth=(self.token, ""), stream=True, timeout=(30, 300)) as r:
                    r.raise_for_status()
                    with open(destino, "wb") as f:
                        for bloco in r.iter_content(1 << 20):
                            f.write(bloco)
                zipfile.ZipFile(destino).testzip()
                return destino
            except Exception as e:
                log(f"  erro: {e}")
                time.sleep(20 * tentativa)
        raise RuntimeError(f"Não consegui baixar {nome}")


class PastaLocal:
    def __init__(self, pasta):
        self.pasta = Path(pasta)

    def arquivos(self, mes):
        return sorted(p.name for p in self.pasta.glob("*.zip"))

    def baixar(self, mes, nome, pasta):
        return self.pasta / nome  # já está no disco


def linhas_zip(caminho, filtro=None):
    """Lê o CSV de dentro do zip da Receita (separador ;, latin-1, aspas).
    `filtro` recebe a linha crua e descarta na hora o que não interessa (bem mais rápido)."""
    with zipfile.ZipFile(caminho) as z:
        for membro in z.namelist():
            with z.open(membro) as bruto:
                for crua in io.TextIOWrapper(bruto, encoding="latin-1", newline=""):
                    if filtro and not filtro(crua):
                        continue
                    yield next(csv.reader([crua], delimiter=";", quotechar='"'))


class Downloads:
    """Baixa vários arquivos ao mesmo tempo (o servidor da Receita é lento por conexão)."""
    def __init__(self, fonte, mes, nomes, pasta, simultaneos=4):
        self.pool = ThreadPoolExecutor(max_workers=simultaneos)
        self.fut = {n: self.pool.submit(fonte.baixar, mes, n, pasta) for n in nomes}

    def caminho(self, nome):
        return self.fut[nome].result()


def processar(downloads, nomes, apagar, func, filtro=None):
    for nome in nomes:
        caminho = downloads.caminho(nome)
        log(f"  lendo {nome}...")
        for linha in linhas_zip(caminho, filtro):
            func(linha)
        if apagar:
            Path(caminho).unlink(missing_ok=True)


# ------------------------------------------------------------------ auxiliares
def carregar_municipios():
    tabela = {}
    with open(Path(__file__).parent / "municipios.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            tabela[int(r["siafi_id"])] = (r["nome"], float(r["latitude"]), float(r["longitude"]))
    return tabela


def espalhar(cnpj, lat, lng):
    """A Receita não dá coordenadas: colocamos a bolinha perto do centro da cidade,
    num ponto fixo (sempre o mesmo para o mesmo CNPJ) dentro de ~2,5 km."""
    h = hashlib.md5(cnpj.encode()).digest()
    a = int.from_bytes(h[:4], "big") / 2**32 * 2 * math.pi
    r = math.sqrt(int.from_bytes(h[4:8], "big") / 2**32) * 0.025
    return round(lat + r * math.sin(a), 5), round(lng + r * math.cos(a) / math.cos(math.radians(lat)), 5)


def telefone(ddd, num):
    ddd, num = re.sub(r"\D", "", ddd or ""), re.sub(r"\D", "", num or "")
    if not num:
        return ""
    return f"{ddd}{num}" if ddd else num


def data_iso(s):
    try:
        return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except Exception:
        return None


def limpar(s):
    return re.sub(r"\s+", " ", (s or "").strip())


# ------------------------------------------------------------------ principal
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--forcar", action="store_true")
    ap.add_argument("--pasta-local")
    ap.add_argument("--mes")
    args = ap.parse_args()

    cfg = carregar_config()
    uf = cfg["uf"].upper()
    estado = carregar_estado()
    fonte = PastaLocal(args.pasta_local) if args.pasta_local else Receita(cfg)
    mes = args.mes or (fonte.ultimo_mes() if isinstance(fonte, Receita) else dt.date.today().strftime("%Y-%m"))
    log(f"Mês mais recente na Receita: {mes} (último processado: {estado.get('ultimo_mes')})")

    gh_out = os.environ.get("GITHUB_OUTPUT")
    if estado.get("ultimo_mes") == mes and not args.forcar:
        log("Nada de novo. Saindo.")
        if gh_out:
            open(gh_out, "a").write("atualizou=nao\n")
        return

    arquivos = fonte.arquivos(mes)
    grupo = lambda prefixo: [a for a in arquivos if a.lower().startswith(prefixo)]
    estab, empresas, simples, cnaes = grupo("estabelecimento"), grupo("empresa"), grupo("simples"), grupo("cnae")
    if not estab:
        sys.exit("Não achei os arquivos Estabelecimentos*.zip")

    pasta_tmp = tempfile.mkdtemp(prefix="cnpj_")
    apagar = isinstance(fonte, Receita)
    hoje = dt.date.today()
    downloads = Downloads(fonte, mes, estab + empresas + simples + cnaes, pasta_tmp)

    # 1) estabelecimentos ativos do estado, abertos nos últimos DIAS_DETECCAO dias
    log(f"[1/4] Estabelecimentos de {uf}...")
    brutos = []
    limite_antigo = hoje - dt.timedelta(days=DIAS_MEMORIA + 60)

    def pega_estab(l):
        if len(l) < 28 or l[19] != uf or l[5] != "02":
            return
        d = data_iso(l[10])
        if not d or d < limite_antigo or d > hoje:
            return
        brutos.append((l, d))
    marca_uf = f';"{uf}";'
    processar(downloads, estab, apagar, pega_estab, lambda c: marca_uf in c)
    if not brutos:
        sys.exit(f"Nenhum estabelecimento ativo encontrado para {uf}.")
    ref = max(d for _, d in brutos)              # data mais recente presente nos dados
    inicio_deteccao = ref - dt.timedelta(days=DIAS_DETECCAO)
    inicio_mapa = ref - dt.timedelta(days=int(cfg["dias_no_mapa"]))
    inicio_memoria = ref - dt.timedelta(days=DIAS_MEMORIA)
    brutos = [(l, d) for l, d in brutos if d >= inicio_memoria]
    basicos = {l[0] for l, _ in brutos}
    log(f"  {len(brutos)} estabelecimentos desde {inicio_memoria} (dados até {ref})")

    # 2) razão social e porte; 3) MEI
    log("[2/4] Empresas (razão social e porte)...")
    info_emp = {}

    def pega_emp(l):
        if l and l[0] in basicos:
            info_emp[l[0]] = (limpar(l[1]), l[5] if len(l) > 5 else "")
    so_basicos = lambda c: c.lstrip('"')[:8] in basicos
    processar(downloads, empresas, apagar, pega_emp, so_basicos)

    log("[3/4] Simples/MEI...")
    mei = set()

    def pega_simples(l):
        if len(l) > 4 and l[0] in basicos and l[4] == "S" and not (l[6] if len(l) > 6 else "").strip("0 "):
            mei.add(l[0])
    processar(downloads, simples, apagar, pega_simples, so_basicos)

    desc_cnae = {}
    for nome in cnaes:
        for l in linhas_zip(downloads.caminho(nome)):
            if len(l) >= 2:
                desc_cnae[l[0]] = limpar(l[1])
    downloads.pool.shutdown()
    shutil.rmtree(pasta_tmp, ignore_errors=True)

    # 4) monta o mapa e descobre os novos
    log("[4/4] Montando mapa e comparando com o que já foi visto...")
    municipios = carregar_municipios()
    vistos = estado.get("vistos", {})           # cnpj -> lote ("" = carga inicial)
    primeira_vez = not vistos
    novos, linhas, cidades, idx_cidade, cnaes_usados = [], [], [], {}, {}
    novos_vistos = {}
    for l, d in sorted(brutos, key=lambda x: x[1], reverse=True):
        cnpj = l[0] + l[1] + l[2]
        if cnpj in vistos:
            lote = vistos[cnpj]
        elif primeira_vez or d < inicio_deteccao:
            lote = ""
        else:
            lote = mes
            novos.append(cnpj)
        novos_vistos[cnpj] = lote
        if d < inicio_mapa:
            continue
        mun = municipios.get(int(l[20])) if l[20].isdigit() else None
        nome_cidade = mun[0] if mun else l[20]
        if nome_cidade not in idx_cidade:
            idx_cidade[nome_cidade] = len(cidades)
            cidades.append(nome_cidade)
        lat, lng = espalhar(cnpj, mun[1], mun[2]) if mun else (None, None)
        razao, porte = info_emp.get(l[0], ("", ""))
        cnae = l[11]
        cnaes_usados[cnae] = desc_cnae.get(cnae, "")
        endereco = limpar(" ".join(x for x in [l[13], l[14]] if x))
        if l[15]:
            endereco += f", {limpar(l[15])}"
        if l[16]:
            endereco += f" - {limpar(l[16])}"
        linhas.append([cnpj, limpar(l[4]), razao, cnae, idx_cidade[nome_cidade], limpar(l[17]), endereco,
                       l[18], telefone(l[21], l[22]), telefone(l[23], l[24]), limpar(l[27]).lower(),
                       d.strftime("%Y%m%d"), porte, 1 if l[0] in mei else 0, lat, lng, lote])

    dados = {
        "uf": uf, "mes": mes, "referencia": ref.isoformat(),
        "atualizado": dt.datetime.now().isoformat(timespec="minutes"),
        "campos": ["cnpj", "fantasia", "razao", "cnae", "cidade", "bairro", "endereco", "cep",
                   "tel1", "tel2", "email", "abertura", "porte", "mei", "lat", "lng", "lote"],
        "cidades": cidades, "cnaes": cnaes_usados, "linhas": linhas,
    }
    salvar_mapa(dados, os.environ.get("SENHA_MAPA"))

    fila = [c for c in carregar_fila() if c in novos_vistos] + novos
    salvar_fila(fila)
    estado.update({"ultimo_mes": mes, "referencia": ref.isoformat(), "vistos": novos_vistos})
    salvar_estado(estado)
    log(f"Pronto: {len(linhas)} empresas no mapa, {len(novos)} novas nesta atualização.")

    site = cfg.get("site_url") or None
    if primeira_vez:
        notificar("Mapa de empresas pronto",
                  f"Carga inicial: {len(linhas):,} empresas abertas em {uf} nos últimos {cfg['dias_no_mapa']} dias. "
                  "A partir de agora você recebe só as novas.".replace(",", "."), site, ["white_check_mark"])
    else:
        notificar(f"{len(novos):,} empresas novas em {uf}".replace(",", "."),
                  f"Dados da Receita de {mes}. Toque para abrir o mapa.", site, ["new"], 4)
    if gh_out:
        open(gh_out, "a").write("atualizou=sim\n")


if __name__ == "__main__":
    main()
