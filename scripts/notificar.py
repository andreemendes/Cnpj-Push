"""
Envia para o celular, uma por uma, as próximas empresas novas da fila
(no máximo `notificacoes_por_dia` do config.json a cada execução).
Tocar na notificação abre o mapa já na bolinha daquela empresa.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from comum import carregar_config, carregar_fila, salvar_fila, ler_mapa, notificar, log


def fone(t):
    if len(t) >= 10:
        return f"({t[:2]}) {t[2:-4]}-{t[-4:]}"
    return t


def main():
    cfg = carregar_config()
    fila = carregar_fila()
    if not fila:
        log("Fila vazia.")
        return
    dados = ler_mapa(os.environ.get("SENHA_MAPA"))
    if not dados:
        log("Mapa ainda não existe.")
        return
    campos = dados["campos"]
    por_cnpj = {l[0]: dict(zip(campos, l)) for l in dados["linhas"]}
    fila = [c for c in fila if c in por_cnpj]       # tira o que já saiu do mapa
    limite = int(cfg.get("notificacoes_por_dia", 10))
    site = (cfg.get("site_url") or "").rstrip("/")
    enviados = 0
    while fila and enviados < limite:
        e = por_cnpj[fila[0]]
        nome = e["fantasia"] or e["razao"] or e["cnpj"]
        ramo = dados["cnaes"].get(e["cnae"], "")
        cidade = dados["cidades"][e["cidade"]]
        partes = [ramo, f"{cidade} · {e['bairro']}" if e["bairro"] else cidade]
        if e["tel1"]:
            partes.append("Tel " + fone(e["tel1"]))
        if e["mei"]:
            partes.append("MEI")
        clique = f"{site}/#c{e['cnpj']}" if site else None
        if not notificar(f"Nova empresa: {nome}", "\n".join(p for p in partes if p), clique, ["office"]):
            break
        fila.pop(0)
        enviados += 1
    salvar_fila(fila)
    log(f"{enviados} notificações enviadas, {len(fila)} ainda na fila.")


if __name__ == "__main__":
    main()
