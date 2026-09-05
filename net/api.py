"""HTTP tipis di atas urllib - tanpa dependency pihak ketiga.

BASE_URL dicari berurutan: env TYPINGBOT_SERVER_URL, file
server_url.txt di sebelah program, lalu konstanta DEFAULT_BASE_URL
(ditanam saat rilis). Kosong = fitur online mati (mode offline penuh).
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = ""

# Cloudflare menolak (error 1010) permintaan tanpa User-Agent - wajib ada.
USER_AGENT = "TypingBot/2.7 (+github.com/ZafranHulaif/typingclubrobot)"


def _program_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve_base():
    v = os.environ.get("TYPINGBOT_SERVER_URL")
    if v:
        return v.rstrip("/")
    try:
        p = os.path.join(_program_dir(), "server_url.txt")
        if os.path.exists(p):
            v = open(p, encoding="utf-8").read().strip()
            if v:
                return v.rstrip("/")
    except Exception:
        pass
    return DEFAULT_BASE_URL.rstrip("/")


BASE_URL = _resolve_base()


class Unreachable(Exception):
    """Server tidak bisa dihubungi (offline / URL salah)."""


def http_json(method, path, body=None, timeout=6):
    """Return (status_code, dict). Raise Unreachable bila koneksi gagal."""
    url = BASE_URL + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", USER_AGENT)
    if data is not None:
        req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8")
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        try:
            raw = e.read().decode("utf-8")
            return e.code, (json.loads(raw) if raw.strip() else {})
        except Exception:
            return e.code, {}
    except Exception as e:
        raise Unreachable(str(e)) from None


def http_download(path_or_url, dest_path, progress_cb=None, timeout=60):
    """Stream ke dest_path.part lalu rename. Return sha256 hexdigest.

    progress_cb(terunduh, total) dipanggil per chunk; total bisa None.
    """
    url = path_or_url if "://" in path_or_url else BASE_URL + path_or_url
    part = dest_path + ".part"
    import hashlib
    h = hashlib.sha256()
    got = 0
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            total = r.headers.get("Content-Length")
            total = int(total) if total else None
            with open(part, "wb") as f:
                while True:
                    b = r.read(1 << 16)
                    if not b:
                        break
                    got += len(b)
                    h.update(b)
                    f.write(b)
                    if progress_cb:
                        try:
                            progress_cb(got, total)
                        except Exception:
                            pass
    except Exception as e:
        try:
            os.remove(part)
        except Exception:
            pass
        raise Unreachable(str(e)) from None
    if os.path.exists(dest_path):
        os.remove(dest_path)
    os.replace(part, dest_path)
    return h.hexdigest()


def fetch_latest():
    """Info rilis terbaru, atau None bila belum ada rilis."""
    status, data = http_json("GET", "/api/latest")
    if status == 200:
        return data
    return None
