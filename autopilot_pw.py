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
import io
import json
import os
import random
import re
import subprocess
import sys
import time

from PIL import Image
from playwright.sync_api import sync_playwright

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

# ---------------------------------------------------------------------------
# Kontrol: hotkey global (F9 pause, F10 kecepatan, F11 stop)
# ---------------------------------------------------------------------------

PAUSED = False
STOP = False
SPEEDS = [(1.0, "NORMAL"), (0.45, "CEPAT"), (1.8, "SANTAI")]
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


def _cek_debug_port():
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://{DEBUG_ADDRESS}/json/version", timeout=2) as r:
            return json.loads(r.read().decode()).get("Browser", "")
    except Exception:
        return ""


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
    """Pastikan ada Brave debug di port 9222. Kill Edge bila perlu."""
    browser_on_port = _cek_debug_port()

    if "Edg" in browser_on_port:
        print("Port 9222 dipegang proses berbasis Edge, mencari prosesnya...")
        for pid, nama in _siapa_pegang_port():
            print(f"  -> {nama} (PID {pid}) memegang port 9222, menutup paksa...")
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                               capture_output=True, timeout=8)
            except Exception:
                pass
        time.sleep(2)
        browser_on_port = _cek_debug_port()
        if "Edg" in browser_on_port:
            print("MASIH terkunci oleh Edge. Task Manager -> End task semua Edge,")
            print("lalu jalankan ulang program.")
            sys.exit(1)
        print("Port 9222 berhasil dibebaskan.")

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
    for pg in ctx.pages:
        if "edclub.com" in pg.url or "typingclub.com" in pg.url:
            page = pg
            break
    if page is None:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        print("Tab edclub belum ada. Buka edclub.com di Brave, bot akan menunggu.")
    return pw, browser, page


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
    pw, browser, PAGE = siapkan_browser()
    print(f"Terhubung! Tab aktif: {PAGE.url}")
    if not OCR_AVAILABLE:
        print("Catatan: 'winocr' tidak ada -> fallback OCR nonaktif (pip install winocr).")
    return True


# ---------------------------------------------------------------------------
# Util frame & JS (Playwright: semua frame otomatis tersedia)
# ---------------------------------------------------------------------------

