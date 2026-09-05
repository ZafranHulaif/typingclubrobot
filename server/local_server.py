"""Backend lokal TypingBot - implementasi API.md untuk dev/test/emergency.

Stdlib saja + cryptography (tanda tangan Ed25519). State disimpan di
folder --store sehingga aman di-restart. Produksi memakai worker.js.

Pakai:  python server/local_server.py --port 8788 [--store DIR]
        [--keys FILE] [--admin KEY]
"""

import argparse
import base64
import hashlib
import html
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_TTL = 30 * 86400
EXE_NAME = "TypingBot.exe"

_lock = threading.Lock()
_keys = {}
_admin_key = ""


def _load_keys(path):
    global _keys
    if not os.path.exists(path):
        from gen_keys import generate
        generate(path)
    with open(path, encoding="utf-8") as f:
        _keys = json.load(f)


def _priv():
    der = base64.b64decode(_keys["priv_pkcs8_b64"])
    return serialization.load_der_private_key(der, password=None)


def _pub():
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(_keys["pub_hex"]))


def _sign(msg):
    return _priv().sign(msg.encode("utf-8")).hex()


def _verify(msg, sig_hex):
    try:
        _pub().verify(bytes.fromhex(sig_hex), msg.encode("utf-8"))
        return True
    except Exception:
        return False


def _make_token(mc):
    exp = int(time.time()) + TOKEN_TTL
    return {"mc": mc, "exp": exp, "sig": _sign(f"v1|{mc}|{exp}")}


def _token_ok(tok):
    try:
        if int(tok["exp"]) < int(time.time()):
            return False
        return _verify(f"v1|{tok['mc']}|{tok['exp']}", tok["sig"])
    except Exception:
        return False


