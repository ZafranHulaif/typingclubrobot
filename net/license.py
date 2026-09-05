"""Lisensi online: token Ed25519 yang diverifikasi offline.

File lisensi (license.dat) dua format: kunci lama (teks) atau token
online (satu baris JSON). Private key hanya ada di server; exe hanya
menanam SERVER_PUBLIC_KEY_HEX sehingga token tidak bisa dipalsukan.
"""

import base64
import json
import os
import sys
import time

from . import api

SERVER_PUBLIC_KEY_HEX = ""

_pub_cache = None


def _public_key():
    global _pub_cache
    if _pub_cache is not None:
        return _pub_cache
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    hexkey = os.environ.get("TYPINGBOT_SERVER_PUBKEY") or SERVER_PUBLIC_KEY_HEX
    if not hexkey and not getattr(sys, "frozen", False):
        try:
            here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            with open(os.path.join(here, "server", "_signing.json"),
                      encoding="utf-8") as f:
                hexkey = json.load(f)["pub_hex"]
        except Exception:
            hexkey = ""
    if not hexkey:
        return None
    _pub_cache = Ed25519PublicKey.from_public_bytes(bytes.fromhex(hexkey))
    return _pub_cache


def token_message(tok):
    return f"v1|{tok['mc']}|{tok['exp']}".encode("utf-8")


def verify_token(tok):
    """Cek tanda tangan + kedaluwarsa. True = masih sah (offline)."""
    if not isinstance(tok, dict):
        return False
    try:
        if int(tok["exp"]) < int(time.time()):
            return False
        pub = _public_key()
        if pub is None:
            return False
        pub.verify(bytes.fromhex(tok["sig"]), token_message(tok))
        return True
    except Exception:
        return False


def days_left(tok):
    try:
        return max(0, int((int(tok["exp"]) - time.time()) // 86400))
    except Exception:
        return 0


def load_token(path):
    try:
        with open(path, encoding="utf-8") as f:
            isi = f.read().strip()
        if not isi.startswith("{"):
            return None
        tok = json.loads(isi).get("token")
        return tok if isinstance(tok, dict) else None
    except Exception:
        return None


def save_token(path, tok):
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"v": 1, "token": tok}, ensure_ascii=False))


def request_approval(mc, nickname, app_version):
    status, data = api.http_json("POST", "/api/license/request",
                                 {"mc": mc, "nickname": nickname,
                                  "app_version": app_version})
    return data


def fetch_status(mc):
    status, data = api.http_json(
        "GET", "/api/license/status?mc=" + mc.replace("-", "%2D"))
    return data


def download_param(tok):
    import urllib.parse
    return urllib.parse.quote(base64.b64encode(
        json.dumps(tok).encode("utf-8")).decode("ascii"))
