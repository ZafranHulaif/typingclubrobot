"""
autopilot_pw.py - Bot TypingClub (edclub.com) versi Playwright.

KEUNGGULAN dibanding autopilot.py (Selenium):
- BEKERJA DI BACKGROUND: bot terus mengetik walau Anda memakai program lain,
  karena semua input dikirim via CDP (protokol internal browser), bukan
  tombol fisik. Tidak ada lagi syarat "Brave harus fokus".
- Semua iframe (termasuk cross-origin) langsung tersedia tanpa rekursi manual.

Logika level sama persis dengan versi Selenium (sudah teruji):
- Lesson standar, tutorial boxed (spasi nbsp), hold-key while typing,
  intro "Type the f key", video (play + 16x + seek), layar skor (Enter),
  minigame Phaser via core API, fallback OCR canvas, penutup pop-up
  achievement/iklan premium.

Cara pakai:
1. python autopilot_pw.py   -> Brave debug dibuka OTOMATIS kalau belum jalan.
2. Login edclub.com, buka level pertama.
3. Silakan pakai PC untuk hal lain; bot jalan terus di belakang.
Stop: Ctrl+C di terminal.
"""

import asyncio
import ctypes
import io
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

from PIL import Image
from playwright.sync_api import sync_playwright

# Windows: granularitas time.sleep() default ~15.6 ms - membuat jeda ketik
# (5-40 ms) selalu membulat ke atas dan laju jauh di bawah target. Naikkan
# resolusi timer ke 1 ms selama proses hidup.
try:
    _winmm = ctypes.windll.winmm
    _winmm.timeBeginPeriod(1)
    import atexit
    atexit.register(lambda: _winmm.timeEndPeriod(1))
except Exception:
    pass

try:
    import keyboard as _kb
    HAVE_HOTKEY = True
except Exception:
    HAVE_HOTKEY = False

# output selalu langsung tampil (penting untuk .exe yang di-capture/di-pipe)
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass


# Log file otomatis: semua output console tetap tampil, tapi juga tersalin
# ke bot.log di samping skrip (sama seperti versi GUI). Jadi log tinggal
# dibaca dari file, tidak perlu copy-paste manual dari terminal.
class _TeeWriter:
    def __init__(self, stream, logpath):
        self._stream = stream
        try:
            self._log = open(logpath, "a", encoding="utf-8", buffering=1)
        except Exception:
            self._log = None

    def write(self, s):
        try:
            self._stream.write(s)
        except Exception:
            pass
        try:
            if self._log and s.strip():
                self._log.write(s)
        except Exception:
            pass
        return len(s)

    def flush(self):
        try:
            self._stream.flush()
        except Exception:
            pass
        try:
            if self._log:
                self._log.flush()
        except Exception:
            pass

    def fileno(self):
        # beberapa modul (faulthandler, subprocess) butuh fd sungguhan
        return self._stream.fileno()

    def isatty(self):
        try:
            return self._stream.isatty()
        except Exception:
            return False


try:
    # saat di-bundle jadi .exe, __file__ menunjuk folder temp PyInstaller
    # yang dihapus saat program keluar -> pakai lokasi .exe sendiri.
    _BASE = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
             else os.path.dirname(os.path.abspath(__file__)))
    _LOG_PATH = os.path.join(_BASE, "bot.log")
    sys.stdout = _TeeWriter(sys.stdout, _LOG_PATH)
    sys.stderr = _TeeWriter(sys.stderr, _LOG_PATH)
    print(f"== sesi {time.strftime('%Y-%m-%d %H:%M:%S')} ==")
except Exception:
    pass

# ---------------------------------------------------------------------------
# Kontrol: hotkey global (F9 pause, F10 kecepatan, F11 stop)
# ---------------------------------------------------------------------------

PAUSED = False
STOP = False
PERLU_LOGIN = False      # True = sesi edclub mati; GUI memunculkan popup login
MINTA_LOGIN_NAV = False   # GUI meminta bot membuka halaman login edclub
MINTA_LOGIN_URL = ""      # URL login pilihan GUI (individu / sekolah)
LOGIN_DICEK = False       # True setelah patroli login berjalan minimal 1x
TUNGGU_RENTANG = False    # True = GUI sedang menanya rentang; bot menunggu
LOGIN_URL_INDIVIDU = "https://www.edclub.com/signin"   # Individual Edition
LOGIN_URL_SEKOLAH = "https://sportal.edclub.com/"      # akun sekolah (Google)
MINTA_BANGUN_PETA = False # GUI meminta bot membangun peta level lengkap
RENTANG_SELESAI = False   # True = mencapai level akhir rentang pilihan user
LEVEL_START = 1           # rentang level pilihan user (GUI)
LEVEL_END = 0             # 0 = tanpa batas akhir
RENTANG_SIAP = False      # True setelah user menjawab dialog rentang di Start
MENUNGGU_SETUP = False    # True = menunggu user menyelesaikan set-up first-run browser
HOTKEY_AKTIF = True       # False = F9/F10/F11 diabaikan (toggle GUI)
SPEEDS = [(140, "NORMAL (140 wpm)"), (200, "CEPAT (200 wpm)"), (85, "SANTAI (85 wpm)")]
SPEED_IDX = 0


def _toggle_pause():
    global PAUSED
    PAUSED = not PAUSED
    print(f">>> {'JEDA (paused)' if PAUSED else 'LANJUT (resume)'} <<<", flush=True)


def _cycle_speed():
    global SPEED_IDX
    SPEED_IDX = (SPEED_IDX + 1) % len(SPEEDS)
    print(f">>> KECEPATAN: {SPEEDS[SPEED_IDX][1]} <<<", flush=True)


def _stop_bot():
    global STOP
    STOP = True
    print(">>> STOP diminta, menutup bot... <<<", flush=True)


# Wrapper cek HOTKEY_AKTIF: hook keyboard tidak dilepas-lepas saat toggle
# (re-hook bisa gagal diam-diam) - cukup diabaikan saat nonaktif. User bisa
# memakai F9/F10/F11 untuk aplikasi lain tanpa takut menggerakkan bot.
def _hk_pause():
    if HOTKEY_AKTIF:
        _toggle_pause()


def _hk_speed():
    if HOTKEY_AKTIF:
        _cycle_speed()


def _hk_stop():
    if HOTKEY_AKTIF:
        _stop_bot()


if HAVE_HOTKEY:
    try:
        _kb.add_hotkey("f9", _hk_pause)
        _kb.add_hotkey("f10", _hk_speed)
        _kb.add_hotkey("f11", _hk_stop)
    except Exception:
        HAVE_HOTKEY = False

# Browser bawaan Chromium apa pun bisa. Urutan preferensi: Brave (yang
# dipakai selama pengembangan) -> Chrome -> Edge (bawaan Windows, jadi
# teman yang tidak install apa pun tetap bisa pakai).
# Override manual: set env TYPINGBOT_BROWSER=path\ke\browser.exe
BROWSER_CANDIDATES = [
    {"name": "Brave", "proc": "brave.exe", "paths": [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
    ]},
    {"name": "Chrome", "proc": "chrome.exe", "paths": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]},
    {"name": "Edge", "proc": "msedge.exe", "paths": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]},
]
BROWSER = None   # kandidat terpilih: {"name":..,"exe":..,"proc":..}
FORCE_BROWSER = ""   # path exe pilihan user (GUI); kosong = otomatis
LAST_BROWSER = ""    # path exe browser terakhir yang benar2 dipakai (preferensi Otomatis)
BRAVE_BINARY = BROWSER_CANDIDATES[0]["paths"][0]   # (kompatibilitas lama)
DEDICATED_PROFILE = os.path.expandvars(r"%LOCALAPPDATA%\TypingBot\profile")
# Mode profil: "bot" = profil khusus terpisah (default, aman) | "saya" =
# pakai profil asli milik user pilihan sendiri (login/bookmark ikut terpakai).
# Chrome/Edge 136+ menolak mode debug di folder data aslinya, tetapi masih
# mengizinkan kalau folder itu dibuka lewat junction (path lain -> data sama;
# teruji di Chrome/Edge 151). Brave menerima folder asli langsung.
PROFILE_MODE = "bot"
PROFILE_DIR = ""       # 'Default' / 'Profile 1' / ... (mode 'saya')
PROFILE_LABEL = ""     # nama tampilan profil utk pesan ramah (mis. 'Student')
# Port debug bisa berubah saat runtime: kalau 9222 kebetulan dipakai
# aplikasi lain (widget sistem bawaan laptop, WebView milik Adobe dll.),
# bot cukup memakai port berikutnya - aplikasi itu tidak perlu ditutup.
DEBUG_PORT = 9222


def _alamat_debug():
    return f"127.0.0.1:{DEBUG_PORT}"
OCR_MIN_INTERVAL = 3.0       # jeda minimal antar percobaan OCR

try:
    import winocr
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False

UI_WORDS = {
    "settings", "setting", "account", "profile", "dashboard", "school", "class",
    "teacher", "student", "lesson", "unit", "level", "levels", "score", "wpm",
    "accuracy", "akurasi", "kecepatan", "practice", "review", "test", "speed",
    "next", "continue", "lanjut", "mulai", "play", "start", "begin", "pause",
    "menu", "back", "restart", "exit", "sound", "music", "help", "premium",
    "upgrade", "langganan", "berlangganan", "skip", "lewati", "close", "tutup",
    "ok", "okay", "cancel", "batal", "save", "simpan", "brave", "edclub",
    "typingclub", "typing", "club", "live", "progress", "progres", "sign",
    "login", "logout", "search", "cari", "home", "beranda", "end", "fin",
}

# ---------------------------------------------------------------------------
# Koneksi: cek port, bersihkan dari Edge, buka Brave otomatis, sambungkan
# ---------------------------------------------------------------------------


def _is_edclub_url(url):
    """Cek hostname ASLI (bukan substring!): URL Stripe yang di dalam
    parameternya menyebut 'edclub.com' pernah menipu cek substring dan
    bikin bot nyangkut di halaman checkout mati."""
    try:
        h = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return h.endswith("edclub.com") or h.endswith("typingclub.com")


def _real_url(pg):
    """URL asli halaman via evaluate. page.url Playwright bisa stale
    (isi sudah m.stripe.network tapi masih melaporkan edclub);
    location.href tidak pernah bohong."""
    try:
        u = pg.evaluate("() => location.href")
        if u and isinstance(u, str):
            return u
    except Exception:
        pass
    try:
        return pg.url
    except Exception:
        return ""


def _frame_edclub(fr):
    """Frame ini milik edclub? Frame Stripe checkout (iframe premium)
    TIDAK BOLEH dijalankan klik apa pun - klik di dalamnya pernah
    membawa tab ke checkout Stripe."""
    try:
        if fr == PAGE.main_frame:
            return _is_edclub_url(_real_url(PAGE))
    except Exception:
        pass
    try:
        u = fr.url
    except Exception:
        return False
    if not u or u.startswith("about:"):
        return True
    h = (urlparse(u).hostname or "").lower()
    return h.endswith("edclub.com") or h.endswith("typingclub.com")


def _cek_debug_port():
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://{_alamat_debug()}/json/version", timeout=2) as r:
            return json.loads(r.read().decode()).get("Browser", "")
    except Exception:
        return ""


# Konfirmasi penutupan paksa aplikasi (dipasang GUI agar pakai dialog, bukan
# console). Default: tanya via console input.
_confirmer = None


def set_confirmer(fn):
    """Pasang callback konfirmasi: fn(nama, pid) -> bool (boleh ditutup?)."""
    global _confirmer
    _confirmer = fn


def _exe_info_pid(pid):
    """(path_exe, pid_induk) dari sebuah PID. PowerShell CIM dulu (wmic
    sudah dihapus di Windows 11 baru), fallback wmic. Return ('', 0) kalau
    tidak terbaca."""
    try:
        out = _run_hidden(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}')."
             "ExecutablePath"],
            capture_output=True, text=True, timeout=12).stdout.strip()
        if out and "\n" not in out:
            exe = out
        else:
            exe = ""
    except Exception:
        exe = ""
    induk = 0
    try:
        out2 = _run_hidden(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}')."
             "ParentProcessId"],
            capture_output=True, text=True, timeout=12).stdout.strip()
        if out2.isdigit():
            induk = int(out2)
    except Exception:
        induk = 0
    if not exe:
        try:
            out3 = _run_hidden(
                ["wmic", "process", "where", f"processid={pid}",
                 "get", "ExecutablePath", "/value"],
                capture_output=True, text=True, timeout=12).stdout
            for ln in out3.splitlines():
                if ln.lower().startswith("executablepath="):
                    exe = ln.split("=", 1)[1].strip()
                    break
        except Exception:
            pass
    return exe, induk


def _identitas_pemegang(pid, nama):
    """Identitas APLIKASI sebenarnya di balik proses pemegang port.
    Kasus nyata: port dipegang msedgewebview2.exe = WebView2 yang ditanam
    aplikasi lain (mis. Adobe), dulu salah terdeteksi sebagai 'Edge' lalu
    ditutup paksa tanpa bertanya. Return dict:
    nama (untuk dialog), exe (untuk ikon), proses (nama proses asli)."""
    exe, induk = _exe_info_pid(pid)
    base = os.path.basename(exe) if exe else nama
    tampil = os.path.splitext(base)[0]
    webview = "webview" in nama.lower() or "webview" in base.lower()
    if webview and induk:
        # cari nama aplikasi induknya (pemilik WebView) - ditampilkan apa
        # adanya tanpa embel2 teknis: user cukup tahu 'Acrobat' jalan.
        pexe, _pinduk = _exe_info_pid(induk)
        if pexe:
            pbase = os.path.basename(pexe)
            tampil = os.path.splitext(pbase)[0]
            exe = pexe
        else:
            tampil = tampil + "  (WebView)"
    return {"nama": tampil, "pid": pid, "exe": exe, "proses": nama}


def _tanya_tutup(nama, pid, exe=""):
    if _confirmer is not None:
        try:
            return bool(_confirmer(nama, pid, exe))
        except Exception:
            return False
    try:
        r = input(f"  Port 9222 dipakai oleh {nama} (PID {pid}). Tutup paksa? [y/N] ")
        return r.strip().lower().startswith("y")
    except Exception:
        return False


def _run_hidden(cmd, **kw):
    """subprocess.run tanpa jendela console. Wajib untuk semua panggilan
    netstat/tasklist/taskkill dari app berjendela (PyInstaller --windowed):
    tanpa flag ini Windows membuka jendela console hitam sesaat untuk tiap
    panggilan (user melihat 'aplikasi flash' beberapa kali saat connect)."""
    kw.setdefault("creationflags", 0x08000000)   # CREATE_NO_WINDOW
    return subprocess.run(cmd, **kw)


def _bebaskan_port(tanya_semua=True):
    """Port 9222 dipakai proses lain -> identifikasi PEMEGANG ASLINYA
    (bisa bukan browser sama sekali; WebView2 milik Adobe dsb. dinaiki
    ke aplikasi induknya), lalu SELALU minta izin user sebelum taskkill.
    (dulu proses 'edge' ditutup paksa diam-diam, pernah menutup
    WebView milik aplikasi lain.)
    Parameter tanya_semua dipertahankan untuk kompatibilitas pemanggil;
    sekarang semua pemegang selalu ditanyakan."""
    pemegang = _siapa_pegang_port()
    if not pemegang:
        return False
    for pid, nama in pemegang:
        info = _identitas_pemegang(pid, nama)
        print(f"  -> port 9222 dipakai {info['nama']} "
              f"({nama}, PID {pid})")
        if not _tanya_tutup(info["nama"], pid, info["exe"]):
            print(f"     tidak jadi ditutup - port tetap dipakai {info['nama']}.")
            continue
        print("     menutup paksa atas izin user...")
        try:
            _run_hidden(["taskkill", "/F", "/T", "/PID", str(pid)],
                        capture_output=True, timeout=8)
        except Exception:
            pass
    time.sleep(2)
    return True


def _siapa_pegang_port():
    pids = []
    try:
        out = _run_hidden(["netstat", "-ano", "-p", "TCP"],
                          capture_output=True, text=True, timeout=8).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[1].endswith(f":{DEBUG_PORT}") and parts[4].isdigit():
                pids.append(int(parts[4]))
    except Exception:
        pass
    hasil = []
    for pid in set(pids):
        try:
            t = _run_hidden(["tasklist", "/FI", f"PID eq {pid}"],
                            capture_output=True, text=True, timeout=5).stdout
            for ln in t.splitlines():
                if ".exe" in ln.lower() and str(pid) in ln:
                    hasil.append((pid, ln.split()[0]))
                    break
        except Exception:
            pass
    return hasil


def _adalah_browser_kita(nama_pemegang):
    """Apakah pemegang port salah satu browser yang dikelola bot
    (brave/chrome/msedge)? Bukan -> aplikasi asing (widget sistem
    bawaan laptop, WebView2 milik aplikasi lain, dll.) -> jangan
    pernah dipaksa ditutup."""
    return any(c["proc"] in nama_pemegang for c in BROWSER_CANDIDATES)


def _port_bind_kosong(port):
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
            return True
    except OSError:
        return False


def _sesuaikan_port():
    """Dipanggil di awal siapkan_browser. Port 9222 dipegang aplikasi
    ASING (bukan brave/chrome/msedge)? Bot pindah ke port kosong
    berikutnya dan MEMBIARKAN aplikasi itu tetap jalan - tanpa dialog
    'tutup aplikasi' yang menakutkan. Kasus nyata: Batterywidgethost
    bawaan laptop pegang 9222, bot malah minta ditutup padahal cukup
    pindah port."""
    global DEBUG_PORT
    pemegang = _siapa_pegang_port()
    if not pemegang:
        return DEBUG_PORT
    nama = " ".join(n.lower() for _, n in pemegang)
    if _adalah_browser_kita(nama):
        return DEBUG_PORT
    for kandidat in range(9223, 9323):
        if _port_bind_kosong(kandidat):
            try:
                info = _identitas_pemegang(pemegang[0][0], pemegang[0][1])
                nm = info["nama"]
            except Exception:
                nm = pemegang[0][1]
            print(f"[PORT] 9222 sedang dipakai {nm} - bot memakai jalur "
                  f"lain ({kandidat}); {nm} dibiarkan tetap jalan.")
            DEBUG_PORT = kandidat
            return DEBUG_PORT
    return DEBUG_PORT


def _ud_browser_dir(nama):
    """Folder data (User Data) ASLI milik browser terpasang. Return '' bila
    browser tidak dikenal/foldernya tidak ada."""
    base = os.path.expandvars("%LOCALAPPDATA%")
    kandidat = {
        "Brave": base + r"\BraveSoftware\Brave-Browser\User Data",
        "Chrome": base + r"\Google\Chrome\User Data",
        "Edge": base + r"\Microsoft\Edge\User Data",
    }
    ud = kandidat.get(nama, "")
    return ud if ud and os.path.isdir(ud) else ""


def _profil_daftar(nama):
    """Daftar profil manusia di browser terpasang (dibaca dari 'Local
    State', tanpa membuka browser). Return list {'dir','nama','email',
    'utama'}; 'Default' selalu di urutan pertama."""
    ud = _ud_browser_dir(nama)
    if not ud:
        return []
    try:
        with open(os.path.join(ud, "Local State"), encoding="utf-8") as f:
            info = json.load(f)
        cache = info.get("profile", {}).get("info_cache", {}) or {}
    except Exception:
        return []
    hasil = []
    for d, v in cache.items():
        if not isinstance(v, dict):
            continue
        nm = (v.get("name") or d).strip() or d
        hasil.append({"dir": d, "nama": nm,
                      "email": (v.get("user_name") or "").strip(),
                      "utama": d == "Default"})
    hasil.sort(key=lambda p: (not p["utama"], p["nama"].lower()))
    return hasil


def _ud_profil_arg(nama):
    """Argumen --user-data-dir untuk mode 'profil saya'. Brave: folder asli.
    Chrome/Edge: JUNCTION ke folder asli (path beda, data sama - satu2nya
    cara melewati larangan debug Chromium 136+ pada folder asli).
    Return '' bila tidak bisa (folder tidak ada / profil tidak ada)."""
    ud = _ud_browser_dir(nama)
    if not ud:
        return ""
    if PROFILE_DIR and not os.path.isdir(os.path.join(ud, PROFILE_DIR)):
        print(f"[PROFIL] profil '{PROFILE_DIR}' tidak ada di {nama} - "
              "memakai profil khusus bot.")
        return ""
    if nama == "Brave":
        return ud
    link = os.path.join(os.path.dirname(DEDICATED_PROFILE),
                        "ud_" + nama.lower())
    try:
        os.makedirs(os.path.dirname(link), exist_ok=True)
        if os.path.exists(link):
            os.rmdir(link)          # junction: hanya link yang terhapus
        r = _run_hidden(["cmd", "/c", "mklink", "/J", link, ud],
                        capture_output=True, text=True, timeout=15)
        if "Junction created" in (r.stdout or "") or \
                "created" in (r.stdout or "").lower():
            return link
        print(f"[PROFIL] gagal membuat pintasan folder ({(r.stderr or '')[:60]})"
              " - memakai profil khusus bot.")
    except Exception as ex:
        print(f"[PROFIL] gagal menyiapkan folder profil ({ex}) "
              "- memakai profil khusus bot.")
    return ""


def _proses_berdasar_nama(proc):
    """PID semua proses dengan nama image tertentu (brave.exe dsb.),
    hasil tasklist diurut seperti biasa (kolom ke-2 = PID)."""
    pids = []
    try:
        out = _run_hidden(["tasklist", "/FI", f"IMAGENAME eq {proc}"],
                          capture_output=True, text=True, timeout=8).stdout
        for ln in out.splitlines():
            bagian = ln.split()
            if (len(bagian) >= 2 and bagian[0].lower() == proc.lower()
                    and bagian[1].isdigit()):
                pids.append(int(bagian[1]))
    except Exception:
        pass
    return pids


