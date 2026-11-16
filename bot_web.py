"""TypingBot Edisi Web - lintas platform (macOS / Linux / Windows / Termux).

Cangkang Windows (WebView2 ter-embed) memang Windows-saja, tapi MESIN bot
(engine/) itu Python murni + Playwright-over-CDP: dia tidak peduli OS.
Edisi web ini menjalankan mesin yang SAMA terhadap browser Chromium mana
pun yang punya port debug:

  - macOS / Linux / Windows : cari & luncurkan Chrome/Brave/Edge/Chromium
    terpasang (jendela terlihat, login tinggal sekali di profil khusus bot)
  - --headless              : chromium tanpa jendela (server, Termux);
    login lewat form di panel web
  - --cdp 9222              : tempel ke browser yang SUDAH jalan dengan
    port debug (mis. Kiwi Browser Android yang dijembatani socat)

Panel kontrol = halaman web di http://localhost:8765 (Mulai/Berhenti/Jeda,
kecepatan, login, log). Tidak ada dependensi baru: stdlib + playwright.

Mesin disentuh lewat monkeypatch POSIX saja - engine/ tak diubah satu
baris pun, jadi aplikasi Windows tetap 100% seperti yang dirilis.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

_REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _REPO)

from engine import state          # noqa: E402
from engine import browser        # noqa: E402
from engine import config         # noqa: E402
from engine import supervisor     # noqa: E402
from engine import hotkeys        # noqa: E402

# ---------------------------------------------------------------- log
_LOG = deque(maxlen=300)
_LOGKUNCI = threading.Lock()


class _Tee:
    """Tangkap print engine (dan milik kita) ke deque untuk panel."""

    def __init__(self, asli):
        self._asli = asli

    def write(self, s):
        try:
            if s and s.strip():
                with _LOGKUNCI:
                    _LOG.append(s.rstrip("\n")[:300])
        except Exception:
            pass
        try:
            return self._asli.write(s)
        except Exception:
            return len(s)

    def flush(self):
        try:
            return self._asli.flush()
        except Exception:
            pass

    def __getattr__(self, nama):     # isatty dkk
        return getattr(self._asli, nama)


# ------------------------------------------------- patch POSIX engine
_BROWSER_POSIX = [
    # (nama, daftar path kandidat, nama proses)
    ("Chrome", [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
        "/snap/bin/chromium", "/usr/bin/chromium-browser",
    ], "chrome"),
    ("Chromium", [
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/usr/bin/chromium", "/usr/bin/chromium-browser",
    ], "chromium"),
    ("Brave", [
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "/usr/bin/brave-browser", "/usr/bin/brave",
    ], "brave"),
    ("Edge", [
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/usr/bin/microsoft-edge", "/usr/bin/microsoft-edge-stable",
    ], "edge"),
]


def _pasang_patch_posix():
    if sys.platform == "win32":
        return          # Windows: pakai engine apa adanya
    import shlex

    def _run_hidden(cmd, **kw):
        kw.pop("creationflags", None)
        return subprocess.run(cmd, **kw)

    def _popen_latar(cmd, **kw):
        kw.pop("creationflags", None)
        kw.setdefault("stdout", subprocess.DEVNULL)
        kw.setdefault("stderr", subprocess.DEVNULL)
        return subprocess.Popen(cmd, **kw)

    def _find_browser():
        for pick in (state.FORCE_BROWSER,
                     os.environ.get("TYPINGBOT_BROWSER", "")):
            pick = (pick or "").strip()
            if pick:
                b = os.path.basename(pick).lower()
                cocok = next((c for c in _BROWSER_POSIX
                              if c[2] in b or b.startswith(c[2])), None)
                if cocok:
                    return {"name": cocok[0], "exe": pick,
                            "proc": cocok[2]}
                if os.path.isfile(pick):
                    return {"name": os.path.basename(pick), "exe": pick,
                            "proc": "chrome"}
                print(f"Browser pilihan ({pick}) tidak ada, deteksi otomatis.")
        for nm, paths, proc in _BROWSER_POSIX:
            for p in paths:
                if p and os.path.isfile(p):
                    return {"name": nm, "exe": p, "proc": proc}
        return None

    def _browser_running():
        proc = (state.BROWSER or {}).get("proc", "chrome")
        try:
            out = subprocess.run(["pgrep", "-f", proc],
                                 capture_output=True, text=True,
                                 timeout=5).stdout
            return bool(out.strip())
        except Exception:
            return False

    def _port_holders():
        """PID+nama pemegang port debug, via lsof. [(pid, nama)]"""
        try:
            out = subprocess.run(
                ["lsof", "-t", "-i", f":{state.DEBUG_PORT}", "-sTCP:LISTEN"],
                capture_output=True, text=True, timeout=5).stdout
            hasil = []
            for pid in out.split():
                try:
                    comm = open(f"/proc/{pid}/comm").read().strip()
                except Exception:
                    try:
                        comm = subprocess.run(
                            ["ps", "-p", pid, "-o", "comm="],
                            capture_output=True, text=True).stdout.strip()
                    except Exception:
                        comm = "?"
                hasil.append((int(pid), comm))
            return hasil
        except Exception:
            return []

    def _free_port(tanya_semua=True):
        """Bebaskan port HANYA dari proses browser (aman: jangan pernah
        membunuh proses tak dikenal di unix)."""
        for pid, nama in _port_holders():
            kandidat = ("chrome", "chromium", "brave", "edge", "msedge")
            if not any(k in nama.lower() for k in kandidat):
                print(f"Port {state.DEBUG_PORT} dipegang '{nama}' "
                      "(bukan browser) - tidak dibunuh otomatis.")
                continue
            try:
                subprocess.run(["kill", "-9", str(pid)], timeout=5)
                print(f"Menutup pemegang port lama: {nama} (PID {pid})")
            except Exception:
                pass
        time.sleep(0.5)
        return not _port_holders()

    def _profile_dir_arg(nama):
        # unix: Chromium 136+ juga menolak debug di profil asli ->
        # selalu profil khusus bot (DEDICATED_PROFILE)
        return ""

    def _list_profiles(nama):
        return []

    browser._run_hidden = _run_hidden
    browser._popen_latar = _popen_latar
    browser._find_browser = _find_browser
    browser._browser_running = _browser_running
    browser._port_holders = _port_holders
    browser._free_port = _free_port
    try:
        import engine.profiles as _prof
        _prof._profile_dir_arg = _profile_dir_arg
        _prof._list_profiles = _list_profiles
    except Exception:
        pass
    # web = tanpa dialog: izin tutup browser lama otomatis (dilog)
    state._confirmer = lambda nama, pid, exe="": True
    print("Patch POSIX engine terpasang.")


# --------------------------------------------------------- headless
def _chromium_headless_path():
    """Cari binary chromium: bundle playwright dulu, lalu browser
    sistem (semua Chromium boleh - Edge/Brave/Chrome juga bisa
    headless + port debug)."""
    kandidat = []
    la = os.environ.get("LOCALAPPDATA")
    if la:
        kandidat += glob.glob(os.path.join(
            la, "ms-playwright", "chromium-*", "chrome-win*", "chrome.exe"))
    kandidat += glob.glob(os.path.expanduser(
        "~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome"))
    kandidat += glob.glob(os.path.expanduser(
        "~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/"
        "Chromium.app/Contents/MacOS/Chromium"))
    pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    pfx86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
    kandidat += [
        os.path.join(pf, "BraveSoftware", "Brave-Browser",
                     "Application", "brave.exe"),
        os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(pfx86, "Microsoft", "Edge", "Application",
                     "msedge.exe"),
        os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     "Google", "Chrome Application", "chrome.exe"),
        "/usr/bin/chromium", "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome", "/usr/bin/brave-browser",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    ]
    for k in kandidat:
        if k and os.path.isfile(k):
            return k
    return None


# ------------------------------------------------------------ worker
Worker = threading.Lock()
_status = {"jalan": False, "mood": ""}


def _worker(args):
    """Kabel yang sama dengan GUI: connect -> main_loop -> disconnect.
    Objek Playwright TIDAK boleh lintas thread - semuanya di sini."""
    try:
        state.STOP = False
        state.PAUSED = False
        state.BROWSER_WV2 = False
        if args.headless:
            exe = _chromium_headless_path()
            if not exe:
                print("Chromium tidak ketemu (bundle playwright atau "
                      "browser sistem). Jalankan:")
                print("  python -m playwright install chromium")
                return
            browser._pick_port()
            prof = os.path.join(_profil_dasar(), "headless")
            os.makedirs(prof, exist_ok=True)
            print(f"Chromium headless: {exe} port {state.DEBUG_PORT}")
            proc = subprocess.Popen(
                [exe, "--headless=new", "--no-first-run",
                 "--no-default-browser-check", "--disable-gpu",
                 f"--remote-debugging-port={state.DEBUG_PORT}",
                 f"--user-data-dir={prof}", "about:blank"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(40):
                if browser._check_debug_port().startswith("Chrome"):
                    break
                time.sleep(0.5)
            state.BROWSER = {"name": "Chromium (headless)", "exe": exe,
                             "proc": "chrome"}
        elif args.cdp:
            state.DEBUG_PORT = int(args.cdp.rstrip("/").split(":")[-1])
            state.BROWSER = {"name": "Browser jarak jauh (CDP)",
                             "exe": "", "proc": "chrome"}
        else:
            browser.ensure_browser()     # cari/luncurkan + pilih port
        _status["jalan"] = True
        _status["mood"] = "menyambung..."
        browser.connect()
        _status["mood"] = "mengetik..."
        supervisor.main_loop()
    except SystemExit:
        _status["mood"] = "berhenti (lihat log)"
    except BaseException as ex:
        _status["mood"] = f"error: {ex}"
    finally:
        _status["jalan"] = False
        try:
            browser.disconnect()
        except Exception:
            pass
        print("Bot berhenti.")


def _profil_dasar():
    d = os.path.join(os.path.expanduser("~"), ".typingbot")
    os.makedirs(d, exist_ok=True)
    return d


def _mulai_worker(args):
    if not Worker.acquire(blocking=False):
        return "Sudah jalan."
    t = threading.Thread(target=_worker, args=(args,), daemon=True)
    t.start()
    return "OK"


# -------------------------------------------------------------- HTTP
HALAMAN = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TypingBot - Edisi Web</title>
<style>
:root{--bg:#0f1115;--card:#171a21;--fg:#e8eaf0;--mute:#8b93a7;
--hijau:#22c55e;--merah:#ef4444;--kuning:#eab308;--biru:#3b82f6}
*{box-sizing:border-box;margin:0}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,
 -apple-system,sans-serif;display:flex;justify-content:center;padding:24px}
.card{background:var(--card);border-radius:14px;padding:22px;width:100%;
max-width:520px;box-shadow:0 8px 30px rgba(0,0,0,.4)}
h1{font-size:19px;margin-bottom:2px}
.sub{color:var(--mute);font-size:13px;margin-bottom:16px}
.status{display:flex;align-items:center;gap:8px;margin-bottom:14px;
font-weight:600;font-size:17px}
.dot{width:11px;height:11px;border-radius:50%;background:var(--mute)}
.dot.jalan{background:var(--hijau);animation:pal 1.2s infinite}
.dot.jeda{background:var(--kuning)}
@keyframes pal{50%{opacity:.4}}
.baris{display:flex;gap:8px;margin-bottom:12px}
button{flex:1;padding:11px;border:0;border-radius:9px;font-weight:600;
font-size:15px;cursor:pointer;color:#fff}
button:disabled{opacity:.4;cursor:default}
#mulai{background:var(--hijau)}#stop{background:var(--merah)}
#jeda{background:#3f4658}
.cep{display:flex;gap:8px;align-items:center;margin-bottom:14px}
.cep input{flex:1;padding:9px;border-radius:8px;border:1px solid #2a2f3a;
background:#0d1017;color:var(--fg);font-size:15px}
.cep span{color:var(--mute);font-size:13px;white-space:nowrap}
.login{border-top:1px solid #262b36;padding-top:14px;margin-top:4px}
.login h3{font-size:14px;color:var(--mute);font-weight:500;margin-bottom:8px}
.login input{width:100%;padding:9px;margin-bottom:8px;border-radius:8px;
border:1px solid #2a2f3a;background:#0d1017;color:var(--fg);font-size:14px}
.login button{background:var(--biru);width:100%}
.log{background:#0a0d12;border-radius:9px;padding:10px;height:170px;
overflow-y:auto;font:11.5px/1.45 ui-monospace,monospace;color:#9aa4b8;
white-space:pre-wrap;margin-top:14px}
.info{color:var(--mute);font-size:12.5px;margin-top:10px}
</style></head><body><div class="card">
<h1>TypingBot <span style="color:var(--mute);font-weight:400;font-size:14px">
edisi web</span></h1>
<div class="sub">mesin yang sama dengan aplikasi Windows, lewat browsermu</div>
<div class="status"><div class="dot" id="dot"></div><span id="st">Memuat…</span>
</div>
<div class="baris">
<button id="mulai" onclick="api('start')">Mulai</button>
<button id="jeda" onclick="api('pause')">Jeda</button>
<button id="stop" onclick="api('stop')">Berhenti</button>
</div>
<div class="cep"><input id="wpm" type="number" min="20" max="800" value="400">
<span>wpm <button style="flex:0;padding:9px 14px;background:#3f4658"
 onclick="api('speed')">pasang</button></span></div>
<div class="login">
<h3>Login edclub (untuk mode headless; mode browser biasa: login
langsung di jendela browser)</h3>
<input id="email" type="email" placeholder="email" autocomplete="off">
<input id="sandi" type="password" placeholder="sandi">
<button onclick="api('login')">Masuk</button>
</div>
<div class="log" id="log"></div>
<div class="info" id="info"></div>
</div>
<script>
async function api(a){
  if(a==='login') body={email:email.value,sandi:sandi.value};
  else if(a==='speed') body={wpm:+wpm.value};
  else body={};
  await fetch('/api/'+a,{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify(body)});
  muat();
}
async function muat(){
  try{
    const s=await (await fetch('/api/status')).json();
    st.textContent=s.label;
    dot.className='dot '+(s.jalan?(s.jeda?'jeda':'jalan'):'');
    info.textContent=(s.browser?('browser: '+s.browser+' · '):'')+
      (s.url?('halaman: '+s.url.slice(0,60)):'')+
      (s.level?(' · level: '+s.level):'');
    wpm.value=s.wpm;
    log.textContent=s.log.slice(-2200);
    log.scrollTop=log.scrollHeight;
  }catch(e){}
}
setInterval(muat,1200);muat();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):     # senyap (log panel sudah dari engine)
        pass

    def _kirim(self, kode, tipe, isi: bytes):
        self.send_response(kode)
        self.send_header("Content-Type", tipe)
        self.send_header("Content-Length", str(len(isi)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(isi)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._kirim(200, "text/html; charset=utf-8",
                        HALAMAN.encode("utf-8"))
        elif self.path == "/api/status":
            with _LOGKUNCI:
                tail = list(_LOG)[-40:]
            wpm = state.SPEED_WPM or config.SPEEDS[state.SPEED_IDX][0]
            st = {
                "jalan": _status["jalan"],
                "jeda": bool(state.PAUSED),
                "label": ("JEDA" if state.PAUSED else
                          ("BERJALAN" if _status["jalan"] else
                           (_status["mood"] or "SIAGA"))),
                "browser": (state.BROWSER or {}).get("name", ""),
                "url": (state.PAGE.url if state.PAGE else "")[:120],
                "level": state.STATUS_LABEL or "",
                "wpm": wpm,
                "log": "\n".join(tail),
            }
            self._kirim(200, "application/json",
                        json.dumps(st).encode("utf-8"))
        else:
            self._kirim(404, "text/plain", b"404")

    def do_POST(self):
        rute = urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        try:
            badan = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            badan = {}
        jawab = "OK"
        if rute == "/api/start":
            jawab = _mulai_worker(ARGS)
        elif rute == "/api/stop":
            hotkeys._stop_bot()
            jawab = "STOP diminta."
        elif rute == "/api/pause":
            hotkeys._toggle_pause()
            jawab = "Jeda."
        elif rute == "/api/speed":
            try:
                state.SPEED_WPM = max(20, min(800, int(badan.get("wpm", 0))))
                jawab = f"Kecepatan: {state.SPEED_WPM} wpm"
            except Exception:
                jawab = "wpm tidak valid"
        elif rute == "/api/login":
            jawab = _login(badan.get("email", ""), badan.get("sandi", ""))
        else:
            jawab = "?"
        self._kirim(200, "application/json",
                    json.dumps({"hasil": jawab}).encode("utf-8"))


def _login(email, sandi):
    """Isi form login edclub di halaman /signin (mode headless)."""
    pg = state.PAGE
    if not pg:
        return "Belum ada halaman - klik Mulai dulu."
    try:
        u = pg.url or ""
    except Exception:
        return "Halaman tidak siap."
    if "/signin" not in u:
        try:
            pg.goto(config.LOGIN_URL_INDIVIDUAL,
                    timeout=15000)
        except Exception:
            try:
                pg.goto("https://www.edclub.com/signin/", timeout=15000)
            except Exception:
                return "Gagal membuka /signin."
    try:
        pg.fill("input[type=email], input[name=email]", email, timeout=5000)
        pg.fill("input[type=password], input[name=password]", sandi,
                timeout=5000)
        pg.press("input[type=password], input[name=password]", "Enter",
                 timeout=5000)
        return "Login dikirim - lihat log."
    except Exception as ex:
        return f"Form login tidak ketemu: {str(ex)[:80]}"


# --------------------------------------------------------------- main
ARGS = None


def main():
    global ARGS
    ap = argparse.ArgumentParser(
        description="TypingBot Edisi Web (macOS/Linux/Termux/Windows)")
    ap.add_argument("--port", type=int, default=8765,
                    help="port panel web (default 8765)")
    ap.add_argument("--browser", default="",
                    help="path exe browser (kosong = deteksi otomatis)")
    ap.add_argument("--headless", action="store_true",
                    help="chromium playwright tanpa jendela (server/Termux)")
    ap.add_argument("--cdp", default="",
                    help="tempel browser yang sudah jalan: 9222 / "
                         "http://127.0.0.1:9222 (mis. socat Kiwi Android)")
    ap.add_argument("--smoke", action="store_true",
                    help="cek diri lalu keluar (untuk CI)")
    ARGS = ap.parse_args()

    sys.stdout = _Tee(sys.stdout)
    sys.stderr = _Tee(sys.stderr)
    _pasang_patch_posix()
    state.BROWSER_WV2 = False
    if ARGS.browser:
        state.FORCE_BROWSER = ARGS.browser

    if ARGS.smoke:
        # cek diri: panel hidup + (headless) binary chromium ada
        if ARGS.headless and not _chromium_headless_path():
            print("SMOKE GAGAL: chromium playwright tidak ketemu")
            sys.exit(1)
        srv = ThreadingHTTPServer(("127.0.0.1", ARGS.port), Handler)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        import urllib.request
        d = urllib.request.urlopen(
            f"http://127.0.0.1:{ARGS.port}/api/status", timeout=5).read()
        assert json.loads(d)["label"]
        h = urllib.request.urlopen(
            f"http://127.0.0.1:{ARGS.port}/", timeout=5).read()
        assert b"TypingBot" in h
        srv.shutdown()
        print("SMOKE OK")
        return

    if ARGS.headless and not _chromium_headless_path():
        print("Chromium playwright belum ada. Jalankan dulu:")
        print("  python -m playwright install chromium")
        sys.exit(1)

    srv = ThreadingHTTPServer(("0.0.0.0", ARGS.port), Handler)
    print(f"Panel TypingBot: http://localhost:{ARGS.port}")
    if ARGS.cdp:
        print(f"Mode CDP: menempel ke port debug {ARGS.cdp}")
    elif ARGS.headless:
        print("Mode headless: login lewat form di panel.")
    else:
        print("Mode browser: bot akan membuka Chrome/Brave/Edge "
              "dengan profil khusus bot (~/.typingbot).")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("Sampai jumpa!")
        hotkeys._stop_bot()


if __name__ == "__main__":
    main()
