"""Funções compartilhadas: configuração, estado, criptografia e notificação (ntfy)."""
import gzip
import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DOCS = RAIZ / "docs"
DADOS = RAIZ / "dados"
ARQ_ESTADO = DADOS / "estado.json.gz"
ARQ_FILA = DADOS / "fila.json"
ARQ_MAPA_ABERTO = DOCS / "dados.json"
ARQ_MAPA_CRIPTO = DOCS / "dados.bin"
MAGICO = b"CNPJ1"
ITERACOES = 250_000


def log(*a):
    print(*a, flush=True)


def carregar_config():
    with open(RAIZ / "config.json", encoding="utf-8") as f:
        return json.load(f)


def carregar_estado():
    if ARQ_ESTADO.exists():
        with gzip.open(ARQ_ESTADO, "rt", encoding="utf-8") as f:
            return json.load(f)
    return {"ultimo_mes": None, "vistos": {}}


def salvar_estado(estado):
    DADOS.mkdir(exist_ok=True)
    with gzip.open(ARQ_ESTADO, "wt", encoding="utf-8") as f:
        json.dump(estado, f, separators=(",", ":"))


def carregar_fila():
    if ARQ_FILA.exists():
        return json.loads(ARQ_FILA.read_text(encoding="utf-8"))
    return []


def salvar_fila(fila):
    DADOS.mkdir(exist_ok=True)
    ARQ_FILA.write_text(json.dumps(fila), encoding="utf-8")


# ---------- criptografia (para o mapa não ficar aberto na internet) ----------

def _chave(senha: str, sal: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=sal, iterations=ITERACOES)
    return kdf.derive(senha.encode("utf-8"))


def salvar_mapa(dados: dict, senha: str | None):
    """Grava os dados do mapa. Com senha: docs/dados.bin (gzip + AES-GCM). Sem senha: docs/dados.json."""
    DOCS.mkdir(exist_ok=True)
    bruto = gzip.compress(json.dumps(dados, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9)
    if senha:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        sal, iv = os.urandom(16), os.urandom(12)
        cifrado = AESGCM(_chave(senha, sal)).encrypt(iv, bruto, None)
        ARQ_MAPA_CRIPTO.write_bytes(MAGICO + sal + iv + cifrado)
        ARQ_MAPA_ABERTO.unlink(missing_ok=True)
        log(f"Mapa salvo com senha em {ARQ_MAPA_CRIPTO.name} ({len(cifrado)/1e6:.1f} MB)")
    else:
        ARQ_MAPA_ABERTO.write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        ARQ_MAPA_CRIPTO.unlink(missing_ok=True)
        log("AVISO: SENHA_MAPA não definida — dados.json ficou SEM senha.")


def ler_mapa(senha: str | None):
    if ARQ_MAPA_CRIPTO.exists():
        if not senha:
            sys.exit("dados.bin existe mas SENHA_MAPA não foi informada.")
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        b = ARQ_MAPA_CRIPTO.read_bytes()
        assert b[:5] == MAGICO, "arquivo dados.bin inválido"
        sal, iv, cifrado = b[5:21], b[21:33], b[33:]
        bruto = AESGCM(_chave(senha, sal)).decrypt(iv, cifrado, None)
        return json.loads(gzip.decompress(bruto))
    if ARQ_MAPA_ABERTO.exists():
        return json.loads(ARQ_MAPA_ABERTO.read_text(encoding="utf-8"))
    return None


# ---------- notificação no celular (app ntfy, Android/iPhone) ----------

def notificar(titulo: str, mensagem: str, clique: str | None = None, tags=None, prioridade=3):
    topico = os.environ.get("NTFY_TOPICO", "").strip()
    if not topico:
        log(f"[sem NTFY_TOPICO, notificação não enviada] {titulo} — {mensagem}")
        return False
    import requests
    servidor = os.environ.get("NTFY_SERVIDOR", "https://ntfy.sh").rstrip("/")
    corpo = {"topic": topico, "title": titulo, "message": mensagem, "priority": prioridade}
    if clique:
        corpo["click"] = clique
    if tags:
        corpo["tags"] = tags
    r = requests.post(servidor, json=corpo, timeout=30)
    if r.status_code >= 300:
        log(f"Falha ao notificar ({r.status_code}): {r.text[:200]}")
        return False
    return True