def _tutup_browser_user(proc, nama):
    """Mode 'profil saya': browser harus BETUL2 mati dulu agar bisa
    diluncurkan ulang dengan profil user + mode debug (jika masih jalan,
    proses baru hanya membuka jendela di proses lama TANPA debug).
    Selalu minta izin user (dialog logo) sebelum menutup.
    Return False bila user menolak -> pemanggil jatuh ke profil khusus."""
    pids = _proses_berdasar_nama(proc)
    if not pids:
        return True
    exe, _induk = _exe_info_pid(pids[0])
    print(f"[PROFIL] {nama} sedang jalan - bot perlu menutupnya dulu "
          "untuk memakai profil kamu.")
    if not _tanya_tutup(nama, pids[0], exe):
        print("[PROFIL] tidak ditutup - bot memakai profil khusus saja.")
        return False
    for pid in pids:
        try:
            _run_hidden(["taskkill", "/F", "/T", "/PID", str(pid)],
                        capture_output=True, timeout=8)
        except Exception:
            pass
    for _ in range(10):
        time.sleep(0.5)
        if not _proses_berdasar_nama(proc):
            break
    return True


def _find_browser():
    """Cari browser Chromium terpasang. Return dict kandidat + 'exe',
    atau None. Prioritas: pilihan user (FORCE_BROWSER) -> env
    TYPINGBOT_BROWSER -> deteksi otomatis (Brave -> Chrome -> Edge)."""
    for pick in (FORCE_BROWSER, os.environ.get("TYPINGBOT_BROWSER", "")):
        pick = (pick or "").strip()
        if pick:
            base = os.path.basename(pick).lower()
            cocok = next((c for c in BROWSER_CANDIDATES
                          if base.startswith(c["proc"].replace(".exe", ""))), None)
            if cocok:
                # nama kanonik ("Brave") - pemanggil membandingkan dengan
                # nama itu untuk memutuskan profil default vs khusus
                return {"name": cocok["name"], "exe": pick,
                        "proc": cocok["proc"]}
            if os.path.isfile(pick):
                return {"name": os.path.basename(pick), "exe": pick,
                        "proc": "brave.exe"}
            print(f"Browser pilihan ({pick}) tidak ditemukan, pakai deteksi otomatis.")
    # Preferensi Otomatis: browser yang terakhir dipakai (live tersimpan
    # GUI) - jadi Otomatis = 'browser edclub kemarin', bukan selalu Brave.
    last = (LAST_BROWSER or "").strip()
    if last:
        base = os.path.basename(last).lower()
        cocok = next((c for c in BROWSER_CANDIDATES
                      if base.startswith(c["proc"].replace(".exe", ""))), None)
        if cocok:
            return {"name": cocok["name"], "exe": last, "proc": cocok["proc"]}
    for c in BROWSER_CANDIDATES:
        for p in c["paths"]:
            if p and os.path.isfile(p):
                return {"name": c["name"], "exe": p, "proc": c["proc"]}
    return None


def _browser_sudah_jalan():
    proc = (BROWSER or {}).get("proc", "brave.exe")
    try:
        out = _run_hidden(["tasklist", "/FI", f"IMAGENAME eq {proc}"],
            capture_output=True, text=True, timeout=5).stdout
        return proc.lower() in out.lower()
    except Exception:
        return False


def _port_dipakai_browser_lain():
    """Port 9222 hidup tetapi dipegang browser BERBEDA dari pilihan user?
    (mis. jendela debug Brave lama masih nyala padahal user pilih Chrome).
    Return list pemegang [(pid, nama)]; [] bila cocok / tidak ada."""
    pilihan = _find_browser() or {}
    proc_pilihan = pilihan.get("proc", "")
    pemegang = _siapa_pegang_port()
    if not (proc_pilihan and pemegang):
        return []
    nama_pemegang = " ".join(n.lower() for _, n in pemegang)
    if proc_pilihan in nama_pemegang:
        return []
    return pemegang


def _restart_browser_debug():
    """Pemulihan terakhir: browser debug hidup di HTTP tetapi websocket
    DevTools-nya menggantung (Brave lama yang jarang dipakai ditidurkan
    Windows; 3x retry connect tetap timeout).
    Restart saja: tutup pemegang 9222, jalankan ulang dengan mode debug.
    Tab browser dipulihkan otomatis oleh sesi restore."""
    pemegang = _siapa_pegang_port()
    if not pemegang:
        return False
    print(f"[PEMULIHAN] Browser debug tidak merespons - memulai ulang "
          f"({', '.join(n for _, n in pemegang)})...")
    for pid, _nama in pemegang:
        try:
            _run_hidden(["taskkill", "/F", "/T", "/PID", str(pid)],
                        capture_output=True, timeout=8)
        except Exception:
            pass
    for _ in range(16):
        time.sleep(0.5)
        if not _cek_debug_port():
            break
    pilihan = _find_browser() or (BROWSER or {}) or {}
    exe = pilihan.get("exe") or ""
    if not exe or not os.path.isfile(exe):
        print("[PEMULIHAN] Browser tidak ditemukan - tidak bisa restart.")
        return False
    args = [exe, f"--remote-debugging-port={DEBUG_PORT}", "--restore-last-session"]
    if PROFILE_MODE == "saya" and PROFILE_DIR:
        ud_saya = _ud_profil_arg(pilihan.get("name", ""))
        if ud_saya:
            args += [f"--user-data-dir={ud_saya}",
                     f"--profile-directory={PROFILE_DIR}"]
        else:
            args.append(f"--user-data-dir={DEDICATED_PROFILE}")
    elif pilihan.get("name") != "Brave":
        args.append(f"--user-data-dir={DEDICATED_PROFILE}")
    # jangan mencuri fokus: jendela browser muncul diminimized tanpa
    # mengaktifkan dirinya (user bisa sedang mengetik di aplikasi lain).
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 7   # SW_SHOWMINNOACTIVE
    subprocess.Popen(args, close_fds=True, startupinfo=si)
    for _ in range(40):
        time.sleep(0.5)
        if STOP:
            sys.exit(0)
        if _cek_debug_port().startswith("Chrome"):
            print("[PEMULIHAN] Browser debug hidup kembali.")
            return True
    return False


def _cari_tab_setup(br, pg_utama):
    """Tab SET-UP first-run (Edge/Chrome/Brave baru pertama kali dibuka di
    profil khusus bot): welcome / pilih default browser / izin cookie /
    sign-in sync. Return tab set-up pertama yang terlihat, None kalau
    tidak ada. (dulu bot langsung menimpa tab set-up; sekarang tunggu
    sampai user menutupnya.)"""
    for ctx2 in br.contexts:
        try:
            for pg2 in ctx2.pages:
                if pg2 == pg_utama:
                    continue
                u = (pg2.url or "").lower()
                if any(k in u for k in
                       ("first-run", "first_run", "firstrun", "welcome",
                        "onboarding", "getting-started", "chrome-signin")):
                    return pg2
        except Exception:
            continue
    return None


def _tutup_tab_kosong(br, pg_utama):
    """Tutup tab kosong sisa start-up browser (newtab/welcome/blank).
    Hanya kalau masih ada tab lain di context - jangan sampai jendela
    ikut tertutup."""
    for ctx in br.contexts:
        try:
            halaman = list(ctx.pages)
            if len(halaman) < 2:
                continue
            for pg in halaman:
                if pg == pg_utama:
                    continue
                try:
                    u = (pg.url or "").lower()
                except Exception:
                    continue
                if (u.startswith(("chrome://new", "edge://new", "brave://new",
                                  "chrome://newtab", "edge://newtab"))
                        or u in ("about:blank", "chrome://welcome",
                                 "edge://welcome", "brave://welcome")):
                    try:
                        pg.close()
                        print("Tab kosong sisa start-up browser ditutup.")
                    except Exception:
                        pass
        except Exception:
            pass


def _browser_dari_pemegang_port():
    """Browser TERPASANG yang saat ini memegang port 9222 (untuk mode
    Otomatis: tempeli saja yang sudah jalan). None kalau port kosong atau
    dipegang proses non-browser (WebView/Adobe dsb. - itu tetap lewat
    dialog izin)."""
    if not _cek_debug_port():
        return None
    holder = _siapa_pegang_port()
    nama = " ".join(n.lower() for _, n in holder)
    for c in BROWSER_CANDIDATES:
        if c["proc"] in nama:
            for p in c["paths"]:
                if p and os.path.isfile(p):
                    return {"name": c["name"], "exe": p, "proc": c["proc"]}
    return None


def siapkan_browser():
    """Pastikan ada browser Chromium (Brave/Chrome/Edge) debug di port
    9222 (atau port berikutnya bila 9222 dipakai aplikasi asing - lihat
    _sesuaikan_port). Browser LAIN milik bot yang memegang port tetap
    ditangani dengan izin user, bukan asal ditutup."""
    global BROWSER
    if STOP:
        sys.exit(0)
    _sesuaikan_port()
    browser_on_port = _cek_debug_port()

    # otomatis pintar: port sudah dipegang browser terpasang -> pakai browser
    # itu langsung (dulu Otomatis selalu Brave -> 'port dipegang browser lain'
    # -> minta izin menutup Chrome/Edge padahal tinggal ditempeli).
    otomatis = not ((FORCE_BROWSER or os.environ.get("TYPINGBOT_BROWSER", "")).strip())
    reuse = _browser_dari_pemegang_port() if otomatis else None
    if reuse is not None:
        BROWSER = reuse
        print(f"[OTOMATIS] {reuse['name']} sudah jalan dengan port debug - "
              "dipakai langsung tanpa menutup apa pun.")

    if "Edg" in browser_on_port and reuse is None:
        # Bisa Edge betulan, bisa juga WebView2 milik aplikasi lain (mis.
        # Adobe) yang membalas /json/version dengan string "Edg/...".
        print("Port 9222 dipegang proses berbasis Edge/WebView, "
              "mencari proses pemegangnya...")
        _bebaskan_port()
        browser_on_port = _cek_debug_port()
        if "Edg" in browser_on_port:
            print("MASIH terkunci. Cek pemegang port: netstat -ano | findstr :9222")
            print("Tutup manual aplikasinya, lalu jalankan ulang program.")
            sys.exit(1)
        print("Port 9222 berhasil dibebaskan.")

    if browser_on_port and reuse is None:
        # Port hidup, tapi dipegang browser lain dari pilihan user? (mis.
        # user pilih Chrome sementara jendela debug Brave lama masih nyala
        # atau menggantung) -> tutup pemegangnya (dengan izin) supaya
        # browser pilihan bisa memakai port.
        lain = _port_dipakai_browser_lain()
        if lain:
            print(f"Port 9222 dipegang browser lain "
                  f"({', '.join(n for _, n in lain)}), padahal pilihan: "
                  f"{(_find_browser() or {}).get('name', '?')}. "
                  "Menutup pemegang port...")
            _bebaskan_port(tanya_semua=True)
            browser_on_port = _cek_debug_port()
            if browser_on_port:
                print("Pemegang port tidak ditutup - bot tidak bisa lanjut. "
                      "Tutup jendela browser lama, lalu klik Start lagi.")
                sys.exit(1)

    if not browser_on_port:
        if _siapa_pegang_port():
            print("Port 9222 dipakai proses lain (bukan browser debug)...")
            _bebaskan_port()
            browser_on_port = _cek_debug_port()
        if not browser_on_port:
            BROWSER = _find_browser()
            if BROWSER is None:
                print("Tidak ada browser Chromium (Brave/Chrome/Edge). "
                      "Install salah satunya dulu.")
                sys.exit(1)
            nm = BROWSER["name"]
            # Mode 'profil saya': luncurkan dengan profil asli user. Browser
            # yang sedang jalan harus dimatikan dulu (dengan izin) - proses
            # baru hanya membuka jendela di proses lama tanpa mode debug.
            # Chrome/Edge dibuka lewat junction (lihat _ud_profil_arg).
            if PROFILE_MODE == "saya" and PROFILE_DIR:
                if _browser_sudah_jalan() and not _tutup_browser_user(
                        BROWSER["proc"], nm):
                    ud_saya = ""
                else:
                    ud_saya = _ud_profil_arg(nm)
                if ud_saya:
                    print(f"[PROFIL] membuka {nm} dengan profilmu "
                          f"({PROFILE_LABEL or PROFILE_DIR})...")
                    subprocess.Popen(
                        [BROWSER["exe"], f"--remote-debugging-port={DEBUG_PORT}",
                         f"--user-data-dir={ud_saya}",
                         f"--profile-directory={PROFILE_DIR}",
                         "--no-first-run"],
                        close_fds=True)
                    for _ in range(30):
                        time.sleep(0.5)
                        if STOP:
                            sys.exit(0)
                        if _cek_debug_port().startswith("Chrome"):
                            break
                    if _cek_debug_port().startswith("Chrome"):
                        browser_on_port = _cek_debug_port()
                    else:
                        print("[PROFIL] profil kamu gagal dibuka - bot "
                              "memakai profil khusus bot.")
            # Chrome/Edge modern menolak flag debug di profil default
            # (Chromium 136+). Jangan coba-coba (buka jendela tanpa debug
            # lalu tunggu 15 dtk sia-sia): langsung profil khusus bot.
            # Hal yang sama kalau browser sama sudah jalan tanpa debug -
            # profil khusus bisa berjalan berdampingan dengan jendela itu.
            if not browser_on_port:
                langsung_profil = (nm != "Brave") or _browser_sudah_jalan()
                if not langsung_profil:
                    print(f"Port 9222 kosong: membuka {nm} otomatis "
                          "dengan mode debug...")
                    subprocess.Popen([BROWSER["exe"], f"--remote-debugging-port={DEBUG_PORT}"],
                                     close_fds=True)
                    for _ in range(30):
                        time.sleep(0.5)
                        if STOP:
                            sys.exit(0)
                        if _cek_debug_port().startswith("Chrome"):
                            break
                    if not _cek_debug_port().startswith("Chrome"):
                        langsung_profil = True
                if langsung_profil:
                    # Profil khusus bot: login edclub sekali, tersimpan selamanya.
                    alasan = ("sudah jalan tanpa debug" if _browser_sudah_jalan()
                              else "profil default menolak mode debug")
                    print(f"Membuka {nm} dengan profil khusus bot ({alasan})...")
                    subprocess.Popen([BROWSER["exe"],
                                      f"--remote-debugging-port={DEBUG_PORT}",
                                      f"--user-data-dir={DEDICATED_PROFILE}"],
                                     close_fds=True)
                    for _ in range(30):
                        time.sleep(0.5)
                        if STOP:
                            sys.exit(0)
                        if _cek_debug_port().startswith("Chrome"):
                            break
    if BROWSER is None:
        BROWSER = _find_browser() or {"name": "browser", "exe": "", "proc": ""}

    print(f"Menyambungkan Playwright ke browser ({BROWSER['name']})...")
    # Retry wajib : sambungan websocket sesi sebelumnya yang
    # terputus paksa (taskkill/app ditutup) menyisakan koneksi setengah
    # terbuka di sisi browser - sambungan pertama setelah itu timeout,
    # tetapi justru menendang koneksi mati itu lepas dan percobaan ke-2
    # langsung berhasil. Tanpa retry = "gagal connect" padahal browser baik.
    def _tangga_connect():
        """Return SELALU 3-tuple (pw, browser, pesan_gagal).
        Pernah bug: slot ke-2 diisi string pesan -> 'browser is None'
        tidak pernah benar -> pemulihan restart tidak pernah jalan dan
        crash 'str' object has no attribute 'contexts'."""
        br = None
        p = None
        pesan = ""
        for percobaan in range(3):
            if STOP:
                sys.exit(0)
            try:
                p = sync_playwright().start()
                br = p.chromium.connect_over_cdp(
                    f"http://{_alamat_debug()}",
                    timeout=20000 if percobaan == 0 else 12000)
                return p, br, ""
            except Exception as e:
                pesan = str(e)[:120]
                if p is not None:
                    try:
                        p.stop()
                    except Exception:
                        pass
                p = None
                br = None
                if percobaan == 0:
                    print("Sambungan pertama gagal (sisa koneksi lama di "
                          "browser) - mencoba lagi...")
                time.sleep(1.5)
        return None, None, pesan

    pw, browser, pesan = _tangga_connect()
    if browser is None and _cek_debug_port():
        # Port hidup di HTTP tetapi websocket menolak = DevTools browser
        # menggantung (idle lama). Restart browser debug lalu coba lagi.
        # kill + relaunch debug browser -> connect langsung ok.
        if _restart_browser_debug():
            pw, browser, pesan = _tangga_connect()
    if browser is None:
        print(f"Gagal menyambung ke browser: {pesan or 'tidak diketahui'}")
        print("Tutup semua jendela browser, lalu klik Start lagi.")
        sys.exit(1)
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()

    page = None
    # Tutup sisa tab Stripe/checkout dari sesi sebelumnya (dibuat saat bot
    # pernah salah klik CTA premium). Tab ini tidak berguna, dan pernah
    # menipu deteksi tab edclub.
    for pg in list(ctx.pages):
        try:
            h = (urlparse(_real_url(pg)).hostname or "").lower()
        except Exception:
            continue
        if "stripe" in h:
            try:
                pg.close()
                print(f"Tab sisa Stripe ditutup ({h})")
            except Exception:
                pass
    # Tab edclub sisa sesi lalu sering mati (layar gelap / ter-bawa ke
    # Stripe checkout) dan malah menang pemilihan tab - bot lalu nyangkut
    # 20-25 detik sebelum recovery menyalakannya. Solusi: periksa
    # kesehatan tiap tab, ambil satu terbaik, tutup sisanya otomatis.
    edclub_tabs = []
    for pg in ctx.pages:
        try:
            if _is_edclub_url(_real_url(pg)):
                edclub_tabs.append(pg)
        except Exception:
            continue
    healthy = []
    for pg in edclub_tabs:
        try:
            u1 = _real_url(pg)
            time.sleep(0.25)
            u2 = _real_url(pg)
        except Exception:
            continue
        # URL masih berubah / pindah host = tab sedang restore atau
        # replay redirect Stripe (hijack sisa sesi lama) - jangan dipakai.
        if u1 != u2 or not _is_edclub_url(u2):
            continue
        try:
            pg.evaluate("() => 1")   # renderer kritis -> raise di sini
        except Exception:
            continue
        healthy.append(pg)
    # Tutup tab edclub yang tidak sehat supaya tidak menumpuk.
    for pg in edclub_tabs:
        if pg not in healthy:
            try:
                pg.close()
                print("Tab edclub mati/sisa ditutup otomatis")
            except Exception:
                pass
    # Pilih yang paling mungkin punya pekerjaan: .play dengan token/canvas
    # aktif > .play apa pun. Skor sama -> tab paling kanan (terbaru) menang;
    # (dulu: skor sama dimenangkan tab pertama = tab lama yang mati).
    def _score(pg):
        try:
            url = _real_url(pg)
        except Exception:
            return -1
        s = 0
        if ".play" in url:
            s += 10
        try:
            info = pg.evaluate("() => {" + PLAYABLE_CHECK_JS + "}")
            if info:
                if info.get("clr"):
                    s += 5
                elif info.get("boxed"):
                    s += 3
                elif info.get("canvas"):
                    s += 1
                if info.get("done"):
                    s -= 8   # layar skor/selesai = tidak ada kerjaan
        except Exception:
            pass
        return s
    if healthy:
        page = max(healthy, key=lambda pg: (_score(pg), healthy.index(pg)))
        others = [pg for pg in healthy if pg is not page]
        for pg in others:
            try:
                pg.close()
            except Exception:
                pass
        if others:
            print(f"{len(others)} tab edclub lain ditutup otomatis "
                  "(dipilih 1 tab terbaik)")
    if page is None:
        # Kalau tidak ada tab edclub: buka tab baru. pernah gagal live:
        # menutup tab Stripe sisa = satu-satunya tab di jendelanya ->
        # Brave membongkar jendela itu -> Target.createTarget gagal sesaat.
        # Solusi: retry + fallback ke tab yang ada / context baru.
        for attempt in range(4):
            try:
                page = ctx.new_page()
                break
            except Exception as e:
                print(f"Buka tab baru gagal ({attempt + 1}/4): {str(e)[:60]}")
                time.sleep(1.5)
        if page is None:
            for c2 in browser.contexts:
                try:
                    if c2.pages:
                        page = c2.pages[0]
                        break
                except Exception:
                    continue
        if page is None:
            try:
                page = browser.new_context().new_page()
            except Exception:
                pass
        if page is None:
            print("Gagal membuka tab. Buka edclub.com manual di Brave, "
                  "lalu jalankan ulang program.")
            sys.exit(1)
        print("Tab edclub belum ada. Membuka edclub.com otomatis...")
        try:
            page.goto("https://www.edclub.com/sportal/program-3.game",
                      timeout=25000)
        except Exception:
            print("Gagal membuka edclub - buka manual di Brave, bot menunggu.")
    # Tutup tab sisa START-UP browser (selalu, dua kali: sekarang + setelah
    # set-up): browser baru dibuka dengan 1 tab kosong (newtab), lalu bot
    # membuat/menemukan tab edclub sendiri -> tab kosong menganggung.
    # Live: Edge membuat tab newtab-nya belakangan (setelah welcome-nya
    # ditutup), jaitu pembersihan sekali di sini kurang - jalankan lagi
    # setelah gerbang set-up. Hanya tab newtab/welcome/blank, hanya kalau
    # masih ada tab lain (jangan sampai jendela ikut tertutup).
    _tutup_tab_kosong(browser, page)
    # Tab set-UP first-run (Edge/Chrome/Brave baru pertama kali dibuka di
    # profil khusus bot): welcome / pilih default browser / izin cookie /
    # sign-in sync. Dulu bot langsung jalan menimpa set-up (
    # sebaiknya tunggu). Sekarang: instruksi + tunggu sampai semua tab
    # set-up ditutup user, bot lanjut otomatis setelahnya.
    global MENUNGGU_SETUP
    if _cari_tab_setup(browser, page) is not None:
        MENUNGGU_SETUP = True
        print("[SETUP] Browser baru sedang set-up (welcome / pilih default "
              "browser / cookie). Selesaikan dulu set-upnya di jendela "
              "browser, lalu TUTUP tab set-upnya - bot mulai bekerja "
              "otomatis begitu tab set-up ditutup.")
        while not STOP:
            time.sleep(1.0)
            if _cari_tab_setup(browser, page) is None:
                break
        MENUNGGU_SETUP = False
        if not STOP:
            print("[SETUP] Set-up browser selesai - bot mulai bekerja.")
            _tutup_tab_kosong(browser, page)
    return pw, browser, page


PLAYABLE_CHECK_JS = r"""
// Apakah halaman ini punya pekerjaan untuk bot?
const clr = document.querySelectorAll('span.token_unit._clr, ._clr > span.token_unit').length;
const boxed = document.querySelectorAll('.boxed-line .boxed-char').length;
const canvas = document.querySelectorAll('canvas').length;
const done = !!document.querySelector('.lesson-complete, [class*="score" i], [class*="result" i]');
return {clr: clr, boxed: boxed, canvas: canvas, done: done};
"""