def all_frames():
    """Semua frame halaman (main + semua iframe, termasuk cross-origin)."""
    try:
        return list(PAGE.frames)
    except Exception:
        return [PAGE.main_frame]


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
    const wraps = document.querySelectorAll('.boxed-line > span');
    if (wraps.length && wraps.length < 200) {
        const chars = [];
        for (const sp of wraps) {
            const chEl = sp.querySelector('.boxed-char');
            if (!chEl) continue;
            let c = (chEl.textContent || '').slice(0, 1);
            if (c === '\u00A0' || c === ' ') c = ' ';
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
    if (!introScreen) {
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

{
    const want = {};
    for (const t of NEXT_TEXTS) want[t] = true;
    outer3:
    for (const el of document.querySelectorAll('button, a, [role="button"], [class*="btn" i], [class*="button" i]')) {
        let txt = '';
        try { txt = (el.innerText || '').trim().toLowerCase(); } catch (e) {}
        if (!txt || txt.length > 14 || !want[txt] || !visible(el)) continue;
        try { if (el.closest('.typable, .token_unit, .boxed-typing-lines, .boxed-line, .TPGAME')) continue; } catch (e) {}
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

_repeat_click = {"label": "", "count": 0, "until": 0.0}


def close_overlays_all_frames():
    """Jalankan penutup pop-up di semua frame. Return jumlah aksi."""
    if time.time() < _repeat_click["until"]:
        return 0
    total = 0
    for fr in all_frames():
        taken = run_js(OVERLAY_JS, fr)
        if taken:
            print(f"[Pop-up] {frame_label(fr)}: {'; '.join(taken[:3])}")
            total += len(taken)
            first = taken[0]
            if first == _repeat_click["label"]:
                _repeat_click["count"] += 1
                if _repeat_click["count"] >= 4:
                    _repeat_click["until"] = time.time() + 25
                    _repeat_click["count"] = 0
                    print(f"[Pop-up] '{first}' berulang tanpa hasil, jeda 25 detik")
            else:
                _repeat_click["label"] = first
                _repeat_click["count"] = 1
            break
    if total == 0:
        for fr in all_frames():
            hint = run_js(MODAL_HINT_JS, fr)
            if hint and (hint.get("achievement") or hint.get("premium")):
                if run_js(ESC_FALLBACK_JS, fr):
                    print(f"[Pop-up] modal tanpa tombol tutup, kirim ESC "
                          f"({'achievement' if hint.get('achievement') else 'premium'})")
                    total += 1
                break
    return total


# ---------------------------------------------------------------------------
# Mesin ketik (CDP via Playwright - tidak butuh fokus jendela OS)
# ---------------------------------------------------------------------------


def type_chars(text, max_chars=None, slow=False):
    """Ketik via CDP. slow=True untuk tutorial boxed (animasi scroll-garis)."""
    lo, hi = (0.13, 0.24) if slow else (0.05, 0.10)
    factor = SPEEDS[SPEED_IDX][0]
    for char in (text if max_chars is None else text[:max_chars]):
        while PAUSED and not STOP:
            time.sleep(0.15)
        if STOP:
            return False
        try:
            if char == "\n":
                PAGE.keyboard.press("Enter")
                time.sleep(0.08)
            elif char == "\t":
                PAGE.keyboard.press("Tab")
                time.sleep(random.uniform(lo, hi) * factor)
            elif char == " ":
                # WAJIB type() bukan press(): engine butuh event keypress/input
                # penuh untuk spasi - press() hanya kirim down/up = ditandai salah
                PAGE.keyboard.type(" ")
                time.sleep(random.uniform(lo, hi) * factor)
            else:
                PAGE.keyboard.type(char)
                time.sleep(random.uniform(lo, hi) * factor)
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


def focus_frame(frame):
    """Fokus internal frame (bukan OS): window.focus + klik CDP di body."""
    run_js("try{window.focus();if(document.body&&document.body.focus)document.body.focus();}catch(e){}", frame)
    try:
        frame.locator("body").first.click(timeout=1500)
    except Exception:
        pass


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
        time.sleep(0.25)
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
        time.sleep(0.6)
        rem = read_remaining(frame) or ""

    typed_any = False
    try:
        if hold_key:
            PAGE.keyboard.down(hold_key)
            time.sleep(0.15)
        # KETIK SELF-CORRECTING: setiap potong, re-ekstrak sisa teks (_clr)
        # lalu ketik 20 karakter pertamanya. PENTING: SELAMA MENGETIK tidak
        # ada klik apa pun - klik di tengah ketikan bisa me-reset lesson.
        CHUNK = 20
        stall = 0
        while True:
            if STOP:
                break
            while PAUSED and not STOP:
                time.sleep(0.15)
            keep_alive_quiet(frame)
            if not rem:
                break
            if not type_chars(rem[:CHUNK]):
                break
            typed_any = True
            time.sleep(0.25)
            rem2 = read_remaining(frame)
            if rem2 is None or rem2 == "":
                break  # tidak ada token tersisa = lesson selesai
            if len(rem2) < len(rem):
                rem = rem2
                stall = 0
            else:
                stall += 1
                if stall >= 3:
                    print("[Standard] ketikan tidak masuk, lanjut transisi")
                    break
                # coba klik banner sekali sebagai pemulihan (lesson ter-pause)
                if stall == 2 and run_js(START_BANNER_JS, frame):
                    print("[Standard] banner pause muncul, diklik")
                    rem = read_remaining(frame) or rem
                time.sleep(0.5)
            esc_modals_only(frame)
    finally:
        if hold_key:
            try:
                PAGE.keyboard.up(hold_key)
            except Exception:
                pass
    if not typed_any:
        return False
    last_typed_text = text
    stats["std"] += 1
    last_action_time = time.time()

    deadline = time.time() + 10
    while time.time() < deadline:
        if close_overlays_all_frames():
            time.sleep(0.6)
            continue
        state, _, _ = detect_all_frames()
        if state == "score":
            if press_enter_guarded():
                print("[Skor] Enter ditekan")
            time.sleep(0.8)
        if state in ("std", "mini", "tut"):
            break
        time.sleep(0.25)

    deadline = time.time() + 8
    while time.time() < deadline:
        state, _, _ = detect_all_frames()
        if state != "unknown":
            break
        time.sleep(0.2)
    last_action_time = time.time()
    return True


# ---------------------------------------------------------------------------
# Tutorial boxed
# ---------------------------------------------------------------------------

_tut_sig = None
_tut_attempts = 0


def handle_tutorial(frame, data):
    global _tut_sig, _tut_attempts, last_action_time
    text = data.get("text", "")
    if not text:
        return False
    if text == _tut_sig and _tut_attempts >= 4:
        return False
    if text != _tut_sig:
        _tut_sig = text
        _tut_attempts = 0
    _tut_attempts += 1
    focus_frame(frame)
    print(f"[Tutorial] ketik {text!r} (coba {_tut_attempts})")
    if not type_chars(text, slow=True):
        return False
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
try {
    for (const w of c.words) {
        if (!w || !w.char_list || w.completed) continue;
        const ch = w.char_list[w.index || 0] || w.char_list[0];
        if (ch && cands.indexOf(ch) < 0) cands.push(ch);
    }
} catch (e) {}
if (!cands.length && c.cur_char) cands.push(c.cur_char.chr);
return {fed: false, cands: cands.slice(0, 8), idx: c.cur_char_index,
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


def handle_phaser_minigame():
    global last_action_time
    if time.time() < _phaser_cooldown["until"]:
        return False
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
                if stalled >= 4 and not probed:
                    # cur_char tidak diterima -> game multi-kata (pilih bebas).
                    # Coba kandidat huruf pertama dari tiap kata yang belum selesai.
                    probed = True
                    try:
                        info = fr.evaluate(
                            "(arg) => {" + PHASER_PROBE_JS + "}", None)
                    except Exception:
                        info = None
                    cands = (info or {}).get("cands") or []
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
                    print("[Minigame/Phaser] indeks tidak maju, jeda 20 detik")
                    _phaser_cooldown["until"] = time.time() + 20
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
        try { el.click(); } catch (e) {}
        return {key: t, sel: sel};
    }
}
return null;
"""


def click_screen_keyboard():
    global last_action_time
    for fr in all_frames():
        hit = run_js(SCREENKEY_JS, fr)
        if hit:
            print(f"[Keyboard-layar] klik '{hit.get('key')}' ({hit.get('sel')})")
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
try { v.playbackRate = 16; } catch (e) {}
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
        print(f"[Video] {frame_label(fr)}: diputar cepat 16x & dilompat ke akhir")
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


def handle_intro_steps():
    global _intro_sig, _intro_attempts, last_action_time
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
        if sig == _intro_sig:
            _intro_attempts += 1
            if _intro_attempts > 6:
                continue
        else:
            _intro_sig = sig
            _intro_attempts = 1
        focus_frame(fr)
        print(f"[Intro] instruksi: {res['type']} {key!r} (coba {_intro_attempts})")
        try:
            PAGE.keyboard.press(key)
        except Exception:
            return False
        stats["intro"] += 1
        last_action_time = time.time()
        time.sleep(0.8)
        return True
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


def recover_and_restart_lesson():
    """Buka tab baru ke daftar pelajaran, klik pelajaran berikutnya, tutup tab mati."""
    global PAGE, last_typed_text, last_url, _last_recovery, last_action_time
    _last_recovery = time.time()
    print("[RECOVERY] Halaman macet/kosong, membuka ulang pelajaran...")
    try:
        newpg = PAGE.context.new_page()
    except Exception as e:
        print(f"[RECOVERY] gagal bikin tab: {str(e)[:80]}")
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
        return False
    print(f"[RECOVERY] membuka pelajaran: {clicked}")
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


# ---------------------------------------------------------------------------
# Loop utama
# ---------------------------------------------------------------------------

last_typed_text = ""
last_action_time = time.time()
last_debug_dump = 0.0
last_url = ""
stats = {"std": 0, "mini": 0, "ocr": 0, "popup": 0, "hold": 0, "uikey": 0, "tut": 0,
         "phaser": 0, "video": 0, "intro": 0}


def main_loop():
    global PAGE, last_url, last_debug_dump, last_action_time, _last_recovery, STATUS_URL
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

            # anti-pause ringan tiap iterasi (banner "Start Typing" dll.)
            keep_alive_frames()

            url = PAGE.url
            STATUS_URL = url
            if "edclub.com" not in url and "typingclub.com" not in url:
                # coba cari ulang tab edclub (prioritas yang di halaman .play)
                found = None
                for pg in browser.contexts[0].pages:
                    if "edclub.com" in pg.url or "typingclub.com" in pg.url:
                        if ".play" in pg.url:
                            found = pg
                            break
                        if found is None:
                            found = pg
                if found:
                    PAGE = found
                else:
                    time.sleep(1)
                    continue

            if url != last_url:
                if last_url:
                    print(f"[PROGRES] {last_url.split('/')[-1]} -> {url.split('/')[-1]}  "
                          f"(std={stats['std']} tut={stats['tut']} mini={stats['mini']} "
                          f"phaser={stats['phaser']} ocr={stats['ocr']} hold={stats['hold']} "
                          f"video={stats['video']} popup={stats['popup']})")
                last_url = url

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
                if press_enter_guarded():
                    print("[Skor] Enter ditekan")
                    last_action_time = time.time()
                time.sleep(0.5)
            else:
                if handle_intro_steps():
                    time.sleep(0.3)
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
                    if stalled > 40 and time.time() - _last_recovery > 60:
                        # halaman kemungkinan mati/kosong -> pulihkan otomatis
                        if not recover_and_restart_lesson():
                            _last_recovery = time.time()
                    if stalled > STALL_WARN_SECONDS \
                            and time.time() - last_debug_dump > STALL_WARN_SECONDS:
                        last_debug_dump = time.time()
                        print("[PERINGATAN] Tidak ada aktivitas, dumping state...")
                        dump_debug_info()

            time.sleep(0.15)

        except KeyboardInterrupt:
            print("Dihentikan manual.")
            break
        except Exception:
            time.sleep(0.5)

    print(f"Selesai. Total: lesson={stats['std']} tutorial={stats['tut']} "
          f"minigame={stats['mini']} phaser={stats['phaser']} ocr={stats['ocr']} "
          f"hold={stats['hold']} video={stats['video']} popup={stats['popup']}")


if __name__ == "__main__":
    main_loop()