class _Store:
    def __init__(self, folder):
        self.folder = folder
        os.makedirs(folder, exist_ok=True)

    def _path(self, name):
        return os.path.join(self.folder, name)

    def machines(self):
        try:
            with open(self._path("machines.json"), encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def save_machines(self, data):
        with open(self._path("machines.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)

    def release(self):
        try:
            with open(self._path("release.json"), encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def save_release(self, data):
        with open(self._path("release.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def exe_path(self):
        return self._path(EXE_NAME)


def _admin_page(store, key):
    machines = store.machines()

    def baris(m):
        tombol = []
        st = m.get("status")
        if st == "pending":
            tombol = [("Setujui", "approve", "#238636"),
                      ("Tolak", "deny", "#b62324")]
        elif st == "approved":
            tombol = [("Cabut akses", "revoke", "#b62324"),
                      ("Hapus", "delete", "#444a56")]
        else:
            tombol = [("Setujui ulang", "approve", "#238636"),
                      ("Hapus", "delete", "#444a56")]
        t = "".join(
            f'<form method="post" action="/admin/action" class="inl">'
            f'<input type="hidden" name="key" value="{html.escape(key)}">'
            f'<input type="hidden" name="mc" value="{html.escape(m["mc"])}">'
            f'<input type="hidden" name="act" value="{act}">'
            f'<button class="b" style="background:{col}">{txt}</button></form>'
            for txt, act, col in tombol)
        return ("<tr><td><b>" + html.escape(m.get("nickname", "?")) + "</b>"
                + f'<div class="dim">{html.escape(m["mc"])}</div></td>'
                + f'<td class="dim">{html.escape(str(m.get("app_version", "") or "-"))}</td>'
                + f'<td class="dim">{time.strftime("%d-%m-%Y %H:%M", time.gmtime(m.get("last_seen", 0) + 7 * 3600))} WIB</td>'
                + f"<td>{t}</td></tr>")

    def tabel(daftar):
        if not daftar:
            return '<div class="dim kosong">tidak ada</div>'
        return ('<table><tr><th>Mesin</th><th>Versi</th><th>Terakhir</th>'
                '<th>Aksi</th></tr>' + "".join(baris(m) for m in daftar)
                + "</table>")

    per_status = {}
    for m in machines.values():
        per_status.setdefault(m.get("status", "?"), []).append(m)
    for v in per_status.values():
        v.sort(key=lambda m: -m.get("last_seen", 0))
    menunggu = per_status.get("pending", [])
    oke = per_status.get("approved", [])
    buruk = per_status.get("denied", []) + per_status.get("revoked", [])
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TypingBot Admin</title><style>
body{{background:#141519;color:#e9eaee;font:14px/1.5 system-ui;margin:0;padding:20px}}
h1{{font-size:20px;margin:0 0 10px}}
.atas{{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:6px}}
.chip{{border-radius:12px;padding:3px 12px;font-size:12px;font-weight:600}}
.k{{background:#d2992222;color:#d29922}} .h{{background:#3fb95022;color:#3fb950}}
.x{{background:#f8514922;color:#f85149}}
.muat{{color:#e9eaee;background:#20232b;border:1px solid #2c303b;border-radius:8px;
padding:5px 12px;font-size:12px;cursor:pointer;text-decoration:none}}
.dim{{color:#9aa0ab;font-size:12px}} .kosong{{padding:10px 2px}}
.judul{{margin:18px 0 4px;font-weight:700;font-size:15px}}
table{{border-collapse:collapse;width:100%}}
td,th{{padding:8px 10px;border-bottom:1px solid #2c303b;text-align:left;vertical-align:top}}
.inl{{display:inline-block;margin:1px}} .b{{color:#fff;border:0;border-radius:6px;
padding:5px 10px;font-size:12px;cursor:pointer}}
</style></head><body>
<h1>⚡ TypingBot Admin</h1>
<div class="atas">
<span class="chip k">⏳ {len(menunggu)} menunggu</span>
<span class="chip h">✅ {len(oke)} disetujui</span>
<span class="chip x">⛔ {len(buruk)} ditolak/dicabut</span>
<a class="muat" href="/admin?key={html.escape(key)}">↻ Muat ulang</a>
<span class="dim">otomatis setiap 8 detik</span>
</div>
<div id="isi">
<div class="judul">⏳ Menunggu persetujuan</div>{tabel(menunggu)}
<div class="judul">✅ Disetujui</div>{tabel(oke)}
<div class="judul">⛔ Ditolak / dicabut</div>{tabel(buruk)}
</div>
<script>
setInterval(async()=>{{try{{
const r=await fetch(location.href);
const t=await r.text();
const d=new DOMParser().parseFromString(t,'text/html');
const n=d.getElementById('isi');
if(n)document.getElementById('isi').replaceWith(n);
}}catch(e){{}}}},8000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    store = None

    def log_message(self, fmt, *args):
        pass

    def _json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, code, text):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect_admin(self, key):
        self.send_response(302)
        self.send_header("Location", f"/admin?key={key}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _body_params(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        ctype = self.headers.get("Content-Type") or ""
        if "json" in ctype:
            try:
                return json.loads(raw.decode("utf-8")) if raw else {}
            except Exception:
                return {}
        return {k: v[0] for k, v in parse_qs(raw.decode("utf-8")).items()}

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/api/latest":
            rel = self.store.release()
            if not rel:
                return self._json(404, {"error": "no_release_yet"})
            return self._json(200, rel)
        if u.path == "/api/license/status":
            mc = (q.get("mc") or [""])[0]
            m = self.store.machines().get(mc)
            if not m or m["status"] not in ("approved",):
                st = m.get("status", "unknown") if m else "unknown"
                return self._json(200, {"status": st})
            with _lock:
                tok = _make_token(mc)
                m["last_seen"] = int(time.time())
                machines = self.store.machines()
                machines[mc] = m
                self.store.save_machines(machines)
            return self._json(200, {"status": "approved", "token": tok})
        if u.path == "/api/download":
            try:
                tok = json.loads(base64.b64decode(unquote((q.get("t") or [""])[0])))
            except Exception:
                tok = {}
            if not _token_ok(tok):
                return self._json(403, {"error": "bad_token"})
            path = self.store.exe_path()
            if not os.path.exists(path):
                return self._json(404, {"error": "no_release_yet"})
            size = os.path.getsize(path)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.end_headers()
            with open(path, "rb") as f:
                while True:
                    b = f.read(65536)
                    if not b:
                        break
                    self.wfile.write(b)
            return
        if u.path == "/admin":
            key = (q.get("key") or [""])[0]
            if key != _admin_key:
                return self._html(403, "<h3>kunci admin salah</h3>")
            return self._html(200, _admin_page(self.store, key))
        self._json(404, {"error": "not_found"})

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/api/license/request":
            data = self._body_params()
            mc = str(data.get("mc") or "")[:32]
            nick = str(data.get("nickname") or "?")[:40]
            ver = str(data.get("app_version") or "")[:16]
            if not mc:
                return self._json(400, {"error": "mc_required"})
            with _lock:
                machines = self.store.machines()
                m = machines.get(mc)
                if not m:
                    m = {"mc": mc, "status": "pending",
                         "first_seen": int(time.time())}
                    machines[mc] = m
                m["nickname"] = nick or m.get("nickname", "?")
                m["app_version"] = ver
                m["last_seen"] = int(time.time())
                self.store.save_machines(machines)
                if m["status"] == "approved":
                    return self._json(200, {"status": "approved",
                                            "token": _make_token(mc)})
            return self._json(200, {"status": m.get("status", "pending")})
        if u.path == "/api/publish":
            if self.headers.get("X-Admin-Key") != _admin_key:
                return self._json(403, {"error": "bad_admin_key"})
            ver = self.headers.get("X-Version") or ""
            if not ver:
                return self._json(400, {"error": "version_required"})
            n = int(self.headers.get("Content-Length") or 0)
            h = hashlib.sha256()
            tmp = self.store.exe_path() + ".part"
            got = 0
            with open(tmp, "wb") as f:
                while got < n:
                    b = self.rfile.read(min(65536, n - got))
                    if not b:
                        break
                    got += len(b)
                    h.update(b)
                    f.write(b)
            if got != n:
                os.remove(tmp)
                return self._json(400, {"error": "body_truncated"})
            os.replace(tmp, self.store.exe_path())
            rel = {"version": ver,
                   "sha256": h.hexdigest(),
                   "size": got,
                   "notes": self.headers.get("X-Notes") or "",
                   "released": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                             time.gmtime())}
            self.store.save_release(rel)
            return self._json(200, {"ok": True, "sha256": rel["sha256"],
                                    "size": got})
        if u.path == "/admin/action":
            q = parse_qs(u.query)
            data = self._body_params()
            for k in ("key", "mc", "act"):
                if k not in data:
                    data[k] = (q.get(k) or [""])[0]
            if data["key"] != _admin_key:
                return self._json(403, {"error": "bad_admin_key"})
            mc, act = data["mc"], data["act"]
            if act not in ("approve", "deny", "revoke", "pending", "delete"):
                return self._json(400, {"error": "bad_action"})
            with _lock:
                machines = self.store.machines()
                m = machines.get(mc)
                if not m:
                    return self._json(404, {"error": "unknown_mc"})
                if act == "delete":
                    machines.pop(mc, None)
                else:
                    m["status"] = {"approve": "approved", "deny": "denied",
                                    "revoke": "revoked", "pending": "pending"}[act]
                self.store.save_machines(machines)
            return self._redirect_admin(data["key"])
        self._json(404, {"error": "not_found"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8788)
    ap.add_argument("--store", default=os.path.join(HERE, "_store"))
    ap.add_argument("--keys", default=os.path.join(HERE, "_signing.json"))
    ap.add_argument("--admin", default="")
    a = ap.parse_args()
    global _admin_key
    _load_keys(a.keys)
    admin_file = os.path.join(os.path.dirname(os.path.abspath(a.keys)),
                              "_admin_key.txt")
    if a.admin:
        _admin_key = a.admin
    elif os.path.exists(admin_file):
        _admin_key = open(admin_file, encoding="utf-8").read().strip()
    else:
        import secrets
        _admin_key = secrets.token_hex(16)
        with open(admin_file, "w", encoding="utf-8") as f:
            f.write(_admin_key + "\n")
        print("ADMIN KEY baru:", _admin_key)
    Handler.store = _Store(a.store)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(f"local_server jalan di http://127.0.0.1:{a.port}")
    print("pub_hex:", _keys["pub_hex"])
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