pw = None
browser = None
PAGE = None
STATUS_URL = ""   # dibaca GUI (string biasa, aman lintas thread)
STATUS_LABEL = ""  # label level asli dari halaman (mis. 'L87')
_label_retry = 0.0
_rentang_nav = 0.0
_rentang_jump_done = False
_rentang_max_seen = 0    # level tertinggi yang terlihat sesi ini (anti lompat-balik)
_unlock_set = None    # level terbuka di akun (diisi saat perlu)
_last_loop_err = 0.0


def connect():
    """Sambungkan ke Brave. HARUS dipanggil dari thread yang sama dengan
    main_loop() - objek Playwright tidak boleh dipakai lintas thread."""
    global pw, browser, PAGE
    if PAGE is not None:
        return True
    try:
        pw, browser, PAGE = siapkan_browser()
    except SystemExit:
        raise
    except Exception as e:
        print(f"Gagal menyambung ke browser: {str(e)[:120]}")
        print("Tutup semua jendela browser, lalu klik Start lagi.")
        sys.exit(1)
    print(f"Terhubung! Tab aktif: {PAGE.url}")
    _pasang_login_sentinel()
    if not OCR_AVAILABLE:
        print("Catatan: 'winocr' tidak ada -> fallback OCR nonaktif (pip install winocr).")
    return True


def disconnect():
    """Putuskan koneksi Playwright dan reset cache global. Harus dipanggil
    dari thread yang menjalankan connect(). Tanpa ini, restart dari GUI
    memakai objek Playwright milik thread lama yang sudah mati ->
    error "cannot switch to a different thread"."""
    global pw, browser, PAGE
    global PERLU_LOGIN, LOGIN_DICEK, RENTANG_SIAP
    # Reset status login dulu (sebelum guard): disconnect yang dipanggil
    # tanpa koneksi pun harus membersihkan state sesi sebelumnya.
    PERLU_LOGIN = False
    LOGIN_DICEK = False
    RENTANG_SIAP = False
    _login_sentinel["ok"] = True
    _login_sentinel["alasan"] = ""
    _login_sentinel["pernah_in"] = False
    _login_sentinel["unknown_mulai"] = 0.0
    _login_ck["terakhir"] = 0.0
    if pw is None and PAGE is None:
        return
    try:
        pw.stop()
    except Exception:
        pass
    pw, browser, PAGE = None, None, None


# ---------------------------------------------------------------------------
# Util frame & JS (Playwright: semua frame otomatis tersedia)
# ---------------------------------------------------------------------------

def all_frames():
    """Semua frame halaman (main + semua iframe, termasuk cross-origin)."""
    try:
        return list(PAGE.frames)
    except Exception:
        try:
            return [PAGE.main_frame]
        except Exception:
            return []


def _edclub_frames():
    """Semua frame milik edclub (frame Stripe/checkout dikecualikan)."""
    return [fr for fr in all_frames() if _frame_edclub(fr)]


def run_js(js, frame=None):
    """evaluate JS di frame (default main). Aman dari error."""
    fr = frame if frame is not None else PAGE.main_frame
    try:
        return fr.evaluate("() => {" + js + "}")
    except Exception:
        return None


def frame_label(frame):
    if frame == PAGE.main_frame:
        return "atas"
    return "frame:" + (frame.url[-60:] if frame.url else frame.name)


# ---------------------------------------------------------------------------
# Deteksi state per frame
# ---------------------------------------------------------------------------

DETECT_JS = r"""
const out = {std: null, mini: null, canvases: document.querySelectorAll('canvas').length, core: false};

// Penting: teks lesson diambil Hanya dari token _clr (belum diketik).
// Token salah (_err berisi karakter salah yang di-inject edclub ke teks)
// tidak boleh ikut - kalau ikut, ekstraksi terkorupsi dan semua salah.
// Efek samping positif: ini otomatis menangani lesson yang sebagian sudah
// diketik dan baris baru yang muncul progresif (cukup re-ekstrak).
const stdEls = document.querySelectorAll('span.token_unit._clr, ._clr > span.token_unit');
if (stdEls.length > 0) {
    const result = [];
    for (const e of stdEls) {
        const txt = e.innerText || e.textContent;
        if (!txt) continue;
        if (txt.includes('↵') || txt.includes('\n')) result.push('\n');
        else if (txt.includes('↹') || txt.includes('\t')) result.push('\t');
        else {
            // Run whitespace (>=2 nbsp/spasi berurutan) = Satu unit
            // indentasi: tekan Tab Sekali di lesson Tab:
            // 1 Tab = 1 token run, err=0; spasi per-char = salah).
            // Run 1 = spasi biasa. (dulu: ambil karakter pertama saja ->
            // nbsp mentah terkirim, engine diam = bot nyangkut di level 87.)
            let run = 0;
            for (const ch of txt) {
                if (ch === '\u00A0' || ch === ' ') { run++; continue; }
                if (run === 1) result.push(' ');
                else if (run >= 2) result.push('\t');
                run = 0;
                result.push(ch);
            }
            if (run === 1) result.push(' ');
            else if (run >= 2) result.push('\t');
        }
    }
    const t = result.join('');
    if (t.replace(/\s/g, '').length > 0) out.std = t;
}

if (!out.std) {
    // Tutorial boxed: hanya ekstrak Run Pending (trailing run dengan tanda
    // class sama dengan karakter terakhir) - sama seperti _clr di lesson
    // standar. Re-entry mid-lesson melanjutkan dari sisa, bukan retype all.
    const tspans = Array.from(document.querySelectorAll('.boxed-line > span'))
        .filter(sp => sp.querySelector('.boxed-char'));
    if (tspans.length && tspans.length < 200) {
        const tsig = sp => {
            const ch = sp.querySelector('.boxed-char');
            let line = '';
            try { const l = sp.closest('.boxed-line'); line = l ? l.className : ''; } catch (e) {}
            return (line + '|' + sp.className + '|' + ch.className).trim();
        };
        const tsigs = tspans.map(tsig);
        const tlast = tsigs[tsigs.length - 1];
        let ti = tsigs.length - 1;
        while (ti >= 0 && tsigs[ti] === tlast) ti--;
        // sertakan run Pendek (<=2) sebelum trailing run = karakter Aktif
        // (di-highlight sendiri oleh situs asli; tanpa ini karakter aktif
        // terjatuh dari ekstraksi -> urutan ketikan bergeser satu = desync)
        let tstart = ti + 1;
        if (ti >= 0) {
            let tj = ti;
            while (tj >= 0 && tsigs[tj] === tsigs[ti]) tj--;
            if (ti - tj <= 2) tstart = tj + 1;
        }
        const chars = [];
        for (let k = tstart; k < tspans.length; k++) {
            let c = (tspans[k].querySelector('.boxed-char').textContent || '').slice(0, 1);
            if (c === '\u00a0' || c === ' ') c = ' ';
            else c = c.trim();
            if (c) chars.push(c);
        }
        if (chars.length) out.tut = {text: chars.join('')};
    }

    const letterSels = ['.letter:not(.correct):not(.typed)', 'span[class*="letter"]:not(.correct)'];
    for (const sel of letterSels) {
        const els = document.querySelectorAll(sel);
        const chars = [];
        for (const e of els) {
            if (!(e.offsetWidth > 0 || e.offsetHeight > 0)) continue;
            const t = (e.textContent || '').trim();
            if (t.length === 1) chars.push(t);
            if (chars.length >= 20) break;
        }
        if (chars.length >= 2) { out.mini = {text: chars.join(''), source: sel}; break; }
    }
    if (!out.mini) {
        const wordSels = ['.word:not(.completed):not(.done)', '.arcade-word', '.game-word',
                          'span[class*="word"]', 'div[class*="word"]'];
        outer_words:
        for (const sel of wordSels) {
            for (const e of document.querySelectorAll(sel)) {
                if (!(e.offsetWidth > 0 || e.offsetHeight > 0)) continue;
                const t = (e.innerText || e.textContent || '').trim();
                if (t && t.length < 20 && /^[a-zA-Z\s]+$/.test(t) && t.replace(/\s/g, '').length >= 2) {
                    out.mini = {text: t, source: sel};
                    break outer_words;
                }
            }
        }
    }
}

if (!out.std && !out.mini && !out.tut) {
    const targets = [];
    try { if (window.core) { out.core = true; targets.push(window.core); } } catch (e) {}
    outer_core:
    for (const t of targets) {
        try {
            for (const k of Object.keys(t)) {
                let v; try { v = t[k]; } catch (e) { continue; }
                if (typeof v === 'string' && v.length > 1 && v.length < 100 && /^[a-zA-Z\s]+$/.test(v)) {
                    out.mini = {text: v, source: 'core.' + k};
                    break outer_core;
                }
            }
        } catch (e) {}
    }
}
return out;
"""

SCORE_JS = r"""
const t = (document.body ? document.body.innerText : '').toLowerCase();
if (t.includes('new key introduction')) return false;
if (/^type the[\s\S]{1,20}?\s+key/m.test(t.replace(/\u00a0/g, ' '))) return false;
if (t.includes('wpm') && (t.includes('accuracy') || t.includes('akurasi'))) return true;
const cont = document.querySelector('.navbar-continue');
return !!(cont && (cont.offsetWidth || cont.offsetHeight));
"""


def detect_all_frames():
    """Return (state, frame, data)."""
    canvases = 0
    canvas_frames = []
    for fr in all_frames():
        info = run_js(DETECT_JS, fr)
        if not info:
            continue
        if info.get("canvases"):
            canvases += int(info["canvases"])
            canvas_frames.append(fr)
        if info.get("std"):
            return "std", fr, info["std"]
        if info.get("tut"):
            return "tut", fr, info["tut"]
        if info.get("mini"):
            return "mini", fr, info["mini"]
        if fr == PAGE.main_frame and run_js(SCORE_JS, fr):
            return "score", fr, None
    return "unknown", None, {"canvases": canvases, "canvas_frames": canvas_frames}


# ---------------------------------------------------------------------------
# Penutup pop-up / iklan premium / achievement
# ---------------------------------------------------------------------------

OVERLAY_JS = r"""
const taken = [];
// Modal premium terlihat? Jangan klik tombol lanjut apa pun - di level
// premium klik "continue" edclub Membawa Tab ke Stripe Checkout
// .
const premModal = (() => {
    try {
        const dlgs = document.querySelectorAll('[class*="modal" i], [class*="popup" i], [class*="dialog" i], [role="dialog"]');
        for (const d of dlgs) {
            if (!(d.offsetWidth > 100 && d.offsetHeight > 80)) continue;
            const t = (d.innerText || '').toLowerCase();
            if (/premium|upgrade|subscription|subscribe|langganan|berlangganan|go pro|unlock all/.test(t)) return true;
        }
    } catch (e) {}
    return false;
})();
const visible = el => { try { return !!(el.offsetWidth || el.offsetHeight); } catch (e) { return false; } };
function doClick(el, why) { try { el.click(); taken.push(why); return true; } catch (e) { return false; } }

const CLOSE_TEXTS = ['x','×','✕','✖','close','tutup','no thanks','not now','maybe later','later',
                     'nanti saja','nanti','lewati','skip'];
const NEXT_TEXTS  = ['next','continue','lanjut','mulai','main','play','start','begin','selesai',
                     'claim','klaim','skip video','got it','ok','okay'];

const closeSels = ['.modal-close', '.close-btn', '.pop-close', 'button[class*="close" i]',
                   '[class*="modal"] [class*="close" i]', '[aria-label*="close" i]',
                   '[aria-label*="dismiss" i]', '[data-dismiss]', '[class*="dismiss" i]',
                   '[class*="achievement"] [class*="close" i]', 'svg[class*="close" i]',
                   '[class*="close" i][class*="icon" i]', '[class*="popup"] [class*="x" i]'];
outer1:
for (const sel of closeSels) {
    for (const el of document.querySelectorAll(sel)) {
        if (visible(el) && doClick(el, 'tutup:' + sel)) break outer1;
    }
}

if (taken.length === 0) {
    let introScreen = false;
    try {
        const bt = document.body ? document.body.innerText.toLowerCase() : '';
        introScreen = bt.includes('new key introduction') || /^type the[\s\S]{1,20}?\s+key/m.test(bt.replace(/\u00a0/g, ' '));
    } catch (e) {}
    if (!introScreen && !premModal) {
    const nextSels = ['.next-button', '.btn-continue', '.continue-button',
                      '[data-testid="lesson-next-btn"]', '.a-btn.next', '.navbar-continue'];
    outer2:
    for (const sel of nextSels) {
        for (const el of document.querySelectorAll(sel)) {
            if (visible(el) && doClick(el, 'lanjut:' + sel)) break outer2;
        }
    }
    }
}

if (!premModal) {
    const want = {};
    for (const t of NEXT_TEXTS) want[t] = true;
    outer3:
    for (const el of document.querySelectorAll('button, a, [role="button"], [class*="btn" i], [class*="button" i]')) {
        let txt = '';
        try { txt = (el.innerText || '').trim().toLowerCase(); } catch (e) {}
        if (!txt || txt.length > 14 || !want[txt] || !visible(el)) continue;
        try { if (el.closest('.typable, .token_unit, .boxed-typing-lines, .boxed-line, .TPGAME')) continue; } catch (e) {}
        // Jangan klik tombol "continue/next" di dalam kontainer premium/
        // upsell/checkout: itu CTA berbayar (pernah membawa bot ke Stripe
        // Checkout). Tombol lanjut yang sah ada di navbar, bukan di modal.
        try { if (el.closest('[class*="premium" i],[class*="upsell" i],[class*="paywall" i],[class*="checkout" i],[class*="stripe" i]')) continue; } catch (e) {}
        if (doClick(el, 'teks:"' + txt + '"')) break outer3;
    }
}

{
    const want = {};
    for (const t of CLOSE_TEXTS) want[t] = true;
    const MODAL_SEL = '[class*="modal" i],[class*="popup" i],[class*="dialog" i],[class*="overlay" i],[role="dialog"],[class*="premium" i],[class*="upsell" i],[class*="paywall" i],[class*="achiev" i],[class*="promo" i],[class*="banner" i]';
    outer3b:
    for (const el of document.querySelectorAll('button, a, span, div, [role="button"]')) {
        let txt = '';
        try { txt = (el.innerText || '').trim().toLowerCase(); } catch (e) {}
        if (!txt || txt.length > 18 || !want[txt] || !visible(el)) continue;
        try { if (el.closest('.typable, .token_unit, .boxed-typing-lines, .boxed-line, .TPGAME')) continue; } catch (e) {}
        let inModal = false;
        try { inModal = !!el.closest(MODAL_SEL); } catch (e) {}
        if (!inModal) continue;
        if (doClick(el, 'tutup-teks:"' + txt + '"')) break outer3b;
    }
}
return taken;
"""

ESC_FALLBACK_JS = r"""
const ev = new KeyboardEvent('keydown', {key: 'Escape', code: 'Escape', keyCode: 27,
                                          which: 27, bubbles: true, cancelable: true});
[window, document, document.body].forEach(t => { try { t.dispatchEvent(ev); } catch (e) {} });
return true;
"""

MODAL_HINT_JS = r"""
const dlgs = document.querySelectorAll('[class*="modal" i], [class*="popup" i], [class*="dialog" i], [role="dialog"]');
for (const d of dlgs) {
    if (!(d.offsetWidth > 100 && d.offsetHeight > 80)) continue;
    const t = (d.innerText || '').toLowerCase();
    const achievement = /achievement|badge unlocked|congratulation|selamat/.test(t);
    const premium = /premium|upgrade|subscription|subscribe|langganan|berlangganan|go pro|unlock all/.test(t);
    if (achievement || premium) return {achievement: achievement, premium: premium};
}
return null;
"""

PREMIUM_MODAL_JS = r"""
// Modal premium: return {x,y} = titik tombol X (edmodal-x) untuk klik
// mouse asli, atau {zombie:true} kalau modal fullscreen Tanpa X (iframe
// checkout Stripe sudah mengambil alih). di 2968: klik X
// -> edclub otomatis lanjut ke lesson berikutnya (perilaku yang sama
// dengan popup premium di akun teman: tutup = lanjut level).
// Catatan: Jangan blokir request Stripe - modal yang checkout-nya gagal
// termuat jadi zombie gelap menetap (ever terjadi: 'gelap' false alarm).
let modal = null;
for (const d of document.querySelectorAll('[class*="modal" i], [role="dialog"]')) {
    if (d.offsetWidth > 100 && d.offsetHeight > 80) { modal = d; break; }
}
if (!modal) return null;
let x = modal.querySelector('.edmodal-x');
if (!x) x = modal.querySelector('[class*="close" i], [aria-label*="close" i]');
if (x && (x.offsetWidth || x.offsetHeight)) {
    const r = x.getBoundingClientRect();
    const cx = r.left + r.width/2, cy = r.top + r.height/2;
    const top = document.elementFromPoint(cx, cy);
    if (top && (top === x || x.contains(top) || top.contains(x)) && !x.closest('iframe'))
        return {x: cx, y: cy};
}
for (const el of modal.querySelectorAll('span, div, a, button, i')) {
    if (!(el.offsetWidth || el.offsetHeight) || el.children.length > 1) continue;
    const t = (el.innerText || '').trim();
    if (t !== '\u00d7' && t !== '\u2715' && t.toLowerCase() !== 'x') continue;
    const r = el.getBoundingClientRect();
    if (r.width > 60 || r.height > 60) continue;
    const cx = r.left + r.width/2, cy = r.top + r.height/2;
    const top = document.elementFromPoint(cx, cy);
    if (top && (top === el || el.contains(top) || top.contains(el)) && !el.closest('iframe'))
        return {x: cx, y: cy};
}
for (const f of modal.querySelectorAll('iframe')) {
    if ((f.src || '').toLowerCase().includes('stripe')) return {zombie: true};
}
const mt = (modal.innerText || '').toLowerCase();
if (modal.offsetHeight > window.innerHeight * 0.5 &&
    /premium|upgrade|subscription|langganan|berlangganan|go pro|unlock all/.test(mt))
    return {zombie: true};
return null;
"""

_repeat_click = {"label": "", "count": 0, "until": 0.0}


BADGE_STREAK_JS = r"""
// Popup badge streak / pencapaian (live 23:33, level 662): '.badgebg'
// overlay 320x320 tanpa tombol tutup, teksnya ('5 Day Streak...') ada di
// Elemen Saudara (.badge_text) bukan di dalamnya - jadi selector modal
// lama ([class*=modal/popup/dialog]) tidak pernah cocok. Penutup yang
// Terbukti live: tekan ESC sungguhan (CDP keyboard). Return true kalau
// badge terlihat.
const bg = document.querySelector('.badgebg');
if (bg && (bg.offsetWidth > 50 || bg.offsetHeight > 50)) return true;
return false;
"""


def close_overlays_all_frames():
    """Jalankan penutup pop-up di semua frame. Return jumlah aksi."""
    if time.time() < _repeat_click["until"]:
        return 0
    total = 0
    # Badge streak: tidak punya tombol tutup - ESC keyboard asli (CDP,
    # isTrusted) menutupnya (live terverifikasi; KeyboardEvent sintetis
    # berisiko tidak dipercaya seperti JS .click()).
    try:
        if run_js(BADGE_STREAK_JS, PAGE.main_frame):
            PAGE.keyboard.press("Escape")
            print("[Pop-up] badge streak/pencapaian ditutup (ESC)")
            total += 1
    except Exception:
        pass
    for fr in _edclub_frames():
        taken = run_js(OVERLAY_JS, fr)
        if taken:
            print(f"[Pop-up] {frame_label(fr)}: {'; '.join(taken[:3])}")
            total += len(taken)
            first = taken[0]
            if first == _repeat_click["label"]:
                _repeat_click["count"] += 1
                if _repeat_click["count"] >= 3:
                    # Klik JS x3 tanpa hasil = pop-up premium butuh gesture
                    # sungguhan. Bahaya terbukti : klik mouse di area
                    # iframe Stripe yang menutupi layar = tab terbawa ke
                    # checkout stripe -> bot nyangkut. Maka: hanya klik
                    # elemen tutup yang 1) selektornya presisi (bukan
                    # sembarang class mengandung huruf 'x') dan 2) titik
                    # tengahnya benar-benar di atas elemen itu (cek
                    # elementFromPoint), bukan di bawah iframe.
                    print("[Pop-up] klik tutup tanpa hasil - eskalasi "
                          "ESC + klik mouse (dengan pengecekan posisi)")
                    run_js(ESC_FALLBACK_JS, fr)
                    run_js(r"""
// cari tombol tutup presisi + verifikasi tidak tertutup iframe
const cands = [];
for (const sel of ['[class*="popup" i] [class*="close" i]',
                   '[class*="modal" i] [class*="close" i]',
                   '[aria-label*="close" i]', '[data-dismiss]']) {
    for (const el of document.querySelectorAll(sel)) {
        if (!(el.offsetWidth || el.offsetHeight)) continue;
        const r = el.getBoundingClientRect();
        const cx = r.left + r.width/2, cy = r.top + r.height/2;
        const top = document.elementFromPoint(cx, cy);
        if (!top || (top !== el && !el.contains(top) && !top.contains(el))) continue;
        if (el.querySelector('iframe') || el.closest('iframe')) continue;
        cands.push({x: cx, y: cy});
    }
    if (cands.length) break;
}
window.__CLICKPT = cands.length ? cands[0] : null;
""", fr)
                    pt = run_js("return window.__CLICKPT;", fr)
                    if pt:
                        try:
                            _tandai_klik_bot()
                            PAGE.mouse.click(pt["x"], pt["y"])
                        except Exception:
                            pass
                    _repeat_click["until"] = time.time() + 8
                    _repeat_click["count"] = 0
            else:
                _repeat_click["label"] = first
                _repeat_click["count"] = 1
            break
    if total == 0:
        for fr in _edclub_frames():
            hint = run_js(MODAL_HINT_JS, fr)
            if hint and hint.get("achievement"):
                if run_js(ESC_FALLBACK_JS, fr):
                    print("[Pop-up] modal tanpa tombol tutup, kirim ESC "
                          "(achievement)")
                    total += 1
                break
            # jangan ESC modal premium: ESC pernah mengkonsumsi modal
            # premium sekali-per-page-load tanpa memajukan level (log
            # 08:02). Modal premium ditangani _premium_modal_action
            # (klik X = edclub lanjut lesson berikutnya).
            if hint and hint.get("premium"):
                break
    return total


