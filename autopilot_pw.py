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


# Log file otomatis: semua output console TETAP tampil, tapi juga tersalin
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


try:
    _LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "bot.log")
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


if HAVE_HOTKEY:
    try:
        _kb.add_hotkey("f9", _toggle_pause)
        _kb.add_hotkey("f10", _cycle_speed)
        _kb.add_hotkey("f11", _stop_bot)
    except Exception:
        HAVE_HOTKEY = False

BRAVE_BINARY = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
DEBUG_ADDRESS = "127.0.0.1:9222"
STALL_WARN_SECONDS = 90      # tidak ada aksi selama ini -> dump debug
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
    """URL ASLI halaman via evaluate. TERBUKTI LIVE: page.url Playwright
    bisa STALE - tab yang isinya sudah m.stripe.network masih melaporkan
    URL edclub. location.href tidak pernah bohong."""
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
        with urllib.request.urlopen(f"http://{DEBUG_ADDRESS}/json/version", timeout=2) as r:
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


def _tanya_tutup(nama, pid):
    if _confirmer is not None:
        try:
            return bool(_confirmer(nama, pid))
        except Exception:
            return False
    try:
        r = input(f"  Port 9222 dipakai oleh {nama} (PID {pid}). Tutup paksa? [y/N] ")
        return r.strip().lower().startswith("y")
    except Exception:
        return False


def _bebaskan_port():
    """Port 9222 dipakai proses non-Brave -> identifikasi PEMEGANG ASLINYA
    (bisa bukan browser sama sekali, mis. Adobe), minta izin user sebelum
    taskkill. Edge/msedge tetap ditutup langsung (aman)."""
    pemegang = _siapa_pegang_port()
    if not pemegang:
        return False
    for pid, nama in pemegang:
        nl = nama.lower()
        if "brave" in nl:
            continue
        if "edg" in nl:
            print(f"  -> {nama} (PID {pid}) memegang port 9222, menutup paksa...")
        else:
            print(f"  -> port 9222 dipakai {nama} (PID {pid})")
            if not _tanya_tutup(nama, pid):
                print(f"     tidak jadi ditutup - port tetap dipakai {nama}.")
                continue
            print("     menutup paksa atas izin user...")
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, timeout=8)
        except Exception:
            pass
    time.sleep(2)
    return True


def _siapa_pegang_port():
    pids = []
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"],
                             capture_output=True, text=True, timeout=8).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[1].endswith(":9222") and parts[4].isdigit():
                pids.append(int(parts[4]))
    except Exception:
        pass
    hasil = []
    for pid in set(pids):
        try:
            t = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                               capture_output=True, text=True, timeout=5).stdout
            for ln in t.splitlines():
                if ".exe" in ln.lower() and str(pid) in ln:
                    hasil.append((pid, ln.split()[0]))
                    break
        except Exception:
            pass
    return hasil


def _find_brave():
    kandidat = [
        BRAVE_BINARY,
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
    ]
    for p in kandidat:
        if p and os.path.isfile(p):
            return p
    return None


def _brave_sudah_jalan():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq brave.exe"],
                             capture_output=True, text=True, timeout=5).stdout
        return "brave.exe" in out.lower()
    except Exception:
        return False