# ---------------------------------------------------------------------------
# Mesin ketik (CDP via Playwright - tidak butuh fokus jendela OS)
# ---------------------------------------------------------------------------


def _clear_modifiers():
    """Lepas modifier yang mungkin nyangkut (Shift/Ctrl/Alt). key-up tidak
    menghasilkan karakter, jadi aman - mencegah simbol/huruf salah pada
    lesson berikutnya (mis. sisa Shift dari lesson hold)."""
    for key in ("Shift", "Control", "Alt", "Meta"):
        try:
            PAGE.keyboard.up(key)
        except Exception:
            pass


_loop_overhead = 0.030   # estimasi overhead verifikasi per karakter (ewma)
_last_char_delay = 0.0


def _char_delay(slow=False):
    """Jeda per karakter dari target WPM (1 kata = 5 karakter).
    Delay dikurangi overhead verifikasi yang terukur (loop mengukur sendiri
    via _loop_overhead) supaya LAJU AKHIR benar-benar mendekati target:
    140 wpm = ~86 ms/kar total, 200 = 60, 85 = 141.
    slow=True (tutorial boxed): engine butuh waktu animasi per karakter -
    jangan turun di bawah cadence aman (0.14-0.24 s)."""
    global _last_char_delay
    wpm = SPEEDS[SPEED_IDX][0]
    if slow:
        _last_char_delay = random.uniform(0.14, 0.24)
        return _last_char_delay
    base = 12.0 / wpm - _loop_overhead
    base = max(base, 0.004)
    _last_char_delay = base * random.uniform(0.85, 1.15)
    return _last_char_delay


def type_chars(text, max_chars=None, slow=False):
    """Ketik via CDP. slow=True untuk tutorial boxed (animasi scroll-garis).
    TIDAK ada jeda untuk 'aktivitas user': input CDP isTrusted=true sehingga
    deteksi keydown mempan false-positive, dan klik mouse di tengah
    halaman tidak mengganggu engine. Gangguan user yang betulan (klik
    halaman / tekan tombol) terdeteksi otomatis oleh
    loop verifikasi handle_standard (karakter tak terkonsumsi -> koreksi
    backspace / re-fokus), bukan oleh jeda di sini."""
    for char in (text if max_chars is None else text[:max_chars]):
        while PAUSED and not STOP:
            time.sleep(0.15)
        if STOP:
            return False
        try:
            if char == "\n":
                PAGE.keyboard.press("Enter")
                time.sleep(0.03 + 0.02 * random.random())
            elif char == "\t":
                PAGE.keyboard.press("Tab")
                time.sleep(_char_delay(slow))
            elif char == " ":
                # wajib type() bukan press(): engine butuh event keypress/input
                # penuh untuk spasi - press() hanya kirim down/up = ditandai salah
                PAGE.keyboard.type(" ")
                time.sleep(_char_delay(slow))
            else:
                PAGE.keyboard.type(char)
                time.sleep(_char_delay(slow))
        except Exception:
            return False
    return True


# ---------------------------------------------------------------------------
# Deteksi intervensi user asli.
#
# Event input CDP milik bot punya isTrusted=false; tangan user menghasilkan
# isTrusted=true (tidak bisa dipalsukan dari JS/CDP). Listener di tiap
# frame edclub mencatat timestamp event trusted terakhir -> bot tahu
# persis kapan user sedang memegang halaman, dan mundur sampai user diam.
# (kasus: user klik tombol pengaturan saat bot mengetik -> engine
# kehilangan fokus, ketikan berhenti dikonsumsi, dan bot salah mengira
# 'selesai tanpa layar skor' lalu menekan tombol lanjut.)
# ---------------------------------------------------------------------------

USER_WATCH_JS = r"""
if (!window.__tb_watch) {
  window.__tb_watch = 1;
  window.__tb_user = 0;      // timestamp aktivitas user terakhir
  window.__tb_ignore = 0;    // abaikan event sampai waktu ini (klik bot)
  var rec = function(e){
    if (!e || !e.isTrusted) return;
    var now = Date.now();
    if (window.__tb_ignore && now < window.__tb_ignore) return;
    window.__tb_user = now;
  };
  // Mouse/Scroll Saja: input CDP bot punya isTrusted=true (diinjeksi di
  // level browser, tidak bisa dibedakan dari user) - keydown Tidak boleh
  // dipantau karena bot sendiri mengetik. Klik mouse bot ditutupi
  // lewat __tb_ignore yang dipasang sebelum bot mengklik.
  ['mousedown','mouseup','wheel','touchstart','contextmenu'].forEach(
    function(n){ window.addEventListener(n, rec, true); });
  window.addEventListener('blur', function(){ window.__tb_user = Date.now(); });
}
return (Date.now() - (window.__tb_user || 0)) / 1000;
"""

_user_watch_cache = {"t": 0.0, "elapsed": 1e9}
_user_note = {"tunda": False}


def _tandai_klik_bot(frame=None, ms=900):
    """Panggil SEBELUM bot mengklik dengan mouse CDP: event mousedown-
    nya jangan dihitung sebagai 'aktivitas user' (echo klik sendiri)."""
    run_js(f"window.__tb_ignore = Date.now() + {int(ms)}; return 1;",
           frame if frame is not None else PAGE.main_frame)


def _user_aktif(batas=2.0):
    """True kalau user asli aktif dalam `batas` detik terakhir di halaman
    edclub (klik/ketik/scroll/ambil fokus). Cache 0.5 dtk supaya murah
    dipanggil per karakter. Kegagalan baca = dianggap tidak aktif."""
    now = time.time()
    if now - _user_watch_cache["t"] < 0.5:
        return _user_watch_cache["elapsed"] < batas
    _user_watch_cache["t"] = now
    terbaik = 1e9
    try:
        for fr in _edclub_frames():
            v = run_js(USER_WATCH_JS, fr)
            if isinstance(v, (int, float)) and v < terbaik:
                terbaik = v
    except Exception:
        pass
    _user_watch_cache["elapsed"] = terbaik
    return terbaik < batas


_tunggu_user_since = {"url": "", "t": 0.0}
MINTA_TANYA_LANJUT = False   # GUI: popup 'masih menunggu?' setelah 2 menit


def _tunggu_user(url):
    """User sedang menjelajah (bukan di lesson) - catat & tunggu; kalau
    lebih dari 2 menit, minta GUI menanyakan lanjut/stop."""
    global MINTA_TANYA_LANJUT
    st = _tunggu_user_since
    if st["url"] != url:
        st["url"] = url
        st["t"] = time.time()
        print("[USER] kamu sedang memakai browser bot - bot menunggu "
              "(lanjut otomatis begitu kamu diam / buka lesson)")
    elif time.time() - st["t"] > 120 and not MINTA_TANYA_LANJUT:
        MINTA_TANYA_LANJUT = True
    time.sleep(0.5)


def _user_diam_lagi(url):
    """Reset status menunggu (dipanggil saat bot bisa bekerja lagi)."""
    global MINTA_TANYA_LANJUT
    if _tunggu_user_since["url"]:
        _tunggu_user_since.update(url="", t=0.0)
        MINTA_TANYA_LANJUT = False
        print("[USER] halaman tenang - bot lanjut bekerja.")


_enter_times = []


def press_enter_guarded():
    """Enter untuk menu skor: maks 3x per 6 detik, lalu jeda 15 detik."""
    global _enter_times
    now = time.time()
    _enter_times = [t for t in _enter_times if now - t < 6]
    if len(_enter_times) >= 3:
        print("[Skor] Enter berulang tanpa efek, jeda 15 detik")
        _enter_times = [now + 15]
        return False
    if _enter_times and _enter_times[0] > now:
        return False
    _enter_times.append(now)
    try:
        PAGE.keyboard.press("Enter")
        return True
    except Exception:
        return False


def advance_score_screen():
    """Layar skor: Enter dulu. Kalau Enter sudah berulang tanpa efek,
    klik tombol lanjut dengan mouse CDP sungguhan - JS .click() tidak
    dihitung sebagai gesture user oleh sebagian tombol edclub (sama
    seperti tombol play video), jadi klik JS terlihat 'tanpa hasil'."""
    if press_enter_guarded():
        print("[Skor] Enter ditekan")
        return True
    for sel in (".navbar-continue", "a.navbar-continue",
                ".lesson-complete button.btn-primary", "button.continue"):
        try:
            loc = PAGE.locator(sel)
            if loc.count() == 0:
                continue
            _tandai_klik_bot()
            loc.first.click(timeout=1500)
            print(f"[Skor] klik lanjut via mouse: {sel}")
            return True
        except Exception:
            continue
    return False


def focus_frame(frame):
    """Fokus internal frame (bukan OS): cukup window.focus + body.focus.
    TANPA klik body - klik mouse CDP di body jatuh di atas keyboard layar
    pada level intro (tombol menyala ORANGE = ditekan-mouse), mengganggu
    engine dan keystroke berikutnya kadang ditelan."""
    run_js("try{window.focus();if(document.body&&document.body.focus)document.body.focus();}catch(e){}", frame)


# ---------------------------------------------------------------------------
# Anti-pause: edclub men-pause lesson saat window blur (banner "Start Typing").
# Solusi: paksa hasFocus() selalu true + dispatch event focus + klik banner.
# ---------------------------------------------------------------------------

ANTI_PAUSE_JS = r"""
try { Document.prototype.hasFocus = function () { return true; }; } catch (e) {}
try { window.dispatchEvent(new Event('focus')); } catch (e) {}
try { document.dispatchEvent(new Event('focus')); } catch (e) {}
try { document.dispatchEvent(new Event('visibilitychange')); } catch (e) {}
const b = document.querySelector('.drop-banner');
if (b && (b.offsetWidth || b.offsetHeight)) {
    try { b.click(); } catch (e) {}
    return 'banner';
}
return true;
"""


def keep_alive_frames():
    """Jalankan anti-pause di semua frame. Return True jika banner diklik."""
    clicked = False
    for fr in _edclub_frames():
        res = run_js(ANTI_PAUSE_JS, fr)
        if res == "banner":
            clicked = True
    return clicked


QUIET_ALIVE_JS = r"""
// Versi Tanpa Klik: hanya patch fokus + dispatch event. Aman dipakai
// berulang selama mengetik.
try { Document.prototype.hasFocus = function () { return true; }; } catch (e) {}
try { window.dispatchEvent(new Event('focus')); } catch (e) {}
try { document.dispatchEvent(new Event('focus')); } catch (e) {}
try { document.dispatchEvent(new Event('visibilitychange')); } catch (e) {}
return true;
"""


def keep_alive_quiet(frame):
    """Anti-pause tanpa klik apa pun (dipakai selama mengetik)."""
    run_js(QUIET_ALIVE_JS, frame)


def esc_modals_only(frame):
    """Kirim ESC hanya jika ada modal achievement/premium betul-betul tampil.
    Tidak ada klik sama sekali - aman di tengah ketikan."""
    hint = run_js(MODAL_HINT_JS, frame)
    if hint and (hint.get("achievement") or hint.get("premium")):
        run_js(ESC_FALLBACK_JS, frame)
        print(f"[Pop-up] modal ditutup via ESC saat mengetik "
              f"({'achievement' if hint.get('achievement') else 'premium'})")


# ---------------------------------------------------------------------------
# Level standar (+ hold-key while typing)
# ---------------------------------------------------------------------------

HOLD_LESSON_JS = r"""
for (const el of document.querySelectorAll('div, span, p')) {
    const t = (el.innerText || '').trim();
    if (!t || t.length > 120 || !el.offsetWidth) continue;
    const m = t.match(/^hold (?:down )?(?:the )?([a-z])\s+key[\s\S]*typing/i);
    if (m) return {key: m[1], instr: t.replace(/\n/g, ' ')};
}
return null;
"""


# Baca sisa teks yang masih harus diketik (hanya token _clr, urutan DOM).
READ_REMAINING_JS = r"""
const els = document.querySelectorAll('span.token_unit._clr');
if (!els.length) return null;
const out = [];
for (const e of els) {
    const txt = e.innerText || e.textContent;
    if (!txt) continue;
    if (txt.includes('↵') || txt.includes('\n')) out.push('\n');
    else if (txt.includes('↹') || txt.includes('\t')) out.push('\t');
    else {
        let run = 0;
        for (const ch of txt) {
            if (ch === '\u00A0' || ch === ' ') { run++; continue; }
            if (run === 1) out.push(' ');
            else if (run >= 2) out.push('\t');
            run = 0;
            out.push(ch);
        }
        if (run === 1) out.push(' ');
        else if (run >= 2) out.push('\t');
    }
}
return out.join('');
"""


def read_remaining(frame):
    """Sisa teks lesson (hanya token pending). None jika tak ada token."""
    return run_js(READ_REMAINING_JS, frame)


ERR_COUNT_JS = r"""
return document.querySelectorAll('span.token_unit._err').length;
"""


def count_errors(frame):
    """Jumlah karakter yang sudah ditandai salah di lesson."""
    n = run_js(ERR_COUNT_JS, frame)
    return n if isinstance(n, int) else None


STATE_JS = r"""
// Satu roundtrip untuk loop ketik: sisa teks (_clr) + jumlah salah (_err).
const out = [];
for (const e of document.querySelectorAll('span.token_unit._clr')) {
    const txt = e.innerText || e.textContent;
    if (!txt) continue;
    if (txt.includes('\u21b5') || txt.includes('\n')) out.push('\n');
    else if (txt.includes('\u21b9') || txt.includes('\t')) out.push('\t');
    else {
        let run = 0;
        for (const ch of txt) {
            if (ch === '\u00a0' || ch === ' ') { run++; continue; }
            if (run === 1) out.push(' ');
            else if (run >= 2) out.push('\t');
            run = 0;
            out.push(ch);
        }
        if (run === 1) out.push(' ');
        else if (run >= 2) out.push('\t');
    }
}
const err = document.querySelectorAll('span.token_unit._err').length;
return [out.join(''), err];
"""


def read_state(frame):
    """(sisa_teks, jumlah_salah) dalam SATU evaluate. None teks = tak ada
    token pending. Dipakai di loop ketik per-karakter supaya cepat."""
    res = run_js(STATE_JS, frame)
    if not isinstance(res, list) or len(res) != 2:
        return None, None
    rem = res[0] if isinstance(res[0], str) else None
    err = res[1] if isinstance(res[1], int) else None
    return rem, err


START_BANNER_JS = r"""
// Klik banner "Start Typing" Sekali di awal lesson (state pause awal).
// Jangan pernah mengklik apa pun saat sedang mengetik (bisa reset lesson!).
const b = document.querySelector('.drop-banner');
if (b && (b.offsetWidth || b.offsetHeight)) {
    try { b.click(); return 'klik'; } catch (e) {}
}
return null;
"""


_std_last_rem = None
_std_attempts = 0
_stall_user_note = False


def handle_standard(frame, text):
    global last_typed_text, last_action_time, _std_last_rem, _std_attempts, _stall_user_note
    # Level terkunci premium: modal premium menutupi lesson, input mati.
    # Dulu bot mencoba mengetik 3x (gagal, buang waktu) bahkan sempat
    # mengklik tombol CTA premium yang membawa ke Stripe Checkout.
    # Sekarang: langsung lewati level via tombol lanjut (klik mouse asli).
    for fr in all_frames():
        hint = run_js(MODAL_HINT_JS, fr)
        if hint and hint.get("premium"):
            print("[Premium] level terkunci premium - lewati via tombol lanjut")
            try:
                _tandai_klik_bot()
                PAGE.locator(".navbar-continue, a.navbar-continue") \
                    .first.click(timeout=2500)
            except Exception:
                pass
            last_action_time = time.time()
            return True
    hold = run_js(HOLD_LESSON_JS, frame) or {}
    hold_key = hold.get("key")

    rem = read_remaining(frame)
    if rem is None:
        return False
    # anti-busur: teks sama persis & sudah dicoba 3x -> diamkan (biarkan
    # handler lain / recovery yang bekerja)
    if rem == _std_last_rem:
        _std_attempts += 1
        if _std_attempts > 3:
            return False
    else:
        _std_last_rem = rem
        _std_attempts = 1

    print(f"[Standard] Sisa {len(rem)} karakter: {rem[:24]!r}..."
          + (f" (TAHAN {hold_key!r})" if hold_key else ""))
    focus_frame(frame)

    # stabilisasi: sisa teks tidak berubah sebentar (halaman siap)
    for _ in range(8):
        time.sleep(0.12)
        r2 = read_remaining(frame)
        if r2 is None or r2 != rem:
            rem = r2
            continue
        break
    if rem is None:
        return False

    # aktifkan lesson: klik banner "Start Typing" jika sedang tampil
    if run_js(START_BANNER_JS, frame):
        print("[Standard] banner Start Typing diklik")
        time.sleep(0.4)
        rem = read_remaining(frame) or ""

    typed_any = False
    try:
        if hold_key:
            PAGE.keyboard.down(hold_key)
            time.sleep(0.15)
        # ketik per-karakter terverifikasi (prinsip: tidak boleh salah):
        # Karakter berikutnya tidak pernah dikirim sebelum karakter saat ini
        # terverifikasi dikonsumsi dengan benar oleh engine lesson.
        # - salah tidak pernah berantai: deteksi terjadi 1 karakter, bukan 20.
        # - kalau konsumsi tidak persis (keystroke hilang / DOM berganti /
        # banner pause), ketikan berhenti dan realign ke DOM - tidak
        # pernah lanjut berdasarkan asumsi.
        # - modifier (Shift dll.) dilepas dulu: sisa modifier = karakter
        # salah pada lesson berikutnya.
        # - karakter yang ditandai salah (_err) segera di-Backspace sekali;
        # kalau situs tidak mengizinkan, dicatat dan lanjut (maks 1 char).
        # penting: selama mengetik tidak ada klik apa pun - klik di tengah
        # ketikan bisa me-reset lesson.
        _clear_modifiers()
        pre_err = count_errors(frame)
        if pre_err:
            print(f"[Standard] {pre_err} karakter salah sudah ada sebelum mulai, "
                  "coba koreksi dengan Backspace")
            try:
                for _ in range(pre_err):
                    PAGE.keyboard.press("Backspace")
                    time.sleep(0.06)
                time.sleep(0.4)
            except Exception:
                pass
            left = count_errors(frame)
            if left is not None and left < pre_err:
                rem = read_remaining(frame) or rem
            else:
                print("[Standard] koreksi awal tidak mempan (salah terkunci) "
                      "- lanjut, akurasi lesson ini bisa < 100%")
        stall = 0
        verified = 0
        bs_ok = True
        err_prev = count_errors(frame)
        if err_prev is None:
            err_prev = 0
        while True:
            if STOP:
                break
            while PAUSED and not STOP:
                time.sleep(0.15)
            if not rem:
                break
            ch = rem[0]
            t_char = time.time()
            if not type_chars(ch):
                break
            typed_any = True
            rem2, err_after = read_state(frame)
            if err_after is None:
                err_after = err_prev
            if err_after > err_prev and bs_ok:
                # 1 karakter tertandai salah - coba hapus sekarang
                try:
                    PAGE.keyboard.press("Backspace")
                    time.sleep(0.25)
                except Exception:
                    pass
                r_chk, err_chk = read_state(frame)
                if err_chk is not None and err_chk < err_after:
                    rem2 = r_chk  # token kembali pending
                    err_after = err_chk
                else:
                    bs_ok = False
                    print("[Standard] 1 karakter salah tidak bisa dihapus "
                          "(lanjut - tercatat di akurasi)")
                    rem2 = r_chk
            if rem2 is None or rem2 == "":
                # bisa berarti selesai, tapi juga "baris berikut belum
                # muncul di DOM" (render progresif). Jangan langsung anggap
                # selesai: tunggu grace, ketik ulang tidak boleh (Enter
                # dobel = salah). Baris baru muncul < 300 ms di situs asli,
                # jadi grace singkat cukup.
                got = None
                for _ in range(8):
                    time.sleep(0.10)
                    r = read_remaining(frame)
                    if r:
                        got = r
                        break
                if got:
                    rem = got
                    stall = 0
                    continue
                break  # benar-benar tidak ada token = lesson selesai
            if rem2 == rem:
                # Karakter tidak terkonsumsi. Penyebab umum: klik user (di
                # halaman / di luar window -> blur -> engine pause sesaat,
                # caret pindah). pulihkan sekarang, bukan tangga jeda:
                # dulu stall 1-7 menumpuk sleep 0.05+0.15 (~0.5-3 dtk
                # tersendat per klik) dan spam-klik mencapai stall>=8 ->
                # tombol lanjut diklik -> typing berhenti total (keluhan
                # live 2x). Sekarang: fokus + banner dipulihkan tiap
                # iterasi (murah, tanpa klik mouse), poll cepat; eskalasi
                # tombol lanjut hanya kalau user tidak sedang memegang
                # halaman (klik user = mouse-only watcher, aman dari
                # ketikan bot sendiri).
                stall += 1
                user_kehadian = _user_aktif(3.0)
                if user_kehadian:
                    stall = min(stall, 3)
                    if not _stall_user_note:
                        _stall_user_note = True
                        print("[Standard] user memegang halaman - fokus "
                              "dipulihkan terus, mengetik tidak berhenti")
                else:
                    _stall_user_note = False
                run_js(QUIET_ALIVE_JS, frame)
                focus_frame(frame)
                if run_js(START_BANNER_JS, frame):
                    print("[Standard] banner pause muncul, diklik")
                    time.sleep(0.15)
                time.sleep(0.04)
                r_retry, _ = read_state(frame)
                if r_retry is not None and r_retry != rem:
                    rem = r_retry
                    stall = 0
                    verified += 1
                    if verified % 20 == 0:
                        keep_alive_quiet(frame)
                    if verified % 25 == 0:
                        esc_modals_only(frame)
                    continue
                if stall >= 8 and not user_kehadian:
                    # benar-benar macet tanpa user: kemungkinan lesson
                    # selesai tapi layar skor tidak muncul (bug situs,
                    # terbukti L87/192) - satu klik tombol lanjut langsung
                    # ke lesson berikutnya.
                    print("[Standard] ketikan tidak masuk - mungkin selesai "
                          "tanpa layar skor, coba tombol lanjut")
                    if _phaser_try_advance():
                        last_action_time = time.time()
                        time.sleep(0.6)
                        return True
                    break
                err_prev = err_after
                continue
            # terkonsumsi / DOM berubah -> selalu percaya DOM terbaru
            rem = rem2
            stall = 0
            verified += 1
            err_prev = err_after
            # kalibrasi laju: overhead aktual per karakter (verifikasi dll.)
            # diukur & dikompensasikan di jeda karakter berikutnya.
            global _loop_overhead
            oh = (time.time() - t_char) - _last_char_delay
            oh = min(max(oh, 0.0), 0.15)
            _loop_overhead = 0.7 * _loop_overhead + 0.3 * oh
            if verified % 20 == 0:
                keep_alive_quiet(frame)
            if verified % 25 == 0:
                esc_modals_only(frame)
    finally:
        if hold_key:
            try:
                PAGE.keyboard.up(hold_key)
            except Exception:
                pass
        _clear_modifiers()
    if not typed_any:
        return False
    last_typed_text = text
    stats["std"] += 1
    last_action_time = time.time()
    err_total = count_errors(frame)
    if err_total:
        print(f"[Standard] lesson selesai dengan {err_total} karakter salah")

    # Tunggu transisi post-lesson. penting: keluar segera begitu URL
    # berganti (level baru) - intro/skor->level baru tidak pernah
    # menghasilkan state std/mini/tut, dulu loop ini burn deadline penuh
    # (10+8 dtk) padahal level berikutnya sudah siap dikerjakan.
    # Kasus nyata (L113): lesson selesai tapi layar skor tidak pernah
    # muncul (bug situs) - tombol lanjut ada, klik mouse asli langsung.
    entry_url = PAGE.url
    no_score_clicked = False
    entry_wait_start = time.time()
    deadline = time.time() + 10
    while time.time() < deadline:
        if close_overlays_all_frames():
            time.sleep(0.6)
            continue
        state, _, _ = detect_all_frames()
        if state == "score":
            advance_score_screen()
            time.sleep(0.8)
        if state in ("std", "mini", "tut"):
            break
        if PAGE.url != entry_url:
            break   # level sudah pindah - jangan tunggu sisa deadline
        if not no_score_clicked and time.time() > entry_wait_start + 3.0:
            # 3 dtk tanpa skor/URL: kemungkinan layar skor tidak muncul
            # -> satu klik lanjut (mouse asli) menyelesaikannya.
            try:
                loc = PAGE.locator(".navbar-continue, a.navbar-continue").first
                if loc.count() and loc.is_visible():
                    loc.click(timeout=2000)
                    no_score_clicked = True
                    print("[Standard] layar skor belum muncul - klik "
                          "tombol lanjut")
                    time.sleep(0.8)
                    continue
            except Exception:
                pass
        time.sleep(0.25)

    deadline = time.time() + 8
    while time.time() < deadline:
        state, _, _ = detect_all_frames()
        if state != "unknown":
            break
        if PAGE.url != entry_url:
            break
        time.sleep(0.2)
    last_action_time = time.time()
    return True