def siapkan_browser():
    """Pastikan ada Brave debug di port 9222. Port yang dipakai aplikasi
    lain (Adobe/WebView) ditangani dengan izin user, bukan asal ditutup."""
    browser_on_port = _cek_debug_port()

    if "Edg" in browser_on_port:
        # Bisa Edge betulan, BISA JUGA WebView2 milik aplikasi lain (mis.
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

    if not browser_on_port:
        if _siapa_pegang_port():
            print("Port 9222 dipakai proses lain (bukan browser debug)...")
            _bebaskan_port()
            browser_on_port = _cek_debug_port()
        if not browser_on_port:
            if _brave_sudah_jalan():
                print("Brave jalan TANPA mode debug. Tutup semua Brave, jalankan ulang program.")
                sys.exit(1)
            exe = _find_brave()
            if not exe:
                print("Brave tidak ditemukan. Install Brave dulu.")
                sys.exit(1)
            print("Port 9222 kosong: membuka Brave otomatis dengan mode debug...")
            subprocess.Popen([exe, "--remote-debugging-port=9222"], close_fds=True)
            for _ in range(30):
                time.sleep(0.5)
                if _cek_debug_port().startswith("Chrome"):
                    break

    print("Menyambungkan Playwright ke Brave...")
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(f"http://{DEBUG_ADDRESS}")
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
    # Tab edclub sisa sesi lalu sering MATI (layar gelap / ter-bawa ke
    # Stripe checkout) dan malah menang pemilihan tab - bot lalu nyangkut
    # 20-25 detik sebelum recovery menyalakannya. Solusi: periksa
    # kesehatan tiap tab, ambil SATU terbaik, tutup sisanya otomatis.
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
        # Kalau tidak ada tab edclub: buka tab baru. PERNAH GAGAL live:
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
        print(f"Gagal menyambung ke Brave: {str(e)[:100]}")
        print("Coba jalankan ulang program.")
        sys.exit(1)
    print(f"Terhubung! Tab aktif: {PAGE.url}")
    if not OCR_AVAILABLE:
        print("Catatan: 'winocr' tidak ada -> fallback OCR nonaktif (pip install winocr).")
    return True


def disconnect():
    """Putuskan koneksi Playwright dan reset cache global. WAJIB dipanggil
    dari thread yang menjalankan connect(). Tanpa ini, restart dari GUI
    memakai objek Playwright milik thread lama yang sudah mati ->
    error "cannot switch to a different thread"."""
    global pw, browser, PAGE
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

// PENTING: teks lesson diambil HANYA dari token _clr (belum diketik).
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
        else if (txt === '\u00A0' || txt === ' ') result.push(' ');
        else {
            const clean = txt.replace(/\r?\n|\r/g, '');
            if (clean.length > 0) result.push(clean[0]);
        }
    }
    const t = result.join('');
    if (t.replace(/\s/g, '').length > 0) out.std = t;
}