# ---------------------------------------------------------------------------
# Tutorial boxed
# ---------------------------------------------------------------------------

_tut_sig = None
_tut_attempts = 0


# sisa teks tutorial boxed, tanpa mengenal nama class edclub:
# engine boxed pasti menandai karakter selesai lewat class (di span, di
# .boxed-char, atau di .boxed-line induknya). Trik: gabungkan semua class
# tiap karakter jadi "tanda", lalu ambil run terakhir yang tandanya sama
# dengan tanda karakter terakhir (= run karakter yang masih pending).
# Ditambah info tanda: kalau semua karakter satu tanda & beda dari tanda
# pending yang dikenal -> layar sudah selesai (jangan type ulang!).
TUT_REMAIN_JS = r"""
const spans = Array.from(document.querySelectorAll('.boxed-line > span'))
    .filter(sp => sp.querySelector('.boxed-char'));
if (!spans.length) return null;
function sig(sp) {
    const ch = sp.querySelector('.boxed-char');
    let line = '';
    try { const l = sp.closest('.boxed-line'); line = l ? l.className : ''; } catch (e) {}
    return (line + '|' + sp.className + '|' + ch.className).trim();
}
const sigs = spans.map(sig);
const lastSig = sigs[sigs.length - 1];
let i = sigs.length - 1;
while (i >= 0 && sigs[i] === lastSig) i--;
// sertakan run Pendek (<=2) sebelum trailing run = karakter Aktif
// (di-highlight sendiri oleh situs asli; tanpa ini karakter aktif
// terjatuh dari ekstraksi -> urutan ketikan bergeser satu = desync)
let start = i + 1;
if (i >= 0) {
    let j = i;
    while (j >= 0 && sigs[j] === sigs[i]) j--;
    if (i - j <= 2) start = j + 1;
}
const chars = [];
for (let k = start; k < spans.length; k++) {
    let c = (spans[k].querySelector('.boxed-char').textContent || '').slice(0, 1);
    if (c === '\u00a0' || c === ' ') c = ' ';
    else c = c.trim();
    if (c) chars.push(c);
}
return {rem: chars.join(''), total: spans.length,
        firstSig: sigs[0], lastSig: lastSig,
        allSame: sigs.every(s => s === lastSig)};
"""

_tut_pending_sig = None


def _tut_read(frame):
    res = run_js(TUT_REMAIN_JS, frame)
    return res if isinstance(res, dict) else None


_tut_full = None


def handle_tutorial(frame, data):
    global _tut_sig, _tut_attempts, last_action_time, _tut_full
    text = data.get("text", "")
    if not text:
        return False
    if text == _tut_sig and _tut_attempts >= 6:
        return False
    if text != _tut_sig:
        _tut_sig = text
        _tut_attempts = 0
        _tut_full = text
    _tut_attempts += 1
    focus_frame(frame)
    print(f"[Tutorial] ketik {text!r} (coba {_tut_attempts})")
    if run_js(START_BANNER_JS, frame):
        time.sleep(0.4)
    # pola level = lesson standar dengan UI lain (kesimpulan user, benar):
    # ketik urutan penuh sekali dengan kecepatan normal (140 wpm) - transisi
    # animasi tidak perlu selesai untuk bisa lanjut. keuali di awal level:
    # tepat setelah intro, ada jendela mati saat transisi - ketikan pertama
    # jatuh ke ruang kosong. Tunggu layar stabil (bacaan sisa sama 2x,
    # maks ~2 dtk) sebelum mulai. Resume hanya saat re-entry dengan suffix
    # jujur. tanpa jalur input tambahan apapun (klik layar/event sintetis
    # = duplikat = flash merah).
    rem = text
    res = _tut_read(frame)
    stable = 0
    for _ in range(8):
        time.sleep(0.25)
        r2 = _tut_read(frame)
        if (res is not None and r2 is not None
                and r2.get("rem") == res.get("rem")):
            stable += 1
        else:
            res = r2
            stable = 0
        if stable >= 2:
            break
    if (_tut_attempts >= 2 and _tut_full and res
            and isinstance(res.get("rem"), str)
            and 0 < len(res["rem"]) < len(_tut_full)
            and _tut_full.endswith(res["rem"])):
        rem = res["rem"]
        print(f"[Tutorial] lanjut dari sisa {len(rem)} karakter")
    CH = 10   # potongan kecil utk keep-alive senyap di selanya
    while rem:
        if STOP:
            return False
        while PAUSED and not STOP:
            time.sleep(0.15)
        n = min(CH, len(rem))
        if not type_chars(rem[:n]):
            break
        keep_alive_quiet(frame)
        rem = rem[n:]
    # akhir pola: Enter (pola user: sequence > enter). Kalau layar skor
    # sudah muncul duluan, Enter justru menekan lanjut - aman dua-duanya.
    time.sleep(0.8)
    try:
        PAGE.keyboard.press("Enter")
        print("[Tutorial] selesai - Enter")
    except Exception:
        pass
    stats["tut"] += 1
    last_action_time = time.time()
    time.sleep(0.3)
    return True


# ---------------------------------------------------------------------------
# Minigame DOM
# ---------------------------------------------------------------------------

_last_focus_click = {}


def handle_minigame(frame, data):
    global last_action_time
    now = time.time()
    key = frame.url or frame.name
    if now - _last_focus_click.get(key, 0) > 30:
        _last_focus_click[key] = now
        focus_frame(frame)
    text = data.get("text", "")
    print(f"[Minigame/{data.get('source','?')}] Mengetik: {text[:18]!r}")
    if not type_chars(text, max_chars=14):
        return False
    stats["mini"] += 1
    last_action_time = time.time()
    time.sleep(0.15)
    return True


# ---------------------------------------------------------------------------
# Minigame Phaser (core.record_keydown_time) - sudah tanpa fokus sejak awal
# ---------------------------------------------------------------------------

PHASER_FEED_JS = r"""
const gs = [];
for (const g of (window.Phaser ? Phaser.GAMES : [])) {
    try {
        const st = g.state.states[g.state.current];
        if (st && st.core && typeof st.core.record_keydown_time === 'function') gs.push({g: g, st: st});
    } catch (e) {}
}
if (!gs.length) return null;
const pick = gs[gs.length - 1];
if (pick.g.paused) { try { pick.g.paused = false; } catch (e) {} }
const c = pick.st.core;
if (c.has_ended || !c.cur_char) return {fed: false, ended: !!c.has_ended};
const chr = c.cur_char.chr;
if (chr === undefined || chr === null || chr === '' || chr === '<-') {
    return {fed: false, ended: false};
}
c.record_keydown_time(chr);
return {fed: true, chr: chr, idx: c.cur_char_index, ended: !!c.has_ended};
"""

# Game multi-kata (pilih kata bebas): coba kandidat char dari semua kata
# yang belum selesai, bukan hanya cur_char yang berurutan.
PHASER_PROBE_JS = r"""
const gs = [];
for (const g of (window.Phaser ? Phaser.GAMES : [])) {
    try {
        const st = g.state.states[g.state.current];
        if (st && st.core && typeof st.core.record_keydown_time === 'function') gs.push({g: g, st: st});
    } catch (e) {}
}
if (!gs.length) return null;
const pick = gs[gs.length - 1];
if (pick.g.paused) { try { pick.g.paused = false; } catch (e) {} }
const c = pick.st.core;
if (c.has_ended) return {fed: false, ended: true};
const want = arg;
if (want) {
    c.record_keydown_time(want);
    return {fed: true, chr: want, idx: c.cur_char_index, word: c.cur_word_index,
            ended: !!c.has_ended};
}
// kumpulkan kandidat: huruf pertama tiap kata yang belum selesai
const cands = [];
let words_ok = false;
try {
    if (c.words && typeof c.words.length === 'number') {
        words_ok = true;
        for (const w of c.words) {
            if (!w || !w.char_list || w.completed) continue;
            const ch = w.char_list[w.index || 0] || w.char_list[0];
            if (ch && cands.indexOf(ch) < 0) cands.push(ch);
        }
    }
} catch (e) {}
if (!cands.length && c.cur_char) cands.push(c.cur_char.chr);
return {fed: false, cands: cands.slice(0, 8), words_ok: words_ok, idx: c.cur_char_index,
        word: c.cur_word_index, ended: false};
"""

# cek state tanpa memberi ketikan
PHASER_CHECK_JS = r"""
const gs = [];
for (const g of (window.Phaser ? Phaser.GAMES : [])) {
    try {
        const st = g.state.states[g.state.current];
        if (st && st.core) gs.push(st.core);
    } catch (e) {}
}
if (!gs.length) return null;
const c = gs[gs.length - 1];
return {idx: c.cur_char_index, word: c.cur_word_index, ended: !!c.has_ended};
"""

_phaser_cooldown = {"until": 0.0}
_phaser_freeze = {"url": "", "count": 0, "clicked": False}


def _premium_modal_action():
    """Cek modal premium di semua frame edclub. Kalau tombol X ada ->
    klik mouse ASLI dan return 'clicked' (edclub lalu lanjut ke lesson
    berikutnya sendiri; terbukti live di 2968 & 3094). Kalau modal ada
    tanpa X -> return dict pm ({zombie:true} dll). Kalau tidak ada
    modal -> None. Catatan: modal X cuma muncul ~3 detik di awal level,
    lalu menghilang sendiri dan game jadi beku - jadi ini harus
    dipanggil SERING di awal level (watch window)."""
    for fr in _edclub_frames():
        pm = run_js(PREMIUM_MODAL_JS, fr)
        if pm and pm.get("x") is not None:
            try:
                _tandai_klik_bot()
                PAGE.mouse.click(pm["x"], pm["y"])
                print("[Premium] tombol X modal diklik - "
                      "lanjut lesson berikutnya")
                return "clicked"
            except Exception:
                pass
        if pm:
            return pm
    return None


def _phaser_try_advance():
    """Game beku berulang kali -> lewati level game via tombol
    lanjut (klik mouse asli). Game premium/bermasalah tidak boleh
    mengunci progres selamanya (user: 'satu klik langsung ke lesson
    berikutnya')."""
    try:
        loc = PAGE.locator(".navbar-continue, a.navbar-continue, "
                           "[data-testid='lesson-next-btn'], .a-btn.next, "
                           ".btn-continue, .continue-button, .next-button") \
            .first
        if loc.count() and loc.is_visible():
            loc.click(timeout=2000)
            print("[Minigame/Phaser] game beku - level dilewati via tombol lanjut")
            _phaser_freeze["count"] = 0
            _phaser_freeze["clicked"] = False
            return True
    except Exception:
        pass
    # Fallback: tombol berteks lanjut (di luar kontainer premium/iframe,
    # titik klik terverifikasi elementFromPoint) -> klik mouse asli.
    for fr in _edclub_frames():
        pt = run_js(r"""
const NX = ['next','continue','lanjut','mulai','selesai','skip','got it','ok'];
for (const el of document.querySelectorAll('button, a, [role="button"]')) {
    if (!(el.offsetWidth || el.offsetHeight)) continue;
    const txt = (el.innerText || '').trim().toLowerCase();
    if (!txt || txt.length > 14 || !NX.includes(txt)) continue;
    try { if (el.closest('[class*="premium" i],[class*="upsell" i],[class*="paywall" i],[class*="checkout" i],[class*="stripe" i]')) continue; } catch (e) {}
    const r = el.getBoundingClientRect();
    if (r.width < 25 || r.height < 12) continue;
    const cx = r.left + r.width/2, cy = r.top + r.height/2;
    const top = document.elementFromPoint(cx, cy);
    if (!top || (top !== el && !el.contains(top) && !top.contains(el))) continue;
    if (el.querySelector('iframe') || el.closest('iframe')) continue;
    return {x: cx, y: cy};
}
return null;
""", fr)
        if pt:
            try:
                _tandai_klik_bot()
                PAGE.mouse.click(pt["x"], pt["y"])
                print("[Minigame/Phaser] game beku - level dilewati "
                      "via tombol berteks lanjut")
                _phaser_freeze["count"] = 0
                _phaser_freeze["clicked"] = False
                return True
            except Exception:
                pass
    return False


def handle_phaser_minigame():
    global last_action_time
    if time.time() < _phaser_cooldown["until"]:
        return False
    # Level premium: modal menutupi canvas, game mengabaikan ketikan
    # (cur_char.valid=false). Modal+X muncul singkat di awal - klik X.
    if _premium_modal_action() == "clicked":
        last_action_time = time.time()
        return True
    for fr in all_frames():
        res = run_js(PHASER_FEED_JS, fr)
        if res is None or not res.get("fed"):
            continue
        print(f"[Minigame/Phaser] {frame_label(fr)}: memberi ketikan via core API...")
        fed_total = 1
        stalled = 0
        probed = False
        last_idx = res.get("idx")
        while fed_total < 150:
            time.sleep(random.uniform(0.05, 0.11))
            res = run_js(PHASER_FEED_JS, fr)
            if not res or not res.get("fed"):
                break
            idx = res.get("idx")
            if idx == last_idx:
                stalled += 1
                # modal premium bisa muncul kapan saja & mematikan game -
                # cek X di tiap stall (modal X hanya hidup ~3 dtk)
                if stalled >= 2 and _premium_modal_action() == "clicked":
                    last_action_time = time.time()
                    return True
                if stalled >= 4 and not probed:
                    # cur_char tidak diterima -> game multi-kata (pilih bebas).
                    # Coba kandidat huruf pertama dari tiap kata yang belum
                    # selesai. guard: core.words bisa bukan array di sebagian
                    # game (2968) - kandidat jadi sampah, jangan percaya.
                    probed = True
                    try:
                        info = fr.evaluate(
                            "(arg) => {" + PHASER_PROBE_JS + "}", None)
                    except Exception:
                        info = None
                    cands = (info or {}).get("cands") or []
                    words_ok = bool((info or {}).get("words_ok"))
                    if not words_ok:
                        print("[Minigame/Phaser] struktur words tidak dikenal "
                              "(bukan array char_list) - probe dilewati")
                        cands = []
                    else:
                        print(f"[Minigame/Phaser] kandidat multi-kata: {cands!r}")
                    for cand in cands:
                        try:
                            fr.evaluate(
                                "(arg) => {" + PHASER_PROBE_JS + "}", cand)
                        except Exception:
                            continue
                        time.sleep(0.3)
                        chk = run_js(PHASER_CHECK_JS, fr)
                        newidx = (chk or {}).get("idx")
                        if newidx is not None and newidx != idx:
                            print(f"[Minigame/Phaser] kata ditemukan via {cand!r}")
                            stalled = 0
                            last_idx = newidx
                            break
                if stalled >= 8:
                    # beku. Dua kemungkinan: (a) game menunggu interaksi
                    # start (klik canvas) - coba sekali per URL; (b) game
                    # benar-benar bermasalah - setelah 3x beku, lewati level.
                    url_now = PAGE.url
                    if _phaser_freeze["url"] != url_now:
                        _phaser_freeze["url"] = url_now
                        _phaser_freeze["count"] = 0
                        _phaser_freeze["clicked"] = False
                    _phaser_freeze["count"] += 1
                    if not _phaser_freeze["clicked"]:
                        _phaser_freeze["clicked"] = True
                        try:
                            cv = fr.locator("canvas").first
                            if cv.count():
                                cv.click(timeout=1500)
                                print("[Minigame/Phaser] coba klik canvas "
                                      "(start game)")
                                time.sleep(1.5)
                                chk = run_js(PHASER_CHECK_JS, fr)
                                if (chk or {}).get("idx") != last_idx:
                                    stalled = 0
                                    continue
                        except Exception:
                            pass
                    if _phaser_freeze["count"] >= 2:
                        # modal premium bisa menutup canvas - cek X
                        if _premium_modal_action() == "clicked":
                            last_action_time = time.time()
                            return True
                    if _phaser_freeze["count"] >= 3:
                        if _phaser_try_advance():
                            last_action_time = time.time()
                            return True
                        if _skip_to_next_lesson("minigame beku"):
                            last_action_time = time.time()
                            return True
                    print("[Minigame/Phaser] indeks tidak maju, jeda 6 detik "
                          f"(beku #{_phaser_freeze['count']})")
                    _phaser_cooldown["until"] = time.time() + 6
                    break
            else:
                stalled = 0
                last_idx = idx
            fed_total += 1
            last_action_time = time.time()
        stats["phaser"] += fed_total
        print(f"[Minigame/Phaser] {fed_total} karakter dikirim")
        last_action_time = time.time()
        time.sleep(0.4)
        return True
    return False


# ---------------------------------------------------------------------------
# Level "hold key" (instruksi murni, tanpa teks lesson)
# ---------------------------------------------------------------------------

HOLD_JS = r"""
const txt = (document.body ? document.body.innerText : '').toLowerCase();
if (!txt || txt.length > 400) return null;
const pats = [
    /press and hold (?:the )?(?:left |right )?([a-z]+(?: [a-z]+)?)/,
    /hold (?:down )?(?:the )?(?:left |right )?([a-z]+(?: [a-z]+)?)/,
    /tahan (?:tombol )?([a-z]+)/
];
for (const p of pats) {
    const m = txt.match(p);
    if (m) return {key: m[1], raw: m[0]};
}
return null;
"""

HOLD_KEY_MAP = {
    "space": " ", "space bar": " ", "spacebar": " ", "spasi": " ",
    "bar": " ", "shift": "Shift", "ctrl": "Control", "control": "Control", "alt": "Alt",
    "enter": "Enter", "return": "Enter", "tab": "Tab", "esc": "Escape", "escape": "Escape",
    "backspace": "Backspace", "delete": "Delete", "up": "ArrowUp", "down": "ArrowDown",
    "left": "ArrowLeft", "right": "ArrowRight",
}

last_hold_raw = ""
hold_attempts = 0


def map_hold_key(k):
    k = (k or "").strip().lower()
    if k in HOLD_KEY_MAP:
        return HOLD_KEY_MAP[k]
    if len(k) == 1 and k.isalpha():
        return k
    return None


def try_hold_level():
    global last_hold_raw, hold_attempts, last_action_time
    for fr in all_frames():
        instr = run_js(HOLD_JS, fr)
        if not instr:
            continue
        key = map_hold_key(instr.get("key"))
        if not key:
            continue
        raw = instr.get("raw") or key
        if raw == last_hold_raw and hold_attempts >= 4:
            return False
        if raw != last_hold_raw:
            last_hold_raw = raw
            hold_attempts = 0
        hold_attempts += 1
        focus_frame(fr)
        duration = min(1.5 * hold_attempts, 8.0)
        print(f"[Hold] instruksi '{raw}' -> menahan {duration:.1f}s (coba {hold_attempts})")
        try:
            PAGE.keyboard.down(key)
            time.sleep(duration)
        finally:
            try:
                PAGE.keyboard.up(key)
            except Exception:
                pass
        stats["hold"] += 1
        last_action_time = time.time()
        return True
    return False


# ---------------------------------------------------------------------------
# Keyboard layar (klik tombol highlight)
# ---------------------------------------------------------------------------

SCREENKEY_JS = r"""
const sels = ['[class*="key"][class*="highlight"]', '[class*="key"][class*="active"]',
              '.key.highlight', '.keyboard .next'];
for (const sel of sels) {
    for (const el of document.querySelectorAll(sel)) {
        if (!(el.offsetWidth || el.offsetHeight)) continue;
        const t = (el.innerText || el.textContent || '').trim().slice(0, 4);
        // Wajib berlabel: elemen "aktif" Tanpa teks bukan tombol keyboard -
        // pernah diklik dan menavigasi bot ke halaman daftar level.
        if (!t || t.length > 2) continue;
        try { el.click(); } catch (e) {}
        return {key: t, sel: sel};
    }
}
return null;
"""


_scrkey = {"key": "", "count": 0, "until": 0.0}


def click_screen_keyboard():
    global last_action_time
    if time.time() < _scrkey["until"]:
        return False
    for fr in all_frames():
        hit = run_js(SCREENKEY_JS, fr)
        if hit:
            k = hit.get("key") or ""
            if k == _scrkey["key"]:
                _scrkey["count"] += 1
                if _scrkey["count"] >= 4:
                    # klik berulang tanpa kemajuan (klik JS tidak selalu
                    # diterima) - beri jeda supaya tidak spam
                    _scrkey["until"] = time.time() + 10
                    _scrkey["count"] = 0
                    print("[Keyboard-layar] klik tanpa efek, jeda 10 detik")
                    return False
            else:
                _scrkey["key"] = k
                _scrkey["count"] = 1
            print(f"[Keyboard-layar] klik '{k}' ({hit.get('sel')})")
            stats["uikey"] += 1
            last_action_time = time.time()
            return True
    return False


# ---------------------------------------------------------------------------
# Level video: klik play (CDP click = user gesture valid), 16x, seek akhir
# ---------------------------------------------------------------------------

VIDEO_STATE_JS = r"""
const v = document.querySelector('video');
if (!v) return null;
return {paused: !!(v.ended || v.paused), dur: v.duration || 0, cur: v.currentTime || 0};
"""

VIDEO_SKIP_JS = r"""
const v = document.querySelector('video');
if (!v) return false;
try { v.muted = true; } catch (e) {}
// cukup Lompat ke akhir + play supaya event 'ended' menyala - tidak perlu
// playbackRate 16x (skip instan, tanpa percepatan yang menonta video)
try { const p = v.play(); if (p && p.catch) p.catch(() => {}); } catch (e) {}
try {
    if (v.duration && isFinite(v.duration) && v.duration > 2) {
        v.currentTime = Math.max(0, v.duration - 0.4);
    }
} catch (e) {}
return true;
"""


def handle_video_level():
    global last_action_time
    for fr in all_frames():
        info = run_js(VIDEO_STATE_JS, fr)
        if not info:
            continue
        if info.get("paused"):
            try:
                btn = fr.locator(".vjs-big-play-button").first
                _tandai_klik_bot(fr)
                btn.click(timeout=2000)
                time.sleep(0.8)
            except Exception:
                pass
        run_js(VIDEO_SKIP_JS, fr)
        stats["video"] += 1
        last_action_time = time.time()
        print(f"[Video] {frame_label(fr)}: dilompat ke akhir")
        time.sleep(0.5)
        return True
    return False


# ---------------------------------------------------------------------------
# Langkah intro "Type the f key" / "Press Enter"
# ---------------------------------------------------------------------------

INTRO_JS = r"""
for (const el of document.querySelectorAll('div, span, p')) {
    const t = (el.innerText || '').trim();
    if (!t || t.length > 90 || !el.offsetWidth) continue;
    const m = t.match(/^type the\s+([\s\S]+?)\s+key/i);
    if (m) return {type: 'type', key: m[1].trim().toLowerCase()};
    if (/^press enter/i.test(t)) return {type: 'enter'};
}
return null;
"""

INTRO_KEY_MAP = {"space": " ", "space bar": " ", "spacebar": " ", "spasi": " ",
                 "bar": " ", "enter": "Enter"}

_intro_sig = None
_intro_attempts = 0
_intro_flow = False   # True = alur intro berjalan (f->j->d->k di level yang sama)


def _click_labeled_key(key):
    """Klik mouse SUNGGUHAN tombol keyboard layar yang BERLABEL huruf
    target (mis. tombol 'f'). Input valid utk user sentuh. Dipakai HANYA
    sebagai cadangan coba-4 (ketikan CDP beberapa kali tidak masuk)."""
    if not key or len(key) != 1:
        return False
    for fr in all_frames():
        try:
            locs = fr.locator('[class*="key"], .keyboard *')
            for i in range(min(locs.count(), 120)):
                el = locs.nth(i)
                txt = (el.inner_text(timeout=300) or "").strip()
                if txt == key:
                    el.click(timeout=1200)
                    print(f"[Intro] klik tombol layar {key!r} (cadangan)")
                    return True
        except Exception:
            continue
    return False


def handle_intro_steps():
    global _intro_sig, _intro_attempts, last_action_time, _intro_flow
    if _intro_attempts >= 8:
        return False
    for fr in all_frames():
        res = run_js(INTRO_JS, fr)
        if not res:
            continue
        key = res.get("key")
        if res["type"] == "type":
            key = INTRO_KEY_MAP.get(key, key)
            if not key or len(key) > 12:
                continue
        else:
            key = "Enter"
        sig = (res["type"], key)
        if sig != _intro_sig:
            _intro_sig = sig
            _intro_attempts = 0
        _intro_attempts += 1
        # pola tutorial (terbukti): tunggu layar stabil dulu sebelum menekan
        # (jendela mati transisi; menekan terlalu dini = keystroke hilang).
        # Layar pertama di sebuah level: jendela matinya panjang (habis load
        # level) -> 2x baca @0.25s. Layar berikutnya dalam alur intro yang
        # sama (f->j->d->k): engine sudah hidup -> 2x baca @0.10s, tekanan
        # berikutnya praktis instan (pola user "fj" cepat).
        wait = 0.10 if _intro_flow else 0.25
        stable = 0
        for _ in range(10):
            time.sleep(wait)
            now = run_js(INTRO_JS, fr)
            same = bool(now) and (now.get("key"), now.get("type")) == (res.get("key"), res.get("type"))
            if same:
                stable += 1
            else:
                if now:
                    res = now
                stable = 0
            if stable >= 2:
                break
        focus_frame(fr)
        print(f"[Intro] instruksi: {res['type']} {key!r} (coba {_intro_attempts})")
        # satu tekanan bersih. Tekanan ekstra saat layar sudah pindah =
        # tombol salah di layar berikutnya (flash merah).
        if _intro_attempts >= 4 and _intro_attempts % 2 == 0:
            _click_labeled_key(key)
        else:
            try:
                if key == "Enter":
                    PAGE.keyboard.press("Enter")
                else:
                    PAGE.keyboard.type(key)
            except Exception:
                return False
        # tunggu instruksi berganti secepat mungkin (poll 80 ms) supaya
        # f->j praktis instan seperti tekanan manusia beruntun
        for _ in range(30):
            time.sleep(0.08)
            now = run_js(INTRO_JS, fr)
            if not now or (now.get("key"), now.get("type")) != (res.get("key"), res.get("type")):
                stats["intro"] += 1
                _intro_flow = True   # alur intro hidup: layar berikutnya cepat
                last_action_time = time.time()
                return True
        stats["intro"] += 1
        last_action_time = time.time()
        return True
    _intro_flow = False   # tidak ada instruksi intro -> alur intro selesai
    return False


# ---------------------------------------------------------------------------
# Fallback OCR canvas (non-Phaser)
# ---------------------------------------------------------------------------

last_ocr_time = 0.0


def ocr_words_from_frame(frame):
    try:
        png = frame.locator("body").first.screenshot(timeout=3000)
        img = Image.open(io.BytesIO(png)).convert("RGB")
        w, h = img.size
        result = asyncio.run(winocr.recognize_pil(img))
        words = []
        try:
            for line in result.lines:
                for word in line.words:
                    t = (word.text or "").strip().lower()
                    if not re.fullmatch(r"[a-z]{2,12}", t) or t in UI_WORDS:
                        continue
                    r = word.bounding_rect
                    cy = (r.y + r.height / 2) / max(h, 1)
                    if 0.15 < cy < 0.90:
                        words.append(t)
        except Exception:
            for t in result.text.split():
                t = t.strip().lower().strip(".,!?;:'\"()")
                if re.fullmatch(r"[a-z]{2,12}", t) and t not in UI_WORDS:
                    words.append(t)
        return words
    except Exception:
        return []


def try_ocr_minigame(meta):
    global last_ocr_time, last_action_time
    if not OCR_AVAILABLE or not meta.get("canvas_frames"):
        return False
    now = time.time()
    if now - last_ocr_time < OCR_MIN_INTERVAL:
        return False
    last_ocr_time = now
    for fr in meta["canvas_frames"]:
        words = ocr_words_from_frame(fr)
        if not words:
            continue
        focus_frame(fr)
        target = words[0]
        print(f"[Minigame/OCR] kata: {words[:5]} -> mengetik {target!r}")
        if not type_chars(target):
            return False
        stats["ocr"] += 1
        last_action_time = time.time()
        return True
    return False


# ---------------------------------------------------------------------------
# Debug dump
# ---------------------------------------------------------------------------

def dump_debug_info():
    try:
        print("---- DEBUG (tiap frame) ----")
        for fr in all_frames():
            info = run_js(r"""
                return {
                    url: location.href.slice(0, 100),
                    canvases: document.querySelectorAll('canvas').length,
                    core: !!window.core,
                    texts: (function(){
                        const out = [];
                        for (const s of document.querySelectorAll('span, div, p')) {
                            if (out.length >= 8) break;
                            const t = (s.innerText || '').trim();
                            if (t && t.length < 30 && s.children.length === 0 && s.offsetWidth > 0)
                                out.push(t.slice(0, 30));
                        }
                        return out;
                    })()
                };
            """, fr)
            if info:
                print(f"DEBUG {frame_label(fr)}: core={info.get('core')} "
                      f"canvas={info.get('canvases')} url={info.get('url')}")
                for t in info.get("texts", []):
                    print(f"DEBUG   dom: {t}")
        print("---------------------------")
    except Exception as ex:
        print(f"DEBUG gagal: {ex}")


# ---------------------------------------------------------------------------
# Recovery: halaman edclub mati/kosong -> buka tab baru + klik pelajaran aktif
# (ditemukan: daftar pelajaran punya box-container.is_unlocked tanpa
# has_progress = pelajaran yang harus dikerjakan berikutnya)
# ---------------------------------------------------------------------------

LIST_URL = "https://www.edclub.com/sportal/program-3.game"
_last_recovery = 0.0
# Berapa kali lesson URL ini sudah di-recovery (guard anti loop level rusak)
_recovery_counts = {}


def _switch_to_playable_tab():
    """Kalau ada tab edclub lain yang jelas punya pekerjaan (token _clr /
    boxed aktif) sedangkan tab sekarang sunyi - pindah ke sana.
    Return True kalau pindah."""
    global PAGE, last_url, last_action_time
    try:
        pages = [pg for pg in browser.contexts[0].pages
                 if pg is not PAGE]
    except Exception:
        return False
    best, best_score = None, 0
    for pg in pages:
        try:
            url = _real_url(pg)
            if not _is_edclub_url(url):
                continue
            if ".play" not in url:
                continue
            info = pg.evaluate("() => {" + PLAYABLE_CHECK_JS + "}")
            s = 0
            if info:
                if info.get("clr"):
                    s += 5
                elif info.get("boxed"):
                    s += 3
                if info.get("done"):
                    s -= 8
        except Exception:
            continue
        if s > best_score:
            best, best_score = pg, s
    if best is not None:
        print(f"[TAB] pindah ke tab lain yang ada kerjaannya: "
              f"{best.url.split('/')[-1]}")
        PAGE = best
        last_url = ""
        last_action_time = time.time()
        return True
    return False


def recover_and_restart_lesson():
    """Pulihkan halaman macet/kosong. UTAMA: RELOAD TAB YANG SAMA -
    tab baru hanya kalau reload gagal (tab benar2 mati) atau URL lesson
    tidak diketahui. (Dulu selalu tab baru: mengganggu user dan pernah
    bertabrakan dengan refresh manual user.)"""
    global PAGE, last_typed_text, last_url, _last_recovery, last_action_time
    global _std_last_rem, _std_attempts
    _last_recovery = time.time()
    target = last_url if (last_url and ".play" in last_url) else None

    if target:
        n = _recovery_counts.get(target, 0) + 1
        _recovery_counts[target] = n
        if n >= 3:
            # Lesson ini sudah berkali-kali recovery tetap mati = level
            # rusak -> pelajaran berikutnya sesuai urutan daftar (nomor
            # URL edclub tidak berurutan, jangan hitung N+1).
            if _skip_to_next_lesson("recovery berulang, level rusak"):
                return True
            return False
        try:
            PAGE.reload(timeout=25000)
            print(f"[RECOVERY] reload tab yang sama: "
                  f"{target.split('/')[-1]}")
            last_typed_text = ""
            _std_last_rem = None    # biar handle_standard mau ketik ulang
            _std_attempts = 0
            last_url = PAGE.url
            last_action_time = time.time()
            return True
        except Exception as e:
            print(f"[RECOVERY] reload gagal ({str(e)[:60]}) - coba tab baru")

    print("[RECOVERY] Halaman macet/kosong, membuka tab baru...")
    try:
        newpg = PAGE.context.new_page()
    except Exception as e:
        print(f"[RECOVERY] gagal bikin tab: {str(e)[:80]}")
        return False

    if target:
        try:
            newpg.goto(target, timeout=25000)
            print(f"[RECOVERY] muat ulang lesson yang sama: {target.split('/')[-1]}")
        except Exception as e:
            print(f"[RECOVERY] gagal muat ulang: {str(e)[:80]}")
            try:
                newpg.close()
            except Exception:
                pass
            return False
    else:
        # Rentang aktif: kembali ke level sesi (max start vs yang sudah
        # dilihat), bukan baris pertama di daftar (= level terdepan akun,
        # ). Fallback: baris pertama seperti biasa.
        lanjut_lvl = 0
        try:
            if RENTANG_SIAP and (LEVEL_START > 1 or LEVEL_END):
                lanjut_lvl = max(LEVEL_START, _rentang_max_seen)
        except Exception:
            lanjut_lvl = 0
        if lanjut_lvl and str(lanjut_lvl) in _level_map:
            try:
                newpg.goto(_level_map[str(lanjut_lvl)], timeout=25000)
                print(f"[RECOVERY] kembali ke level {lanjut_lvl} sesi ini")
                _finish_recovery(newpg)
                return True
            except Exception as e:
                print(f"[RECOVERY] gagal kembali ke level {lanjut_lvl} "
                      f"({str(e)[:60]}) - coba daftar")
                try:
                    newpg.close()
                    newpg = PAGE.context.new_page()
                except Exception:
                    return False
        try:
            newpg.goto(LIST_URL, timeout=20000)
        except Exception as e:
            print(f"[RECOVERY] gagal buka daftar: {str(e)[:80]}")
            try:
                newpg.close()
            except Exception:
                pass
            return False
        try:
            newpg.wait_for_selector("div.lsn_name", timeout=15000)
        except Exception:
            pass
        clicked = None
        try:
            clicked = newpg.evaluate("""
            () => {
                const rows = document.querySelectorAll('div.box-container.is_unlocked:not(.has_progress)');
                for (const r of rows) {
                    const nm = r.querySelector('div.lsn_name');
                    if (nm) { nm.click(); return (nm.innerText||'').trim(); }
                }
                const any = document.querySelector('div.lsn_name');
                if (any) { any.click(); return '(pertama) ' + (any.innerText||'').trim(); }
                return null;
            }
            """)
        except Exception:
            pass
        if not clicked:
            print("[RECOVERY] baris pelajaran tidak ditemukan")
            try:
                newpg.close()
            except Exception:
                pass
            return False
        print(f"[RECOVERY] membuka pelajaran: {clicked}")

    _finish_recovery(newpg)
    return True


def _finish_recovery(newpg):
    """ tunggu tab recovery siap, jadikan tab utama, tutup tab lama """
    global PAGE, last_typed_text, last_url, last_action_time
    for _ in range(15):
        try:
            newpg.wait_for_timeout(1000)
        except Exception:
            time.sleep(1)
        if ".play" in newpg.url:
            break
    try:
        old = PAGE
        PAGE = newpg
        if old is not newpg:
            old.close()
    except Exception:
        pass
    last_typed_text = ""
    last_url = PAGE.url
    last_action_time = time.time()
    return True


_hijack_counts = {}
_broken_lessons = set()


def _lesson_id(url):
    m = re.search(r"/program-(\d+)/(\d+)\.play", url or "")
    return int(m.group(2)) if m else None


_level_label_cache = {}


# Peta nomor level asli -> URL edclub. Id URL adalah id konten kursus
# (sama untuk semua akun), tapi tidak linier (652 -> 8830, 685 -> 52748)
# jadi tidak bisa dihitung rumus. Peta bawaan 685 level tertanam di
# level_data.py (bawaan exe); level_map.json milik user menimpa nilai
# bawaan kalau ada (mis. kursus/program berbeda).
import level_data as _level_data
_LEVEL_MAP_FILE = os.path.join(_BASE, "level_map.json")
_level_map = {str(n): f"https://www.edclub.com/sportal/program-3/{i}.play"
             for n, i in _level_data.PETA.items()}