if (!out.std) {
    // Tutorial boxed: hanya ekstrak RUN PENDING (trailing run dengan tanda
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
        // sertakan run PENDEK (<=2) sebelum trailing run = karakter AKTIF
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
// Modal premium terlihat? JANGAN klik tombol lanjut apa pun - di level
// premium klik "continue" edclub MEMBAWA TAB ke Stripe Checkout
// (terbukti live di 2968: page.url tetap edclub, isi = m.stripe.network).
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
        // JANGAN klik tombol "continue/next" di dalam kontainer premium/
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
// mouse asli, atau {zombie:true} kalau modal fullscreen TANPA X (iframe
// checkout Stripe sudah mengambil alih). TERBUKTI LIVE di 2968: klik X
// -> edclub otomatis lanjut ke lesson berikutnya (perilaku yang sama
// dengan popup premium di akun teman: tutup = lanjut level).
// CATATAN: JANGAN blokir request Stripe - modal yang checkout-nya gagal
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


def close_overlays_all_frames():
    """Jalankan penutup pop-up di semua frame. Return jumlah aksi."""
    if time.time() < _repeat_click["until"]:
        return 0
    total = 0
    for fr in all_frames():
        if not _frame_edclub(fr):
            continue
        taken = run_js(OVERLAY_JS, fr)
        if taken:
            print(f"[Pop-up] {frame_label(fr)}: {'; '.join(taken[:3])}")
            total += len(taken)
            first = taken[0]
            if first == _repeat_click["label"]:
                _repeat_click["count"] += 1
                if _repeat_click["count"] >= 3:
                    # Klik JS x3 tanpa hasil = pop-up premium butuh gesture
                    # sungguhan. Bahaya terbukti (live): klik mouse di area
                    # iframe Stripe yang menutupi layar = TAB TERBAWA ke
                    # checkout stripe -> bot nyangkut. Maka: hanya klik
                    # elemen tutup yang 1) selektornya presisi (bukan
                    # sembarang class mengandung huruf 'x') dan 2) titik
                    # tengahnya BENAR-BENAR di atas elemen itu (cek
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
        for fr in all_frames():
            if not _frame_edclub(fr):
                continue
            hint = run_js(MODAL_HINT_JS, fr)
            if hint and hint.get("achievement"):
                if run_js(ESC_FALLBACK_JS, fr):
                    print("[Pop-up] modal tanpa tombol tutup, kirim ESC "
                          "(achievement)")
                    total += 1
                break
            # JANGAN ESC modal premium: ESC pernah mengkonsumsi modal
            # premium sekali-per-page-load TANPA memajukan level (log
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


_loop_overhead = 0.030   # estimasi overhead verifikasi per karakter (EWMA)
_last_char_delay = 0.0


def _char_delay(slow=False):
    """Jeda per karakter dari target WPM (1 kata = 5 karakter).
    Delay dikurangi overhead verifikasi yang terukur (loop mengukur sendiri
    via _loop_overhead) supaya LAJU AKHIR benar-benar mendekati target:
    140 wpm = ~86 ms/kar total, 200 = 60, 85 = 141.
    slow=True (tutorial boxed): engine butuh waktu animasi per karakter -
    jangan turun di bawah cadence yang terbukti aman (0.14-0.24 s)."""
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
    """Ketik via CDP. slow=True untuk tutorial boxed (animasi scroll-garis)."""
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
                # WAJIB type() bukan press(): engine butuh event keypress/input
                # penuh untuk spasi - press() hanya kirim down/up = ditandai salah
                PAGE.keyboard.type(" ")
                time.sleep(_char_delay(slow))
            else:
                PAGE.keyboard.type(char)
                time.sleep(_char_delay(slow))
        except Exception:
            return False
    return True


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
    for fr in all_frames():
        if not _frame_edclub(fr):
            continue
        res = run_js(ANTI_PAUSE_JS, fr)
        if res == "banner":
            clicked = True
    return clicked


QUIET_ALIVE_JS = r"""
// Versi TANPA KLIK: hanya patch fokus + dispatch event. Aman dipakai
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
    else if (txt === '\u00A0' || txt === ' ') out.push(' ');
    else { const c = txt.replace(/\r?\n|\r/g, ''); if (c) out.push(c[0]); }
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
    else if (txt === '\u00a0' || txt === ' ') out.push(' ');
    else { const c = txt.replace(/\r?\n|\r/g, ''); if (c) out.push(c[0]); }
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
// Klik banner "Start Typing" SEKALI di awal lesson (state pause awal).
// JANGAN pernah mengklik apa pun saat sedang mengetik (bisa reset lesson!).
const b = document.querySelector('.drop-banner');
if (b && (b.offsetWidth || b.offsetHeight)) {
    try { b.click(); return 'klik'; } catch (e) {}
}
return null;
"""


_std_last_rem = None
_std_attempts = 0


def handle_standard(frame, text):
    global last_typed_text, last_action_time, _std_last_rem, _std_attempts
    # Level terkunci premium: modal premium menutupi lesson, input mati.
    # Dulu bot mencoba mengetik 3x (gagal, buang waktu) bahkan sempat
    # mengklik tombol CTA premium yang membawa ke Stripe Checkout.
    # Sekarang: langsung lewati level via tombol lanjut (klik mouse asli).
    for fr in all_frames():
        hint = run_js(MODAL_HINT_JS, fr)
        if hint and hint.get("premium"):
            print("[Premium] level terkunci premium - lewati via tombol lanjut")
            try:
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
        # KETIK PER-KARAKTER TERVERIFIKASI (prinsip: TIDAK BOLEH SALAH):
        # Karakter berikutnya TIDAK PERNAH dikirim sebelum karakter saat ini
        # terverifikasi dikonsumsi dengan benar oleh engine lesson.
        # - salah tidak pernah berantai: deteksi terjadi 1 karakter, bukan 20.
        # - kalau konsumsi tidak persis (keystroke hilang / DOM berganti /
        #   banner pause), ketikan BERHENTI dan realign ke DOM - tidak
        #   pernah lanjut berdasarkan asumsi.
        # - modifier (Shift dll.) dilepas dulu: sisa modifier = karakter
        #   salah pada lesson berikutnya.
        # - karakter yang ditandai salah (_err) segera di-Backspace SEKALI;
        #   kalau situs tidak mengizinkan, dicatat dan lanjut (maks 1 char).
        # PENTING: SELAMA MENGETIK tidak ada klik apa pun - klik di tengah
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
                # 1 karakter tertandai salah - coba hapus SEKARANG
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
                # BISA berarti selesai, TAPI juga "baris berikut belum
                # muncul di DOM" (render progresif). Jangan langsung anggap
                # selesai: tunggu grace, ketik ulang TIDAK boleh (Enter
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
                # karakter TIDAK terkonsumsi: jangan kirim apapun lagi dulu.
                # Kasus umum: DOM butuh sesaat untuk memproses keystroke.
                stall += 1
                time.sleep(0.05)
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
                if stall == 2:
                    rem = read_remaining(frame) or rem
                    if run_js(START_BANNER_JS, frame):
                        print("[Standard] banner pause muncul, diklik")
                        time.sleep(0.4)
                        rem = read_remaining(frame) or rem
                elif stall >= 5:
                    print("[Standard] ketikan tidak masuk, lanjut transisi")
                    break
                time.sleep(0.15)
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

    # Tunggu transisi post-lesson. PENTING: keluar SEGERA begitu URL
    # berganti (level baru) - intro/skor->level baru tidak pernah
    # menghasilkan state std/mini/tut, dulu loop ini burn deadline penuh
    # (10+8 dtk) padahal level berikutnya sudah siap dikerjakan.
    entry_url = PAGE.url
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


# SISA teks tutorial boxed, TANPA mengenal nama class edclub:
# engine boxed pasti menandai karakter selesai lewat class (di span, di
# .boxed-char, atau di .boxed-line induknya). Trik: gabungkan semua class
# tiap karakter jadi "tanda", lalu ambil RUN TERAKHIR yang tandanya sama
# dengan tanda karakter TERAKHIR (= run karakter yang masih pending).
# Ditambah info tanda: kalau SEMUA karakter satu tanda & beda dari tanda
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
// sertakan run PENDEK (<=2) sebelum trailing run = karakter AKTIF
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
    # POLA LEVEL = LESSON STANDAR dengan UI lain (kesimpulan user, benar):
    # ketik urutan penuh SEKALI dengan kecepatan NORMAL (140 wpm) - transisi
    # animasi tidak perlu selesai untuk bisa lanjut. KEUALI di AWAL level:
    # tepat setelah intro, ada jendela mati saat transisi - ketikan pertama
    # jatuh ke ruang kosong. Tunggu layar stabil (bacaan sisa sama 2x,
    # maks ~2 dtk) sebelum mulai. Resume hanya saat re-entry dengan suffix
    # jujur. TANPA jalur input tambahan apapun (klik layar/event sintetis
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
    modal -> None. PENTING: modal X cuma muncul ~3 detik di awal level,
    lalu menghilang sendiri dan game jadi beku - jadi ini harus
    dipanggil SERING di awal level (watch window)."""
    for fr in all_frames():
        if not _frame_edclub(fr):
            continue
        pm = run_js(PREMIUM_MODAL_JS, fr)
        if pm and pm.get("x") is not None:
            try:
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
    # Fallback: tombol berteks lanjut (di LUAR kontainer premium/iframe,
    # titik klik terverifikasi elementFromPoint) -> klik mouse ASLI.
    for fr in all_frames():
        if not _frame_edclub(fr):
            continue
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
                    # selesai. GUARD: core.words bisa BUKAN array di sebagian
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
                    # start (klik canvas) - coba SEKALI per URL; (b) game
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
        // WAJIB berlabel: elemen "aktif" TANPA teks bukan tombol keyboard -
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
// cukup LOMPAT ke akhir + play supaya event 'ended' menyala - tidak perlu
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

INTRO_READY_JS = r"""
// Sinyal layar siap menerima ketikan: tombol keyboard layar untuk karakter
// yang diminta sedang di-highlight (menyala oranye) oleh engine. Sebelum
// highlight itu muncul, keystroke TIDAK didengar (tekanan terlalu dini =
// hilang; itulah 'coba 1-5' di log + tombol tetap oranye menunggu).
const sels = ['[class*="key"][class*="highlight"]', '[class*="key"][class*="active"]',
              '.key.highlight', '.keyboard .next'];
for (const sel of sels) {
    for (const el of document.querySelectorAll(sel)) {
        if (el.offsetWidth || el.offsetHeight) return true;
    }
}
return false;
"""

_intro_sig = None
_intro_attempts = 0
_intro_flow = False   # True = alur intro berjalan (f->j->d->k di level yang sama)


SKIP_CLICK_JS = r"""
// Cari tombol skip berdasarkan TEKS (bukan class - class edclub berubah-ubah).
for (const el of document.querySelectorAll('button, a, [role="button"], span[onclick], div[onclick]')) {
    const t = (el.innerText || el.textContent || '').trim().toLowerCase();
    if (!t || t.length > 14) continue;
    if (!(t === 'skip' || t === 'lewati' || t.startsWith('skip') || t.startsWith('lewati'))) continue;
    if (!(el.offsetWidth || el.offsetHeight)) continue;
    try { el.click(); return t; } catch (e) {}
}
return null;
"""


def _click_active_screen_key():
    """Klik mouse SUNGGUHAN (CDP) tombol keyboard layar yang sedang
    di-highlight, di SEMUA frame. Klik JS tidak dipercaya engine; ketikan
    juga kadang tidak masuk di layar intro. Hanya klik elemen BERLABEL
    singkat - elemen 'aktif' tanpa teks bukan tombol keyboard (pernah
    menavigasi bot ke halaman daftar level!)."""
    for fr in all_frames():
        for sel in ('[class*="key"][class*="highlight"]',
                    '[class*="key"][class*="active"]'):
            try:
                locs = fr.locator(sel)
                for i in range(min(locs.count(), 6)):
                    el = locs.nth(i)
                    txt = (el.inner_text(timeout=500) or "").strip()
                    if txt and len(txt) <= 2:
                        el.click(timeout=1500)
                        print(f"[Intro] klik tombol keyboard layar {txt!r}")
                        return True
            except Exception:
                continue
    return False


def _click_intro_skip():
    """Layar intro punya tombol skip - pakai kalau ketikan tidak mau masuk.
    Cari berdasarkan teks di semua frame; klik JS dulu, lalu klik mouse
    sungguhan sebagai cadangan."""
    for fr in all_frames():
        res = run_js(SKIP_CLICK_JS, fr)
        if res:
            print(f"[Intro] langkah di-skip via tombol {res!r}")
            return True
    for fr in all_frames():
        try:
            for el in (fr.get_by_text("Skip", exact=True).all() or [])[:4]:
                try:
                    el.click(timeout=1500)
                    print("[Intro] langkah di-skip via klik mouse 'Skip'")
                    return True
                except Exception:
                    continue
        except Exception:
            continue
    return False


def _synth_key(fr, ch):
    """Fallback saluran ketik: dispatch KeyboardEvent sintetis (keydown +
    keypress + keyup) langsung di dokumen frame. CDP kadang tidak masuk
    di layar intro; beberapa engine edclub menerima event sintetis."""
    try:
        fr.evaluate("""(ch) => {
            let code, kc;
            if (ch === 'Enter') { code = 'Enter'; kc = 13; }
            else if (ch === ' ') { code = 'Space'; kc = 32; }
            else { code = 'Key' + ch.toUpperCase(); kc = ch.toUpperCase().charCodeAt(0); }
            const mk = (type) => new KeyboardEvent(type, {
                key: ch, code: code, keyCode: kc, which: kc,
                bubbles: true, cancelable: true});
            const kp = new KeyboardEvent('keypress', {
                key: ch, code: code, keyCode: kc, which: kc, charCode: kc,
                bubbles: true, cancelable: true});
            for (const t of [window, document, document.body]) {
                if (!t) continue;
                try { t.dispatchEvent(mk('keydown')); } catch (e) {}
                try { t.dispatchEvent(kp); } catch (e) {}
                try { t.dispatchEvent(mk('keyup')); } catch (e) {}
            }
            return true;
        }""", ch)
        return True
    except Exception:
        return False


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
        # POLA TUTORIAL (terbukti): tunggu layar STABIL dulu sebelum menekan
        # (jendela mati transisi; menekan terlalu dini = keystroke hilang).
        # Layar PERTAMA di sebuah level: jendela matinya panjang (habis load
        # level) -> 2x baca @0.25s. Layar BERIKUTNYA dalam alur intro yang
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
        # SATU tekanan bersih. Tekanan ekstra saat layar sudah pindah =
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
#  has_progress = pelajaran yang harus dikerjakan berikutnya)
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
    """Buka ulang PELAJARAN YANG SAMA di tab baru, tutup tab mati.
    Versi lama selalu ke daftar pelajaran lalu klik baris pertama yang
    belum dikerjakan - itu membuat bot melompat ke unit lain dan
    kelihatan seperti 'main level acak'. Fall back ke daftar hanya jika
    URL lesson tidak diketahui."""
    global PAGE, last_typed_text, last_url, _last_recovery, last_action_time
    _last_recovery = time.time()
    print("[RECOVERY] Halaman macet/kosong, membuka ulang pelajaran...")
    try:
        newpg = PAGE.context.new_page()
    except Exception as e:
        print(f"[RECOVERY] gagal bikin tab: {str(e)[:80]}")
        return False

    target = last_url if (last_url and ".play" in last_url) else None
    if target:
        n = _recovery_counts.get(target, 0)
        _recovery_counts[target] = n + 1
        if n >= 2:
            # Lesson ini sudah 2x dimuat ulang tetap mati = level rusak
            # (contoh: layar gelap premium macam level 106). Pilih lesson
            # berikutnya SESUAI URUTAN DAFTAR - nomor URL edclub TIDAK
            # berurutan (setelah 189 langsung 2959), jangan hitung N+1.
            try:
                newpg.close()
            except Exception:
                pass
            if _skip_to_next_lesson("recovery berulang, level rusak"):
                return True
            return False
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


def _wait_play_url(newpg):
    for _ in range(16):
        time.sleep(0.5)
        try:
            u = newpg.evaluate("() => location.href")
        except Exception:
            u = None
        if u and ".play" in u and _is_edclub_url(u):
            return u
    return None


def _goto_next_lesson_in_list(newpg, current_url):
    """Buka daftar pelajaran dan klik pelajaran berikutnya SESUAI URUTAN
    KURSUS. NOMOR URL EDCLUB TIDAK BERURUTAN (terbukti: setelah 189.play
    situs sendiri lanjut ke 2959.play) - JANGAN hitung N+1. Klik baris
    pertama yang belum dikerjakan; kalau itu malah lesson yang baru
    ditinggalkan (level rusak) atau lesson yang sudah ditandai rusak,
    klik baris TEPAT SETELAH baris itu. Return URL .play, None jika gagal."""
    cur = _lesson_id(current_url)
    row = 0
    for _ in range(6):
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
    # Coba di TAB YANG SAMA dulu (tanpa buka tab baru - user terganggu
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


def main_loop():
    global PAGE, last_url, last_debug_dump, last_action_time, _last_recovery
    global STATUS_URL, _login_notice, _nav_try, _intro_flow, _premlock_since
    if PAGE is None:
        try:
            connect()
        except SystemExit:
            return
    while True:
        try:
            if STOP:
                print("Bot dihentikan.")
                break
            if PAUSED:
                time.sleep(0.2)
                continue

            # anti-pause ringan tiap iterasi (banner "Start Typing dll.")
            keep_alive_frames()
            _sweep_stripe_tabs()

            url = PAGE.url
            # page.url Playwright bisa STALE: tab berisi Stripe checkout
            # masih melaporkan URL edclub (terbukti live). Percayai
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
            if not _is_edclub_url(url):
                # tab bisa ter-bawa navigasi ke Stripe checkout (dibuktikan
                # live: klik di area iframe premium = top-level navigation).
                # Tutup tab stripe yang menganggur, lalu cari/buat tab edclub.
                try:
                    for pg in list(browser.contexts[0].pages):
                        h = (urlparse(_real_url(pg)).hostname or "").lower()
                        if "stripe" in h and pg is not PAGE:
                            pg.close()
                            print("[TAB] tab Stripe sisa ditutup")
                except Exception:
                    pass
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
                    # Tidak ada tab edclub sama sekali. Buka TAB BARU (bukan
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
            if "login" in low or "signin" in low or "sign-in" in low or "signup" in low:
                # belum login: jangan spam recovery, tunggu user login manual
                if time.time() - _login_notice > 30:
                    _login_notice = time.time()
                    print("[LOGIN] Halaman login terdeteksi. Login dulu di "
                          "Brave, bot menunggu di sini...")
                time.sleep(2)
                continue

            if url != last_url:
                # level baru: cooldown Phaser dari game sebelumnya tidak
                # berlaku lagi (dulu bikin minigame berikutnya tunda 20 dtk)
                _phaser_cooldown["until"] = 0.0
                _phaser_freeze["url"] = ""
                _phaser_freeze["count"] = 0
                _phaser_freeze["clicked"] = False
                _intro_flow = False   # layar intro pertama level ini = settle penuh
                _premlock_since = 0.0
                if last_url:
                    print(f"[PROGRES] {last_url.split('/')[-1]} -> {url.split('/')[-1]}  "
                          f"(std={stats['std']} tut={stats['tut']} mini={stats['mini']} "
                          f"phaser={stats['phaser']} ocr={stats['ocr']} hold={stats['hold']} "
                          f"video={stats['video']} popup={stats['popup']})")
                last_url = url

            # Watch window: klik X modal premium SEBELUM penutup pop-up
            # dan handler mana pun. TERBUKTI LIVE: modal premium edclub
            # hanya SEKALI per page-load; ESC/klik salah dari penutup
            # pop-up pernah MENGKONSUMSI modal itu (log 08:02: 'kirim ESC
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
                    # HEARTBEAT: bot tidak boleh pernah diam tanpa kabar.
                    # (dulu: state unknown = sunyi total, kelihatan mati)
                    if stalled > 10 and time.time() - last_debug_dump > 10:
                        last_debug_dump = time.time()
                        print(f"[TUNDA] tidak ada aktivitas {stalled:.0f}s di "
                              f"{url.split('/')[-1]} - dumping state...")
                        dump_debug_info()
                    # Level premium yang modal-nya sudah tertutup tapi layar
                    # masih gelap & tak ada kerjaan (edclub bug, level 106):
                    # SATU klik tombol lanjut langsung ke lesson berikutnya
                    # (perilaku terverifikasi user). Coba sebelum recovery.
                    if stalled > 6:
                        prem = False
                        for fr2 in all_frames():
                            h = run_js(MODAL_HINT_JS, fr2)
                            if h and h.get("premium"):
                                prem = True
                                break
                        if prem:
                            # TANPA Enter (form checkout bisa menangkap Enter)
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
                    if stalled > 6 and _switch_to_playable_tab():
                        continue
                    if stalled > 12 and time.time() - _last_recovery > 25:
                        # halaman kemungkinan mati/kosong -> pulihkan otomatis
                        if not recover_and_restart_lesson():
                            _last_recovery = time.time()

            time.sleep(0.15)

        except KeyboardInterrupt:
            print("Dihentikan manual.")
            break
        except Exception:
            time.sleep(0.5)

    _sweep_stripe_tabs(force=True)
    print(f"Selesai. Total: lesson={stats['std']} tutorial={stats['tut']} "
          f"minigame={stats['mini']} phaser={stats['phaser']} ocr={stats['ocr']} "
          f"hold={stats['hold']} video={stats['video']} popup={stats['popup']}")


if __name__ == "__main__":
    main_loop()