def _level_map_muat():
    try:
        with open(_LEVEL_MAP_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _level_map.update({str(k): v for k, v in data.items()})
    except Exception:
        pass


def _level_map_catat(nomor, url):
    """Simpan asosiasi level -> URL (mis. '87' -> '...192.play')."""
    if not nomor or not url or ".play" not in url:
        return
    k = str(nomor)
    if _level_map.get(k) == url:
        return
    _level_map[k] = url
    try:
        with open(_LEVEL_MAP_FILE, "w", encoding="utf-8") as f:
            json.dump(_level_map, f, indent=1, sort_keys=True)
    except Exception:
        pass


_level_map_muat()

# Balik peta: id URL -> nomor level (untuk indikator GUI instan).
_url_ke_level = {}
for _n, _u in _level_map.items():
    try:
        _url_ke_level[int(_u.rsplit("/", 1)[1].split(".")[0])] = int(_n)
    except Exception:
        pass


def url_ke_level(url):
    """Nomor level dari URL .play via peta terbalik (pasti & instan,
    tidak menunggu teks halaman termuat)."""
    try:
        m = re.search(r"/program-\d+/(\d+)\.play", url or "")
        if m:
            return _url_ke_level.get(int(m.group(1)))
    except Exception:
        pass
    return None


def _baca_unlock_set():
    """Set nomor level yang TERKUNCI/TERBUKA: kumpulkan nomor lesson yang
    punya class 'is_unlocked' di daftar lesson. Akun baru/logout = hanya
    level 1. None = daftar tidak terbaca."""
    if browser is None:
        return None
    pg = None
    try:
        pg = browser.contexts[0].new_page()
        pg.goto(LIST_URL, timeout=30000)
        pg.wait_for_selector("div.box-container", timeout=15000)
        time.sleep(1.0)
        data = pg.evaluate(r"""() => {
            const rows = [...document.querySelectorAll('div.box-container')];
            const out = [];
            for (const r of rows) {
                if (!(r.className || '').includes('is_unlocked')) continue;
                const m = (r.getAttribute('aria-label') || '')
                    .match(/Lesson (\d+)/);
                if (m) out.push(parseInt(m[1], 10));
            }
            return out;
        }""")
        return set(data or [])
    except Exception:
        return None
    finally:
        try:
            if pg is not None:
                pg.close()
        except Exception:
            pass


# Dialog 'level terkunci' bot<->GUI: bot menunggu jawaban user.
LEVEL_TANYA = {"aktif": False, "start": 0, "fallback": 0, "jawab": "", "event": None}
_rentang_validasi_done = False


def _rentang_validasi_step():
    """Validasi NON-BLOKIR: LEVEL_START harus level TERBUKA di akun
    (terkunci = halaman kosong, bot akan thrash). Dipanggil tiap iterasi
    loop utama SETELAH gerbang login (live 00:04: validasi lama jalan
    SEBELUM patroli login pertama -> daftar logout hanya L1 terbuka ->
    '662 terkunci' padahal user bahkan belum login, dan wait 300 dtk
    membekukan seluruh loop: popup login & tanya rentang tak pernah
    muncul). Return False = user memilih stop."""
    global LEVEL_START, _unlock_set, _rentang_validasi_done
    if _rentang_validasi_done or LEVEL_START <= 1:
        _rentang_validasi_done = True
        return True
    # Tunda selama status login belum pasti / belum login: daftar level
    # versi logout selalu 'hanya level 1' - memvalidasi sekarang hanya
    # menghasilkan popup terkunci palsu. Setelah login, _rentang_cek
    # mengantar ke level awal; level benar2 terkunci tetap ditangani
    # runtime (deteksi halaman kosong).
    if PERLU_LOGIN or not LOGIN_DICEK:
        return True
    try:
        if _profil_login() == "out":
            _rentang_validasi_done = True
            return True
    except Exception:
        pass
    # user sudah membuka lesson sendiri = kerjakan itu, tanpa validasi/
    # lompatan (level terkunci yang dibuka sendiri oleh user adalah urusan
    # user - edclub yang mengizinkan/menolaknya, bukan bot)
    try:
        if ".play" in (_real_url(PAGE) or ""):
            _rentang_validasi_done = True
            return True
    except Exception:
        pass
    if _unlock_set is None:
        _unlock_set = _baca_unlock_set()
    if _unlock_set is None or LEVEL_START in _unlock_set:
        _rentang_validasi_done = True
        return True   # tidak bisa dibaca / memang terbuka: lanjut saja
    fallback = max(_unlock_set) if _unlock_set else 1
    print(f"[RENTANG] level {LEVEL_START} masih TERKUNCI di akun ini - "
          f"terbuka sampai level {fallback}.")
    ev = threading.Event()
    LEVEL_TANYA.update(aktif=True, start=LEVEL_START, fallback=fallback,
                       jawab="", event=ev)
    # tunggu bertahap: jawaban GUI, STOP, atau 300 dtk (timeout = mulai)
    batas = time.time() + 300
    while not ev.is_set() and not STOP and time.time() < batas:
        ev.wait(timeout=1.0)
    LEVEL_TANYA["aktif"] = False
    jawab = LEVEL_TANYA["jawab"] or "mulai"   # timeout = lanjut dari fallback
    _rentang_validasi_done = True
    if jawab == "stop":
        print("[RENTANG] dibatalkan user - bot tidak jalan.")
        return False
    LEVEL_START = fallback
    print(f"[RENTANG] mulai dari level {LEVEL_START} "
          "(posisi terdepan akun).")
    return True


def _goto_level_url(nomor):
    """Buka lesson nomor N langsung dari peta (level_map.json)."""
    url = _level_map.get(str(nomor))
    if not url:
        return False
    try:
        PAGE.goto(url, timeout=25000)
        return True
    except Exception:
        return False


def bangun_peta_level():
    """Bangun peta level -> URL lengkap (1..685) dengan membuka daftar
    lesson lalu menklik tiap baris dan merekam URL .play-nya (~1.3 dtk/
    level, sekali per akun). Baris daftar terverifikasi: aria-label
    'Lesson N' sesuai urutan. Jalan di tab terpisah supaya PAGE aktif
    tidak terganggu."""
    if browser is None:
        print("[PETA] belum terhubung ke browser.")
        return 0
    pg = None
    baru = 0
    try:
        pg = browser.contexts[0].new_page()
        pg.goto(LIST_URL, timeout=30000)
        pg.wait_for_selector("div.box-container", timeout=15000)
        total = pg.evaluate(
            "() => document.querySelectorAll('div.box-container').length") or 0
        if not total:
            print("[PETA] daftar lesson tidak terbaca.")
            return 0
        print(f"[PETA] membangun peta {total} level "
              f"(estimasi {total * 1.4 / 60:.0f} menit, jangan tutup bot)...")
        for i in range(total):
            while PAUSED and not STOP:
                time.sleep(0.3)
            if STOP:
                print(f"[PETA] dihentikan di level {i + 1} "
                      f"(bisa dilanjutkan lain waktu).")
                break
            try:
                try:  # modal premium di tab peta -> tutup dulu
                    x = pg.locator(".edmodal-x")
                    if x.count():
                        x.first.click(timeout=800)
                        time.sleep(0.3)
                except Exception:
                    pass
                lbl = pg.evaluate(
                    "(i)=>{const r=[...document.querySelectorAll"
                    "('div.box-container')][i];"
                    "return r ? (r.getAttribute('aria-label')||'') : '';}", i)
                m = re.match(r"Lesson\s+(\d+)", lbl or "")
                nomor = int(m.group(1)) if m else i + 1
                if str(nomor) in _level_map:
                    continue   # sudah terpetakan (resume cepat tanpa klik)
                pg.evaluate(
                    "(i)=>{const r=[...document.querySelectorAll"
                    "('div.box-container')][i]; if(r) r.click();}", i)
                url = None
                for fase in range(40):
                    time.sleep(0.1)
                    u = pg.evaluate("() => location.href")
                    if u and ".play" in u:
                        url = u
                        break
                    if fase == 12:
                        # lesson terkunci: edclub menampilkan modal 'Are you
                        # sure? ... jumping ahead' dengan tombol Continue -
                        # klik lanjut supaya navigasi tetap terjadi .
                        pg.evaluate("""() => {
                            const t = [...document.querySelectorAll(
                                'button, .btn, [role=button]')];
                            const b = t.find(x =>
                                /continue|lanjut/i.test(x.textContent || '')
                                && x.offsetParent !== null);
                            if (b) b.click();
                        }""")
                if url and _level_map.get(str(nomor)) != url:
                    _level_map_catat(nomor, url)
                    baru += 1
                # go_back hanya kalau memang navigasi ke .play terjadi;
                # baris yang tidak bisa diklik (mis. bagian khusus akhir
                # daftar) tidak menavigasi -> go_back dari daftar justru
                # membawa tab ke about:blank dan builder nyangkut .
                if url:
                    pg.go_back(timeout=15000)
                    pg.wait_for_selector("div.box-container", timeout=15000)
                if (i + 1) % 25 == 0:
                    print(f"[PETA] {i + 1}/{total} level terpetakan...")
            except Exception:
                pulih = False
                for _ in range(3):
                    try:
                        pg.goto(LIST_URL, timeout=30000)
                        pg.wait_for_selector("div.box-container",
                                            timeout=15000)
                        pulih = True
                        break
                    except Exception:
                        time.sleep(2)
                        try:   # tab bisa mati -> tab baru
                            pg.close()
                        except Exception:
                            pass
                        pg = browser.contexts[0].new_page()
                if not pulih:
                    print("[PETA] daftar tidak bisa dibuka lagi - berhenti "
                          "(lanjutkan lain waktu, sudah terpetakan "
                          f"{len(_level_map)}).")
                    break
        print(f"[PETA] selesai: +{baru} baru, total {len(_level_map)} "
              f"level terpetakan (level_map.json).")
    finally:
        try:
            if pg is not None:
                pg.close()
        except Exception:
            pass
    return baru


def _level_label():
    """Nomor level ASLI (mis. 'L87') dari teks halaman. Nomor URL edclub
    adalah id konten (bukan linear - setelah 651 langsung 8830), jadi
    indikator tidak boleh memakai rumus URL. Halaman menampilkan
    'Lesson 87: ...'."""
    try:
        url = PAGE.url
    except Exception:
        return ""
    if url in _level_label_cache:
        return _level_label_cache[url]
    nomor = run_js(r"""
const t = document.body ? document.body.innerText.slice(0, 400) : '';
const m = t.match(/Lesson\s+(\d+)/);
return m ? m[1] : null;
""", PAGE.main_frame)
    lab = f"L{nomor}" if nomor else ""
    # Cache hanya yang berhasil: halaman yang belum selesai memuat masih
    # kosong; kalau dikosongkan pun, cache "" akan menutup label selamanya
    # untuk URL itu (pernah membuat indikator level GUI selalu salah).
    if nomor:
        _level_label_cache[url] = lab
        _level_map_catat(nomor, url)
    return lab


def _wait_play_url(newpg):
    for _ in range(16):
        time.sleep(0.5)
        if STOP:
            return None
        try:
            u = newpg.evaluate("() => location.href")
        except Exception:
            u = None
        if u and ".play" in u and _is_edclub_url(u):
            return u
    return None


def _goto_next_lesson_in_list(newpg, current_url):
    """Buka daftar pelajaran dan klik pelajaran berikutnya SESUAI URUTAN
    KURSUS. Nomor URL edclub tidak berurutan (setelah 189.play situs
    lanjut ke 2959.play) - jangan hitung N+1. Klik baris
    pertama yang belum dikerjakan; kalau itu malah lesson yang baru
    ditinggalkan (level rusak) atau lesson yang sudah ditandai rusak,
    klik baris TEPAT SETELAH baris itu. Return URL .play, None jika gagal."""
    cur = _lesson_id(current_url)
    row = 0
    for _ in range(6):
        if STOP:
            return None
        try:
            newpg.goto(LIST_URL, timeout=25000)
            newpg.wait_for_selector("div.box-container div.lsn_name",
                                    timeout=15000)
        except Exception:
            continue
        idx = newpg.evaluate("""(arg) => {
            const rows = [...document.querySelectorAll('div.box-container')];
            for (let i = arg; i < rows.length; i++) {
                const cls = rows[i].className || '';
                if (!cls.includes('is_unlocked') || cls.includes('has_progress')) continue;
                const nm = rows[i].querySelector('div.lsn_name');
                if (nm) { nm.click(); return i; }
            }
            return -1;
        }""", row)
        if idx is None or idx < 0:
            continue
        row = idx + 1
        url = _wait_play_url(newpg)
        if not url:
            continue
        lid = _lesson_id(url)
        if lid != cur and lid not in _broken_lessons:
            return url
        # baris ini = level rusak itu sendiri / sudah ditandai rusak
        # -> ulangi dari baris setelahnya.
    return None


def _skip_to_next_lesson(alasan):
    """Level rusak/premium-beku: buka tab BARU ke pelajaran berikutnya
    menurut URUTAN DAFTAR (bukan N+1 URL), tutup tab lama."""
    global PAGE, last_url, last_action_time, _last_recovery
    base = last_url if (last_url and ".play" in last_url) else ""
    if not base:
        try:
            base = _real_url(PAGE)
        except Exception:
            base = ""
    if ".play" not in base:
        return False
    lid = _lesson_id(base)
    if lid:
        _broken_lessons.add(lid)
    # Coba di tab yang sama dulu (tanpa buka tab baru - user terganggu
    # dengan tab baru terus-menerus). Tab baru hanya kalau tab sekarang
    # mati (evaluate/goto gagal).
    url = None
    newpg = PAGE
    try:
        url = _goto_next_lesson_in_list(newpg, base)
    except Exception:
        url = None
    if url is None:
        try:
            newpg = PAGE.context.new_page()
            url = _goto_next_lesson_in_list(newpg, base)
        except Exception:
            url = None
        if url is None:
            try:
                newpg.close()
            except Exception:
                pass
            return False
        old = PAGE
        PAGE = newpg
        try:
            if old is not newpg:
                old.close()
        except Exception:
            pass
    _recovery_counts.pop(base, None)
    _hijack_counts.pop(base, None)
    last_url = PAGE.url
    last_action_time = time.time()
    _last_recovery = time.time()
    print(f"[SKIP] {alasan} - lanjut ke {url.split('/')[-1]} "
          f"(urutan daftar pelajaran)")
    return True


# ---------------------------------------------------------------------------
# Loop utama
# ---------------------------------------------------------------------------

last_typed_text = ""
last_action_time = time.time()
last_debug_dump = 0.0
last_url = ""
_premlock_since = 0.0
_login_notice = 0.0


# ---------------------------------------------------------------------------
# Deteksi sesi login edclub
#
# Tiga lapis (tanpa menebak selector DOM yang tidak terverifikasi):
# 1. URL login/signin (perilaku lama, tetap).
# 2. Sentinel 401/403: pasang listener respons jaringan sekali di connect().
# edclub sendiri yang "mengetahui" sesi mati lewat API-nya (ini satu-
# satunya cara menangkap kasus "logout diam-diam saat tab lama dibiarkan
# terbuka" - cookie masih ada tapi server sudah menolaknya).
# 3. Cookie sesi via CDP: profil yang belum pernah login tidak punya cookie
# edclub selain milik Cloudflare (__cf_bm/_cfuvid) -> jelas belum login.
# ---------------------------------------------------------------------------
_login_sentinel = {"ok": True, "alasan": "", "gagal403": 0.0,
                   "terakhir401": 0.0, "path401": {}, "log401": 0.0,
                   "pernah_in": False, "unknown_mulai": 0.0}
_login_ck = {"terakhir": 0.0}

# Path API yang 401-nya pasti berarti sesi mati (penyimpanan progress,
# data murid, sesi). Endpoint lain (mis. premium/entitlement) balas 401
# untuk akun gratis yang sedang login - : satu 401 seperti
# itu pernah memunculkan popup 'belum login' padahal user login.
SESI_PATH_RE = re.compile(r"(session|login|logout|/me\b|/me/|progress|student)",
                          re.I)


def _pasang_login_sentinel():
    """Pasang listener response XHR/fetch edclub -> tangkap 401/403.
    Dipasang ke semua context (tab baru ikut terpasang lewat event page)."""
    if browser is None:
        return

    def on_response(resp):
        try:
            if resp.status not in (401, 403):
                return
            req = resp.request
            if req.resource_type not in ("xhr", "fetch"):
                return
            host = (urlparse(resp.url).hostname or "").lower()
            if not (host.endswith("edclub.com") or host.endswith("typingclub.com")):
                return
            if resp.status == 401:
                now = time.time()
                path = urlparse(resp.url).path or "/"
                _login_sentinel["terakhir401"] = now
                _login_sentinel["path401"][path] = now
                for p in list(_login_sentinel["path401"]):
                    if now - _login_sentinel["path401"][p] > 120:
                        del _login_sentinel["path401"][p]
                if now - _login_sentinel["log401"] > 30:
                    _login_sentinel["log401"] = now
                    print(f"[LOGIN] catatan: API balas 401 ({path[:60]})")
                # 401 tunggal dari endpoint acak bukan tanda sesi mati
                # (akun gratis: endpoint premium memang 401). Percayai
                # hanya endpoint sesi, atau beberapa endpoint berbeda.
                if (SESI_PATH_RE.search(path)
                        or len(_login_sentinel["path401"]) >= 3):
                    _login_sentinel["ok"] = False
                    _login_sentinel["alasan"] = f"API edclub 401 ({path[:40]})"
            else:
                # 403 sesekali bisa hal lain (konten premium) -> butuh 2x
                # dalam 60 detik baru dianggap sesi mati
                now = time.time()
                if now - _login_sentinel["gagal403"] < 60:
                    _login_sentinel["ok"] = False
                    _login_sentinel["alasan"] = "API edclub berulang 403"
                _login_sentinel["gagal403"] = now
        except Exception:
            pass

    def on_page(pg):
        try:
            pg.on("response", on_response)
        except Exception:
            pass

    for ctx in browser.contexts:
        try:
            ctx.on("page", on_page)
            for pg in ctx.pages:
                on_page(pg)
        except Exception:
            pass


PROFILE_CHECK_JS = r"""
// Status login dari DOM. Sinyal live terverifikasi (akun Individual &
// portal sportal - sesi edclub Tidak disimpan di cookie, auth memakai
// header 'Authorization: Token' dari storage internal browser):
// 1..profile-name berisi nama user -> LOGIN (pasti).
// 2. li.dropdown > a.dropdown-toggle Bernama Orang di navbar -> LOGIN.
// (live: dashboard sportal & daftar.game menampilkan 'Zafran Hulaif'
// sebagai toggle; toggle UI lain = Courses/English/Save Progress/
// Typing Jungle - dikecualikan lewat daftar hitam + label bahasa).
// 3. Tautan 'Log in / Sign up' di header -> Logout (terverifikasi di
// halaman daftar.game logout).
const el = document.querySelector('.profile-name');
if (el) {
    const t = (el.textContent || '').trim();
    if (t && !/sign|log\s*in/i.test(t)) return 'in';
    return 'out';
}
const UI_TOGGLE = /^(courses?|english|save progress|more|help|settings?|language|lessons?|programs?|typing jungle|espa\S*|\d+)$/i;
const tog = document.querySelectorAll('li.dropdown > a.dropdown-toggle');
for (const a of tog) {
    if (a.querySelector('.selected-language-label')) continue;
    const t = (a.textContent || '').replace(/\s+/g, ' ').trim();
    if (!t || t.length > 40) continue;
    if (/log ?(in|out)|sign ?(in|up|out)/i.test(t)) continue;
    if (UI_TOGGLE.test(t)) continue;
    return 'in';
}
const adaLogin = [...document.querySelectorAll('a, button')].some(e =>
    /^(log in|login|sign in|sign up|signup|masuk|daftar)$/i
    .test((e.textContent || '').trim()));
if (adaLogin) return 'out';
return null;
"""


def _profil_login():
    """'in'/'out'/None dari elemen .profile-name halaman aktif. INI sinyal
 utama edclub Individual: sesi TIDAK disimpan di cookie sama sekali
 (live: user login betulan, cookie cuma tracker/cloudflare) - deteksi
 cookie mustahil. Elemen profil tampil begitu sesi hidup -> pemulihan
 popup instan setelah user login."""
    try:
        return run_js(PROFILE_CHECK_JS, PAGE.main_frame)
    except Exception:
        return None


def _fetch_login():
    """Deprecated: fetch /api/v1.1/student/me/ TIDAK bisa dipakai - live
    halaman edclub sendiri mengirimnya tanpa token (401 selalu,
    bahkan saat login; API user sebenarnya memakai header Authorization:
    Token dari storage internal). Diganti _probe_tab_login()."""
    return None


_probe_tab_ck = {"terakhir": 0.0}


def _probe_tab_login(timeout_s=15.0):
    """Buka tab CADANGAN ke dashboard edclub, baca penanda login di sana,
    lalu tutup. Status sesi berlaku untuk AKUN secara keseluruhan (token
    disimpan browser, bukan per-halaman) - jadi penanda di dashboard
    menjawab status untuk halaman apapun yang sedang aktif (mis. lesson
    .play yang navbarnya tidak pernah tampil).

    HYDRATION RACE (bug live 08:33): dashboard yang baru dimuat merender
    navbar versi LOGOUT dulu ('Login' link), lalu setelah cek sesi (~1-3
    dtk) diganti nama user. Dulu poll pertama langsung percaya 'out' ->
    popup 'belum login' padahal user sudah login. Sekarang 'out' harus
    STABIL 2 poll berurutan; 'in' (nama user muncul) selalu pasti ->
    langsung. Redirect URL ke /signin = keputusan server, pasti logout.

    Timeout 15 dtk: browser dingin + Cloudflare + iklan bisa >10 dtk
    (dulu None -> patroli menunggu throttle 30-60 dtk berikutnya = cek
    login pertama terasa lama). Return 'in'/'out'/None."""
    try:
        tab = PAGE.context.new_page()
    except Exception:
        return None
    hasil = None
    out_hitung = 0
    try:
        try:
            tab.goto("https://www.edclub.com/sportal/", timeout=20000)
        except Exception:
            pass
        batas = time.time() + timeout_s
        while time.time() < batas and hasil is None:
            try:
                r = tab.evaluate("() => {" + PROFILE_CHECK_JS + "}")
            except Exception:
                r = None
            if r == "in":
                hasil = "in"
                break
            if r == "out":
                out_hitung += 1
                if out_hitung >= 2:
                    hasil = "out"
                    break
                time.sleep(1.5)
                continue
            out_hitung = 0
            try:
                lowtab = (tab.url or "").lower()
            except Exception:
                lowtab = ""
            if any(k in lowtab for k in ("signin", "login", "signup")):
                hasil = "out"
                break
            time.sleep(0.7)
    finally:
        try:
            tab.close()
        except Exception:
            pass
    return hasil


def _patroli_login(url):
    """Cek berkala dari main loop: set/bersihkan PERLU_LOGIN. Interval 8 dtk
    biasa, 3 dtk saat sedang menunggu user login (popup harus tertutup
    cepat begitu user selesai login, bukan 8 dtk kemudian)."""
    global PERLU_LOGIN, MINTA_LOGIN_NAV, LOGIN_DICEK
    now = time.time()
    jeda = 3.0 if PERLU_LOGIN else 8.0
    if now - _login_ck["terakhir"] < jeda:
        return
    _login_ck["terakhir"] = now
    profil = _profil_login()
    low = (url or "").lower()
    di_login = any(k in low for k in ("login", "signin", "sign-in", "signup"))
    # DOM halaman aktif tidak punya penanda (lesson .play, SPA kosong,
    # navbar belum selesai render, Cloudflare) -> cek lewat tab cadangan
    # ke dashboard (status sesi berlaku akun-wide). Throttle 30 dtk;
    # hanya saat jawaban benar-benar dibutuhkan (gerbang belum terbuka
    # atau sedang menunggu login).
    if (profil is None and not di_login
            and ("edclub" in low or "typingclub" in low)
            and (PERLU_LOGIN or not LOGIN_DICEK)
            and now - _probe_tab_ck["terakhir"]
                > (60.0 if PERLU_LOGIN else 30.0)):
        _probe_tab_ck["terakhir"] = now
        print("[LOGIN] Halaman ini tanpa penanda login - cek sesi lewat "
              "tab cadangan...")
        profil = _probe_tab_login()
    # pemulihan instan: profil bernama = pasti login (menimpa sentinel)
    if profil == "in":
        _login_sentinel["pernah_in"] = True
        if not _login_sentinel["ok"] or PERLU_LOGIN:
            _login_sentinel["ok"] = True
            _login_sentinel["alasan"] = ""
            _login_sentinel["path401"].clear()
    mati = (di_login or not _login_sentinel["ok"]
            or profil == "out") and profil != "in"
    if profil is not None:
        _login_sentinel["unknown_mulai"] = 0.0
    elif not mati and not PERLU_LOGIN and not _login_sentinel["pernah_in"]:
        # profil masih None walau DOM + tab cadangan gagal (halaman mati /
        # Cloudflare menggantung / renderer sibuk). Kumpulkan durasi;
        # >40 dtk di halaman edclub -> perlakukan seperti logout.
        if (("edclub" in low or "typingclub" in low) and not di_login):
            if not _login_sentinel["unknown_mulai"]:
                _login_sentinel["unknown_mulai"] = now
                print("[LOGIN] Status login belum terbaca (halaman masih "
                      "memuat/diverifikasi) - menunggu...")
            elif now - _login_sentinel["unknown_mulai"] > 40.0:
                _login_sentinel["ok"] = False
                _login_sentinel["alasan"] = "login tidak terdeteksi >40 dtk"
                mati = True
        else:
            _login_sentinel["unknown_mulai"] = 0.0
    # GUI hanya boleh menanya rentang kalau status login pasti (in/out/mati)
    if mati or profil in ("in", "out"):
        LOGIN_DICEK = True
    if mati and not PERLU_LOGIN:
        PERLU_LOGIN = True
        print("[LOGIN] Sesi edclub tidak aktif"
              + (f" ({_login_sentinel['alasan']})" if _login_sentinel["alasan"] else "")
              + ". Login di jendela browser bot - bot menunggu di sini.")
    elif PERLU_LOGIN and profil == "in":
        # Pulih hanya dengan bukti positif login (profil 'in'). Kalau profil
        # None (halaman tanpa penanda + tab cadangan tertahan throttle)
        # dianggap 'pulih' -> PERLU_LOGIN=False -> popup login tertutup &
        # bot jalan mengetik padahal user logout .
        PERLU_LOGIN = False
        _login_sentinel["ok"] = True
        _login_sentinel["alasan"] = ""
        print("[LOGIN] Sesi edclub aktif kembali - lanjut.")
    if PERLU_LOGIN and MINTA_LOGIN_NAV:
        MINTA_LOGIN_NAV = False
        # URL login yang benar (live: /login = 404). Individu = /signin
        # ("Login Individual Edition"); akun sekolah = portal sportal.
        tujuan = MINTA_LOGIN_URL or LOGIN_URL_INDIVIDU
        try:
            PAGE.goto(tujuan, timeout=25000)
            # fokus ke jendela browser: user baru memilih 'buka halaman
            # login' - jangan biarkan popup bot yang tetap memegang fokus
            try:
                PAGE.bring_to_front()
            except Exception:
                pass
            print(f"[LOGIN] Halaman login dibuka: {tujuan}")
        except Exception as e:
            print(f"[LOGIN] Gagal membuka halaman login: {str(e)[:60]}")
_stripe_sweep_last = 0.0
_nav_try = 0.0
stats = {"std": 0, "mini": 0, "ocr": 0, "popup": 0, "hold": 0, "uikey": 0, "tut": 0,
         "phaser": 0, "video": 0, "intro": 0}


def _sweep_stripe_tabs(force=False):
    """Tutup TAB Stripe liar kapan pun mereka muncul. Dulu pembersihan
    hanya jalan saat TAB UTAMA kabur ke Stripe - padahal modal premium
    (iframe checkout) juga bisa membuka/men-navigasi tab LAIN diam-diam,
    sehingga sesi berikutnya selalu dibuka dengan sisa 'Stripe'."""
    global _stripe_sweep_last
    now = time.time()
    if not force and now - _stripe_sweep_last < 5.0:
        return
    _stripe_sweep_last = now
    try:
        for c in browser.contexts:
            for pg in list(c.pages):
                if pg is PAGE:
                    continue
                try:
                    h = (urlparse(_real_url(pg)).hostname or "").lower()
                except Exception:
                    continue
                if "stripe" in h:
                    pg.close()
                    print("[TAB] tab Stripe liar ditutup")
    except Exception:
        pass


def _page_hidup(pg, timeout_ms=3000):
    """Renderer halaman masih merespons? evaluate() di renderer yang
    di-suspend Windows (browser idle di latar) MENGHANG TANPA TIMEOUT -
    pernah membuat main loop mati diam total (live). wait_for_load_state
    MENERIMA timeout -> panggilan pembuka yang aman sebelum menyentuh
    halaman. True = hidup."""
    try:
        pg.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        return True
    except Exception:
        return False


def _pulihkan_renderer():
    """Renderer tab aktif mati/suspend. Satu-satunya obat:
    restart browser debug (taskkill + relaunch, tanpa curi fokus), lalu
    sambung ulang. Dipanggil dari main loop (thread pemilik Playwright).
    Return True = tersambung ulang & boleh lanjut."""
    global PAGE
    print("[PEMULIHAN] Halaman tidak merespons (renderer menggantung) - "
          "memulai ulang browser debug...")
    PAGE = None
    try:
        disconnect()
    except Exception:
        pass
    if not _restart_browser_debug():
        print("[PEMULIHAN] Browser tidak bisa direstart.")
        return False
    try:
        connect()
        return PAGE is not None
    except SystemExit:
        return False


def _rentang_cek(url):
    """Terapkan rentang level pilihan user. Return True = main loop harus
    `continue` (navigasi/berhenti ditangani di sini). Kasus penting (live):
    setelah login bot mendarat di DAFTAR lesson (.game) - dulu lompatan
    hanya berlaku di halaman .play, sehingga recovery malah membuka level
    TERDEPAN akun (L106) mengabaikan rentang; sekarang dari daftar pun
    langsung menuju LEVEL_START.
    RENTANG_SIAP: rentang baru boleh DITERAPKAN setelah user menjawab
    dialog rentang saat Start (live 00:2x: patroli login membersihkan
    PERLU_LOGIN, dan SEBELUM dialog rentang sempat terbuka (poll GUI
    150ms belumlah jalan) case-3 di bawah langsung melompat ke LEVEL_START
    lama yang tersimpan (662) - browser pindah ke level sendiri padahal
    user belum menjawab apapun)."""
    global RENTANG_SELESAI, STOP, _rentang_nav, _rentang_jump_done, _rentang_max_seen
    if not RENTANG_SIAP:
        return False
    if RENTANG_SELESAI or (LEVEL_START <= 1 and not LEVEL_END):
        return False
    on_play = ".play" in (url or "")
    nomor = 0
    if on_play:
        if STATUS_LABEL.startswith("L"):
            try:
                nomor = int(STATUS_LABEL[1:])
            except ValueError:
                pass
        if not nomor:
            nomor = url_ke_level(url) or 0
        if nomor > _rentang_max_seen:
            _rentang_max_seen = nomor
    # 1) melewati akhir rentang -> selesai
    if nomor and LEVEL_END and nomor > LEVEL_END:
        RENTANG_SELESAI = True
        STOP = True
        print(f"[RENTANG] level {nomor} melewati akhir rentang "
              f"({LEVEL_END}) - bot selesai.")
        return True
    # 1b) selesai saat meninggalkan level akhir: level terakhir kursus
    # (live: L685 = video) tidak pernah punya lesson berikutnya - begitu
    # selesai, situs mendarat ke daftar lesson dan cek 'nomor > LEVEL_END'
    # di atas tidak pernah terpicu. Dulu bot malah lompat balik ke level
    # awal rentang dan mengerjakan ulang 668..685 terus-menerus.
    if (LEVEL_END and _rentang_max_seen >= LEVEL_END and not on_play
            and not PERLU_LOGIN):
        RENTANG_SELESAI = True
        STOP = True
        print(f"[RENTANG] level akhir {_rentang_max_seen} selesai (keluar dari "
              f"lesson) - bot selesai.")
        return True
    if on_play:
        if LEVEL_START <= 1 or _rentang_jump_done:
            return False
        # Jangan lompat balik ke awal rentang kalau level dalam rentang sudah
        # pernah dikerjakan sesi ini - user sengaja membuka level itu.
        if _rentang_max_seen >= LEVEL_START and _rentang_max_seen > 1:
            return False
    # 2) di lesson yang di bawah awal rentang -> lompat
    if on_play:
        if nomor and nomor < LEVEL_START and time.time() - _rentang_nav > 10:
            _rentang_nav = time.time()
            print(f"[RENTANG] level {nomor} di bawah awal ({LEVEL_START}) "
                  f"- lompat ke level {LEVEL_START}")
            if _goto_level_url(LEVEL_START):
                _rentang_jump_done = True
            else:
                print("[RENTANG] URL level awal belum ada di peta - "
                      "bangun peta dulu (tombol Rentang).")
            return True
        return False
    # 3) tidak di lesson (daftar/home edclub) dan sudah login, user diam:
    # kembali ke level yang sedang dikerjakan sesi ini (LEVEL_START kalau
    # belum ada), bukan level terdepan akun. (Keluhan live: user diam di
    # daftar pelajaran, recovery malah membuka L106 terdepan dan bot
    # mengetiknya.) Dulu case ini dibiarkan ke recovery.
    if not PERLU_LOGIN and not _user_aktif(25.0) \
            and time.time() - _rentang_nav > 10:
        _rentang_nav = time.time()
        lanjut = max(LEVEL_START, _rentang_max_seen)
        if _goto_level_url(lanjut):
            _rentang_jump_done = True
            print(f"[RENTANG] kembali ke level {lanjut}...")
            return True
        print("[RENTANG] URL level lanjut belum ada di peta - lanjut otomatis.")
    return False


def main_loop():
    global PAGE, last_url, last_debug_dump, last_action_time, _last_recovery
    global STATUS_URL, STATUS_LABEL, _login_notice, _nav_try, _intro_flow, _premlock_since, _label_retry
    global MINTA_BANGUN_PETA, RENTANG_SELESAI, _rentang_nav, STOP, _last_loop_err, _rentang_jump_done
    global _rentang_max_seen
    if PAGE is None:
        try:
            connect()
        except SystemExit:
            return
    # Validasi level start terkunci kini non-blokir di dalam loop
    # (_rentang_validasi_step) setelah gerbang login - lihat catatan di
    # fungsinya (bug: 00:04: blokir pra-loop membekukan semuanya).
    global _unlock_set, _rentang_validasi_done
    _rentang_validasi_done = False
    _rentang_max_seen = 0    # level tertinggi yang dilihat sesi ini (anti lompat balik)
    renderer_gagal = 0
    pulih_selesai = 0
    _nav_time = 0.0           # waktu tiba di URL saat ini (grace pemulihan)
    _tunggu_rentang_baru = False
    _rentang_jump_done = False   # lompat ke LEVEL_START hanya sekali, dan
    # hanya kalau saat mulai tidak sedang berada di lesson (user yang membuka
    # level sendiri = kerjakan saja level itu, jangan paksa lompat)
    try:
        _rentang_jump_done = ".play" in (_real_url(PAGE) or "")
        if _rentang_jump_done and LEVEL_START > 1:
            print(f"[RENTANG] sudah ada lesson terbuka - kerjakan ini dulu "
                  f"(lompatan ke level {LEVEL_START} dilewati).")
    except Exception:
        pass
    while True:
        try:
            if STOP:
                print("Bot dihentikan.")
                break
            if PAUSED:
                time.sleep(0.2)
                continue

            # Gerbang kesehatan renderer sebelum evaluasi apa pun: evaluate
            # di renderer suspend menghang tanpa timeout (bug: log mati
            # total tepat setelah 'Terhubung!'). 2x gagal -> restart browser.
            if not _page_hidup(PAGE):
                renderer_gagal += 1
                if renderer_gagal == 1:
                    print("[PEMULIHAN] Tab tidak merespons, memberi 5 detik...")
                    time.sleep(5)
                    continue
                if time.time() - pulih_selesai < 60:
                    print("[PEMULIHAN] Baru saja restart tapi masih mati - "
                          "stop (cek jendela browser secara manual).")
                    STOP = True
                    break
                if _pulihkan_renderer():
                    pulih_selesai = time.time()
                    renderer_gagal = 0
                    continue
                STOP = True
                break
            renderer_gagal = 0

            # anti-pause ringan tiap iterasi (banner "Start Typing dll.")
            keep_alive_frames()
            _sweep_stripe_tabs()

            url = PAGE.url
            # page.url Playwright bisa stale: tab berisi Stripe checkout
            # masih melaporkan URL edclub . Percayai
            # location.href; kalau host = stripe/checkout = tab dibajak.
            try:
                real = _real_url(PAGE)
            except Exception:
                real = url
            if _is_edclub_url(real):
                url = real
            else:
                try:
                    rh = (urlparse(real).hostname or "").lower()
                except Exception:
                    rh = ""
                if "stripe" in rh or "checkout" in rh:
                    url = real
            STATUS_URL = url
            # label level bisa kosong saat pertama datang (halaman belum
            # selesai memuat) -> coba lagi berkala sampai dapat
            if not STATUS_LABEL and time.time() - _label_retry > 2:
                _label_retry = time.time()
                try:
                    STATUS_LABEL = _level_label()
                except Exception:
                    pass
            if not _is_edclub_url(url):
                # tab bisa ter-bawa navigasi ke Stripe checkout (dibuktikan
                # live: klik di area iframe premium = top-level navigation).
                # Tutup tab stripe yang menganggur, lalu cari/buat tab edclub.
                _sweep_stripe_tabs(force=True)
                # coba cari ulang tab edclub (prioritas yang di halaman .play)
                found = None
                for pg in browser.contexts[0].pages:
                    pu = _real_url(pg)
                    if _is_edclub_url(pu):
                        if ".play" in pu:
                            found = pg
                            break
                        if found is None:
                            found = pg
                if found:
                    PAGE = found
                else:
                    # Tidak ada tab edclub sama sekali. Buka tab baru (bukan
                    # goto dari konteks Stripe - pernah diblokir Brave), lalu
                    # tutup tab lama. Lesson yang sama dibajak 2x = level
                    # premium rusak -> langsung lompat ke berikutnya.
                    if time.time() - _nav_try > 10:
                        _nav_try = time.time()
                        key = last_url if (last_url and ".play" in last_url) else url
                        n = _hijack_counts.get(key, 0) + 1
                        _hijack_counts[key] = n
                        if n >= 2 and _skip_to_next_lesson(
                                "tab berulang kali dibawa ke Stripe"):
                            _hijack_counts.pop(key, None)
                            continue
                        target = key if ".play" in key else LIST_URL
                        newpg = None
                        try:
                            newpg = PAGE.context.new_page()
                            newpg.goto(target, timeout=25000)
                            old = PAGE
                            PAGE = newpg
                            try:
                                if old is not newpg:
                                    old.close()
                            except Exception:
                                pass
                            last_url = PAGE.url
                            last_action_time = time.time()
                            print(f"[NAV] tab dibajak Stripe - tab baru ke "
                                  f"{target.split('/')[-1]}")
                        except Exception:
                            if newpg is not None:
                                try:
                                    newpg.close()
                                except Exception:
                                    pass
                    time.sleep(1)
                    continue

            low = url.lower()
            _patroli_login(url)
            if PERLU_LOGIN:
                # Jangan buang level untuk sesi mati: berhenti mengetik,
                # GUI memunculkan popup; lanjut sendiri setelah login.
                if time.time() - _login_notice > 30:
                    _login_notice = time.time()
                    print("[LOGIN] Menunggu login edclub di jendela browser bot...")
                time.sleep(1)
                continue
            if not LOGIN_DICEK:
                # gerbang keras: status login belum pasti (belum terbaca
                # in/out). Dilarang mengetik / recovery / klik apapun.
                # Bug live 2x: saat status belum terbaca, (1) popup rentang
                # dimunculkan padahal belum login, (2) recovery macetnya
                # daftar pelajaran malah membuka pelajaran gratis 116 dan
                # bot mengetik tanpa login & tanpa rentang.
                if time.time() - _login_notice > 15:
                    _login_notice = time.time()
                    print("[LOGIN] Menunggu status login terbaca "
                          "(jangan melakukan apapun dulu)...")
                time.sleep(1)
                continue
            if "login" in low or "signin" in low or "sign-in" in low or "signup" in low:
                # belum login: jangan spam recovery, tunggu user login manual
                if time.time() - _login_notice > 30:
                    _login_notice = time.time()
                    print("[LOGIN] Halaman login terdeteksi. Login dulu di "
                          "browser bot, bot menunggu di sini...")
                time.sleep(2)
                continue

            # validasi level start terkunci (non-blokir, hanya setelah
            # status login pasti; selama menunggu jawaban GUI, loop berhenti
            # di sini dan tidak menyentuh halaman)
            if not _rentang_validasi_step():
                STOP = True
                return

            # user asli sedang memakai browser bot di luar lesson (daftar
            # level, pengaturan, profil) - jangan ambil alih; tunggu sampai
            # user diam atau masuk lesson sendiri. >2 menit -> GUI bertanya.
            if ".play" not in url and _user_aktif(25.0):
                _tunggu_user(url)
                continue
            _user_diam_lagi(url)

            if url != last_url:
                # level baru: cooldown Phaser dari game sebelumnya tidak
                # berlaku lagi (dulu bikin minigame berikutnya tunda 20 dtk)
                _phaser_cooldown["until"] = 0.0
                _phaser_freeze["url"] = ""
                _phaser_freeze["count"] = 0
                _phaser_freeze["clicked"] = False
                _intro_flow = False   # layar intro pertama level ini = settle penuh
                _premlock_since = 0.0
                STATUS_LABEL = ""
                if last_url:
                    print(f"[PROGRES] {_level_label() or '?'} "
                          f"({last_url.split('/')[-1]} -> {url.split('/')[-1]})  "
                          f"(std={stats['std']} tut={stats['tut']} mini={stats['mini']} "
                          f"phaser={stats['phaser']} ocr={stats['ocr']} hold={stats['hold']} "
                          f"video={stats['video']} popup={stats['popup']})")
                # label level asli untuk indikator GUI (bukan rumus URL:
                # nomor URL acak per akun dan pernah salah terus)
                try:
                    STATUS_LABEL = _level_label()
                except Exception:
                    STATUS_LABEL = ""
                last_url = url
                # Navigasi = aktivitas: budget stall baru untuk halaman
                # yang baru dibuka. Dulu timer stall tidak direset saat
                # pindah halaman -> waktu menunggu dialog rentang/login
                # terakumulasi -> tepat setelah lompatan rentang, recovery
                # menembak '[tunda] 107s' padahal halaman baru dimuat
                # .
                last_action_time = time.time()
                _nav_time = time.time()

            # permintaan bangun peta level dari GUI
            if MINTA_BANGUN_PETA:
                MINTA_BANGUN_PETA = False
                bangun_peta_level()
                continue
            # rentang sedang ditanyakan GUI -> berhenti bergerak (dulu:
            # recovery menembak & membuka level terdepan L106 saat popup
            # rentang masih terbuka)
            if TUNGGU_RENTANG:
                _tunggu_rentang_baru = True
                time.sleep(0.3)
                continue
            if _tunggu_rentang_baru:
                _tunggu_rentang_baru = False
                # dialog rentang selesai dijawab: budget stall baru (waktu
                # user berpikir di depan popup bukan 'halaman mati')
                last_action_time = time.time()
            # rentang level pilihan user (lompat awal / berhenti di akhir)
            if _rentang_cek(url):
                continue

            # Watch window: klik X modal premium sebelum penutup pop-up
            # dan handler mana pun. modal premium edclub
            # hanya sekali per page-load; ESC/klik salah dari penutup
            # pop-up pernah mengkonsumsi modal itu (log 08:02: 'kirim ESC
            # (premium)') -> level premium berikutnya tak pernah dapat
            # modal -> game beku. X diklik = edclub lanjut sendiri.
            # (berlaku sepanjang waktu, bukan hanya awal level: upsell
            # premium juga muncul di akhir lesson, macam di 2967)
            if _premium_modal_action() == "clicked":
                last_action_time = time.time()
                time.sleep(0.8)
                continue

            if close_overlays_all_frames():
                stats["popup"] += 1
                time.sleep(0.6)
                continue

            state, frame, data = detect_all_frames()

            if state == "std":
                handle_standard(frame, data)
            elif state == "tut":
                handle_tutorial(frame, data)
            elif state == "mini":
                handle_minigame(frame, data)
            elif state == "score":
                if advance_score_screen():
                    last_action_time = time.time()
                time.sleep(0.6)
            else:
                # Modal premium: setelah watch window, modal zombie
                # (fullscreen checkout tanpa X) -> tunggu 12 dtk lalu
                # lewati sesuai urutan daftar.
                pm = _premium_modal_action()
                if pm == "clicked":
                    last_action_time = time.time()
                    time.sleep(0.6)
                    continue
                if pm and pm.get("zombie"):
                    if _premlock_since == 0.0:
                        _premlock_since = time.time()
                        print("[Premium] modal fullscreen tanpa X "
                              "(checkout Stripe) - menunggu...")
                    elif time.time() - _premlock_since > 12.0:
                        if _skip_to_next_lesson("modal premium tak tertutup"):
                            _premlock_since = 0.0
                            continue
                else:
                    _premlock_since = 0.0
                if handle_intro_steps():
                    time.sleep(0.05)
                    continue
                if handle_phaser_minigame():
                    time.sleep(0.3)
                    continue
                if try_hold_level():
                    time.sleep(0.4)
                    continue
                if click_screen_keyboard():
                    time.sleep(0.4)
                    continue
                if handle_video_level():
                    time.sleep(0.4)
                    continue
                if not try_ocr_minigame(data or {}):
                    stalled = time.time() - last_action_time
                    # user asli aktif (memegang halaman)? Semua aksi ambil-
                    # alih (klik lanjut, ganti tab, recovery) ditunda -
                    # dulu intervensi user salah dibaca 'level selesai/
                    # mati' dan bot menekan tombol sendiri.
                    user_sibuk = _user_aktif(25.0)
                    # heartbeat: bot tidak boleh pernah diam tanpa kabar.
                    # (dulu: state unknown = sunyi total, kelihatan mati)
                    if stalled > 10 and time.time() - last_debug_dump > 10:
                        last_debug_dump = time.time()
                        print(f"[TUNDA] tidak ada aktivitas {stalled:.0f}s di "
                              f"{url.split('/')[-1]} - dumping state...")
                        dump_debug_info()
                    # Level premium yang modal-nya sudah tertutup tapi layar
                    # masih gelap & tak ada kerjaan (edclub bug, level 106):
                    # satu klik tombol lanjut langsung ke lesson berikutnya
                    # (perilaku terverifikasi user). Coba sebelum recovery.
                    if stalled > 6 and not user_sibuk:
                        prem = False
                        for fr2 in all_frames():
                            h = run_js(MODAL_HINT_JS, fr2)
                            if h and h.get("premium"):
                                prem = True
                                break
                        if prem:
                            # tanpa Enter (form checkout bisa menangkap Enter)
                            # - langsung klik mouse asli di tombol lanjut.
                            clicked_prem = False
                            try:
                                loc = PAGE.locator(
                                    ".navbar-continue, a.navbar-continue").first
                                if loc.count() and loc.is_visible():
                                    loc.click(timeout=2000)
                                    clicked_prem = True
                                    print("[Premium] layar gelap premium - "
                                          "lanjut ke lesson berikutnya")
                                    last_action_time = time.time()
                                    continue
                            except Exception:
                                pass
                            # Tidak ada tombol lanjut -> level memang rusak:
                            # lompat langsung, jangan tunggu recovery.
                            if not clicked_prem and _skip_to_next_lesson(
                                    "layar gelap premium tanpa tombol lanjut"):
                                last_action_time = time.time()
                                continue
                    # Tab edclub lain mungkin punya pekerjaan (bot bisa
                    # nyangkut di tab yang salah setelah navigasi manual).
                    if stalled > 6 and not user_sibuk and _switch_to_playable_tab():
                        continue
                    # level terkunci = halaman .play kosong (live: L100
                    # logout memuat body kosong) - reload tidak akan
                    # menolong; lompat ke urutan daftar.
                    if stalled > 10:
                        nomor = 0
                        if STATUS_LABEL.startswith("L"):
                            try:
                                nomor = int(STATUS_LABEL[1:])
                            except ValueError:
                                pass
                        if nomor and _unlock_set is None:
                            _unlock_set = _baca_unlock_set()
                        if nomor and _unlock_set and nomor not in _unlock_set:
                            if _skip_to_next_lesson("level terkunci untuk akun"):
                                last_action_time = time.time()
                                continue
                    if stalled > 12 and not user_sibuk and time.time() - _last_recovery > 25 \
                            and time.time() - _nav_time > 25:
                        # halaman kemungkinan mati/kosong -> pulihkan otomatis
                        # (grace 25 dtk sejak tiba: halaman yang baru dinavigasi
                        # (mis. lompatan rentang) boleh lambat memuat - jangan
                        # langsung dikira mati dan di-reload)
                        if not recover_and_restart_lesson():
                            _last_recovery = time.time()

            time.sleep(0.15)

        except KeyboardInterrupt:
            print("Dihentikan manual.")
            break
        except Exception as ex:
            # jangan menelan exception diam-diam (bug: loop error 2x/dtk
            # tanpa satu baris log pun - bot 'mati diam'). Throttled 30 dtk.
            if time.time() - _last_loop_err > 30:
                _last_loop_err = time.time()
                print(f"[LOOP] error (diabaikan, lanjut): {ex!r}")
            time.sleep(0.5)

    _sweep_stripe_tabs(force=True)
    print(f"Selesai. Total: lesson={stats['std']} tutorial={stats['tut']} "
          f"minigame={stats['mini']} phaser={stats['phaser']} ocr={stats['ocr']} "
          f"hold={stats['hold']} video={stats['video']} popup={stats['popup']}")


if __name__ == "__main__":
    main_loop()
