"""
autopilot.py - Bot TypingClub (edclub.com) penuh otomatis, siap level 1 s/d akhir.

Yang ditangani otomatis:
- Lesson standar  (span.token_unit)  -> diketik penuh
- Minigame DOM    (.letter/.word di dalam iframe, termasuk cross-origin)
- Minigame Phaser (balloon valley, dll.) -> dibaca langsung dari memori game
  (core.record_keydown_time): tidak perlu OCR/fokus/ketik fisik
- Minigame canvas non-Phaser (fallback terakhir) -> screenshot + OCR Windows bawaan
- Pop-up achievement -> ditutup, lanjut normal
- Iklan premium/langganan -> ditutup (di level premium, menutup = langsung lanjut level berikutnya)
- Layar skor (WPM/accuracy) -> Enter otomatis
- Tombol Next/Continue/Lanjut/Mulai/Play di semua frame
- Level tutorial/video -> tunggu video selesai, klik Skip/Lanjut begitu muncul
- Level tutorial "boxed" (perkenalan tombol baru, mis. ` dan ~) -> baca .boxed-char
  satu per satu mulai dari posisi .cursor, lalu ketik sisanya
- Level keyboard layar -> klik otomatis tombol yang sedang di-highlight
- Level tahan tombol ("hold space"/"tahan shift") -> keyDown lama lalu keyUp aman
- CapsLock otomatis dimatikan agar huruf besar/kecil tidak terbalik

Cara pakai:
1. python autopilot.py   -> Brave debug dibuka OTOMATIS kalau belum jalan.
   (Fallback manual: jalankan brave.exe --remote-debugging-port=9222)
2. Login edclub.com, buka level pertama.
3. Fokuskan jendela Brave (bot hanya mengetik saat Brave aktif).
Stop darurat: gerakkan mouse ke pojok kiri-atas, atau Ctrl+C.
"""

import asyncio
import ctypes
import io
import os
import random
import re
import subprocess
import sys
import time

import pyautogui
from PIL import Image
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.001

BRAVE_BINARY = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
DEBUG_ADDRESS = "127.0.0.1:9222"
MAX_FRAME_DEPTH = 3          # kedalaman rekursi iframe
STALL_WARN_SECONDS = 90      # tidak ada aksi selama ini -> dump debug
OCR_MIN_INTERVAL = 3.0       # jeda minimal antar percobaan OCR
FOCUS_RECLICK_SECONDS = 30   # klik ulang fokus frame game tiap interval ini

try:
    import winocr
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False

# Kata UI umum yang TIDAK boleh diketik hasil OCR (bukan kata game)
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

print("Menghubungkan ke Brave (debug port 9222)...")


def _cek_debug_port():
    """Baca http://127.0.0.1:9222/json/version untuk tahu browser apa yang pegang port."""
    import json as _json
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://{DEBUG_ADDRESS}/json/version", timeout=2) as r:
            return _json.loads(r.read().decode()).get("Browser", "")
    except Exception:
        return ""


def _siapa_pegang_port():
    """Cari proses yang mendengarkan port 9222 -> daftar (pid, nama_exe)."""
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


_browser_on_port = _cek_debug_port()

if "Edg" in _browser_on_port:
    # Edge (atau proses berbasis Edge) mencuri port 9222. Edge punya fitur
    # "Startup boost" yang mempertahankan proses msedge.exe tersembunyi walau
    # semua jendelanya sudah ditutup -> tutup paksa proses pemegang portnya.
    print("Port 9222 dipegang proses berbasis Edge, mencari prosesnya...")
    pemegang = _siapa_pegang_port()
    if not pemegang:
        print("  proses tidak teridentifikasi (netstat kosong)")
    for pid, nama in pemegang:
        print(f"  -> {nama} (PID {pid}) memegang port 9222, menutup paksa...")
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, timeout=8)
        except Exception:
            pass
    time.sleep(2)
    _browser_on_port = _cek_debug_port()
    if "Edg" in _browser_on_port:
        print("MASIH terkunci oleh Edge. Tutup manual:")
        print("  1. Task Manager -> cari 'Microsoft Edge' -> End task SEMUA")
        print("  2. Matikan fitur background Edge: edge://settings/system ->")
        print("     'Startup boost' dan 'Continue running background extensions' OFF")
        print("  3. Jalankan ulang program ini")
        sys.exit(1)
    print("Port 9222 berhasil dibebaskan dari Edge.")

if not _browser_on_port:
    # Port kosong: kalau Brave belum jalan sama sekali, buka sendiri dengan mode debug
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

    if _brave_sudah_jalan():
        print("Brave sedang jalan TANPA mode debug (port 9222 kosong).")
        print("Tutup semua jendela Brave dulu, lalu jalankan ulang program ini")
        print("(program akan membuka Brave dengan mode debug secara otomatis).")
        sys.exit(1)

    exe = _find_brave()
    if not exe:
        print("Brave tidak ditemukan di lokasi standar. Install Brave atau jalankan manual:")
        print('  brave.exe --remote-debugging-port=9222')
        sys.exit(1)
    print(f"Port 9222 kosong: membuka Brave otomatis dengan mode debug...")
    subprocess.Popen([exe, "--remote-debugging-port=9222"], close_fds=True)
    for _ in range(30):
        time.sleep(0.5)
        # Catatan: Brave melaporkan dirinya sebagai "Chrome/..." di /json/version
        if _cek_debug_port().startswith("Chrome"):
            break
    _browser_on_port = _cek_debug_port()

if _browser_on_port:
    print(f"Port 9222 dipegang oleh: {_browser_on_port}")
    if "Brave" not in _browser_on_port and "Chrome" not in _browser_on_port:
        print(f"Peringatan: browser bukan Brave/Chrome ({_browser_on_port})")

_options = Options()
_options.binary_location = BRAVE_BINARY
_options.add_experimental_option("debuggerAddress", DEBUG_ADDRESS)
try:
    driver = webdriver.Chrome(options=_options)
except Exception as ex:
    print(f"GAGAL terhubung: {ex}")
    print('Jalankan Brave dulu: brave.exe --remote-debugging-port=9222')
    print("(Semua Brave harus tertutup sebelum menjalankan shortcut debug,")
    print(" dan tidak boleh ada browser lain yang memakai port 9222)")
    sys.exit(1)
print("Terhubung ke Brave!")

if not OCR_AVAILABLE:
    print("Catatan: 'winocr' tidak ada -> fallback OCR minigame canvas nonaktif.")
    print("         Install dengan: pip install winocr")

# ---------------------------------------------------------------------------
# Util Windows / tab
# ---------------------------------------------------------------------------

def is_brave_focused():
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return False
        buff = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
        title = buff.value.lower()
        return any(t in title for t in ["brave", "edclub", "typingclub", "typing club"])
    except Exception:
        return False


def ensure_capslock_off():
    try:
        if ctypes.windll.user32.GetKeyState(0x14) & 1:
            pyautogui.press("capslock")
            print("[Kunci] CapsLock dimatikan")
    except Exception:
        pass


def switch_to_typing_tab():
    try:
        for handle in driver.window_handles:
            driver.switch_to.window(handle)
            if "edclub.com" in driver.current_url or "typingclub.com" in driver.current_url:
                return True
    except Exception:
        pass
    return False


def ensure_typing_site():
    try:
        url = driver.current_url
    except Exception:
        driver.switch_to.default_content()
        url = ""
    if "edclub.com" not in url and "typingclub.com" not in url:
        switch_to_typing_tab()
        time.sleep(0.3)
        return False
    return True


# ---------------------------------------------------------------------------
# Traversal iframe via Selenium (bisa akses frame cross-origin, beda dengan
# rekursi JS murni di twos.py yang mentok same-origin)
# ---------------------------------------------------------------------------

def iter_frame_paths(max_depth=MAX_FRAME_DEPTH):
    """Generator: masuk ke tiap frame (path [] = dokumen atas, [0,2] = nested).
    Selama iterasi, context driver berada DI DALAM frame tsb.
    Selesai/gagal otomatis kembali ke default_content."""
    def walk(prefix, depth):
        try:
            frames = driver.find_elements(By.TAG_NAME, "iframe")
        except Exception:
            return
        for i, frame in enumerate(frames):
            path = prefix + [i]
            try:
                driver.switch_to.frame(frame)
            except Exception:
                continue
            yield path
            if depth < max_depth:
                yield from walk(path, depth + 1)
            try:
                driver.switch_to.parent_frame()
            except Exception:
                driver.switch_to.default_content()
                return
    try:
        yield []
        yield from walk([], 0)
    finally:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass


def enter_frame(path):
    """Masuk ulang ke frame berdasarkan path indeks. Raise jika DOM berubah."""
    driver.switch_to.default_content()
    for idx in path:
        frames = driver.find_elements(By.TAG_NAME, "iframe")
        driver.switch_to.frame(frames[idx])


def run_js(script):
    """execute_script di frame saat ini, aman dari error."""
    try:
        return driver.execute_script(script)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Deteksi state per frame (satu panggilan JS per frame)
# ---------------------------------------------------------------------------

DETECT_JS = r"""
const out = {std: null, mini: null, canvases: document.querySelectorAll('canvas').length, core: false};

const stdEls = document.querySelectorAll('span.token_unit, .token_unit');
if (stdEls.length > 0) {
    const result = [];
    for (const e of stdEls) {
        const txt = e.innerText || e.textContent;
        if (!txt) continue;
        if (txt.includes('↵') || txt.includes('\n')) result.push('\n');
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
    // Tutorial "boxed" (perkenalan tombol baru): .boxed-line > span > .boxed-char
    // CATATAN: checkmark/cursor tidak bisa dibedakan via CSS (state di memori JS),
    // jadi teks penuh diambil dan hanya diketik sekali per teks unik (cache signature).
    // PENTING: spasi ditulis sebagai &nbsp; (\u00A0) dan TIDAK boleh di-trim.
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

if (!out.std && !out.mini) {
    const targets = [];
    try { if (window.core) { out.core = true; targets.push(window.core); } } catch (e) {}
    try { if (window.core && window.core.lesson_controller) targets.push(window.core.lesson_controller); } catch (e) {}
    try { if (window.core && window.core.game) targets.push(window.core.game); } catch (e) {}
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


def detect_all_frames():
    """Return (state, path, data). state: 'std' | 'mini' | 'score' | 'unknown'."""
    canvases_anywhere = 0
    canvas_paths = []
    for path in iter_frame_paths():
        info = run_js(DETECT_JS)
        if not info:
            continue
        if info.get("canvases"):
            canvases_anywhere += int(info["canvases"])
            canvas_paths.append(path)
        if info.get("std"):
            return "std", path, info["std"]
        if info.get("tut"):
            return "tut", path, info["tut"]
        if info.get("mini"):
            return "mini", path, info["mini"]
        if not path:  # cek layar skor / menu selesai hanya di dokumen atas
            if run_js(r"""
                const t = (document.body ? document.body.innerText : '').toLowerCase();
                // layar intro pengenalan tombol baru BUKAN menu skor (jangan Enter-spam)
                if (t.includes('new key introduction')) return false;
                if (/^type the[\s\S]{1,20}?\s+key/m.test(t.replace(/\u00a0/g, ' '))) return false;
                if (t.includes('wpm') && (t.includes('accuracy') || t.includes('akurasi'))) return true;
                // menu selesai tutorial/lesson: tombol "-> Press Enter" tanpa teks WPM
                const cont = document.querySelector('.navbar-continue');
                return !!(cont && (cont.offsetWidth || cont.offsetHeight));
            """):
                return "score", path, None
    meta = {"canvases": canvases_anywhere, "canvas_paths": canvas_paths}
    return "unknown", [], meta


# ---------------------------------------------------------------------------
# Penutup pop-up / iklan premium / achievement (dijalankan di tiap frame)
# ---------------------------------------------------------------------------

OVERLAY_JS = r"""
const taken = [];
const visible = el => { try { return !!(el.offsetWidth || el.offsetHeight); } catch (e) { return false; } };
function doClick(el, why) { try { el.click(); taken.push(why); return true; } catch (e) { return false; } }

const CLOSE_TEXTS = ['x','×','✕','✖','close','tutup','no thanks','not now','maybe later','later',
                     'nanti saja','nanti','lewati','skip'];
const NEXT_TEXTS  = ['next','continue','lanjut','mulai','main','play','start','begin','selesai',
                     'claim','ambill','klaim','skip video','got it','ok','okay'];
const PREMIUM_WORDS = ['premium','upgrade','subscription','subscribe','langganan','berlangganan',
                       'go pro','unlock all'];

let bodyText = '';
try { bodyText = (document.body ? document.body.innerText : '').toLowerCase(); } catch (e) {}
const premium = PREMIUM_WORDS.some(w => bodyText.includes(w));

// 1) tombol tutup klasik (ikon X, modal-close, dsb.) - tag apa pun termasuk svg/div
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

// 2) tombol lanjut klasik (kecuali di layar intro - tombolnya bukan untuk lanjut level)
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

// 3) tombol LANJUT berdasar teks persis; HANYA elemen mirip tombol (bukan span/div
//    biasa, agar kata pelajaran seperti "play"/"main" tidak diklik!), di luar area ketik
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

// 3b) tombol TUTUP berdasar teks (x, x-icon, close, no thanks...).
//     Span/div biasa BOLEH asal berada DI DALAM kontainer modal/iklan,
//     dan tidak di area ketik. (Iklan premium sering pakai <span>x</span> polos.)
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


_repeat_click = {"label": "", "count": 0, "until": 0.0}

ESC_FALLBACK_JS = r"""
// modal achievement/langganan membandel tanpa tombol tutup -> kirim Escape
const ev = new KeyboardEvent('keydown', {key: 'Escape', code: 'Escape', keyCode: 27,
                                          which: 27, bubbles: true, cancelable: true});
[window, document, document.body].forEach(t => { try { t.dispatchEvent(ev); } catch (e) {} });
return true;
"""

MODAL_HINT_JS = r"""
// hanya dianggap modal bila ada kontainer dialog terlihat (bukan sekadar teks di halaman)
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


def close_overlays_all_frames():
    """Jalankan penutup pop-up di semua frame. Return jumlah aksi klik."""
    if time.time() < _repeat_click["until"]:
        return 0
    total = 0
    for path in iter_frame_paths():
        taken = run_js(OVERLAY_JS)
        if taken:
            label = "atas" if not path else "frame" + ".".join(map(str, path))
            print(f"[Pop-up] {label}: {'; '.join(taken[:3])}")
            total += len(taken)
            # pengaman: aksi sama terus berulang tanpa efek -> jeda 25 detik
            first = taken[0]
            if first == _repeat_click["label"]:
                _repeat_click["count"] += 1
                if _repeat_click["count"] >= 4:
                    _repeat_click["until"] = time.time() + 25
                    _repeat_click["count"] = 0
                    print(f"[Pop-up] '{first}' berulang tanpa hasil, jeda penutupan 25 detik")
            else:
                _repeat_click["label"] = first
                _repeat_click["count"] = 1
            break  # DOM bisa berubah setelah klik, mulai ulang scan
    if total == 0:
        # tidak ada tombol diklik: kalau ada modal achievement/premium terlihat,
        # coba tombol ESC (banyak modal menutup dengan Escape)
        for path in iter_frame_paths():
            hint = run_js(MODAL_HINT_JS)
            if hint and (hint.get("achievement") or hint.get("premium")):
                if run_js(ESC_FALLBACK_JS):
                    print(f"[Pop-up] modal terdeteksi tanpa tombol tutup, kirim ESC "
                          f"({'achievement' if hint.get('achievement') else 'premium'})")
                    total += 1
                break
    return total


# ---------------------------------------------------------------------------
# Mesin ketik
# ---------------------------------------------------------------------------

def type_chars(text, max_chars=None, slow=False):
    """Ketik fisik via pyautogui. Return False jika fokus hilang di tengah jalan.
    slow=True: jeda lebih manusiawi (untuk tutorial boxed yang animasi scroll-garisnya
    bisa menelan keystroke kalau diketik terlalu cepat)."""
    ensure_capslock_off()
    lo, hi = (0.13, 0.24) if slow else (0.05, 0.10)
    for char in (text if max_chars is None else text[:max_chars]):
        if not is_brave_focused():
            return False
        try:
            if char == "\n":
                pyautogui.press("enter")
                time.sleep(0.08)
            elif char == " ":
                pyautogui.press("space")
                time.sleep(random.uniform(lo, hi))
            else:
                pyautogui.write(char)
                time.sleep(random.uniform(lo, hi))
        except pyautogui.FailSafeException:
            raise
    return True


_enter_times = []


def press_enter_guarded():
    """Enter untuk menu skor, dengan pengaman anti-spam:
    maks 3 kali dalam 6 detik, lalu jeda 15 detik."""
    global _enter_times
    now = time.time()
    _enter_times = [t for t in _enter_times if now - t < 6]
    if len(_enter_times) >= 3:
        print("[Skor] Enter berulang tanpa efek, jeda 15 detik")
        _enter_times = [now + 15]  # blokir 15 detik ke depan
        return False
    if _enter_times and _enter_times[0] > now:
        return False  # masih dalam masa jeda
    _enter_times.append(now)
    if is_brave_focused():
        pyautogui.press("enter")
        return True
    return False


def focus_game_frame(path):
    """Fokus keyboard ke frame game: window.focus() + klik CDP di tengah body."""
    global _last_focus_click
    try:
        enter_frame(path)
    except Exception:
        return
    run_js("try{window.focus();if(document.body&&document.body.focus)document.body.focus();}catch(e){}")
    now = time.time()
    if now - _last_focus_click.get(tuple(path), 0) > FOCUS_RECLICK_SECONDS:
        try:
            body = driver.find_element(By.TAG_NAME, "body")
            ActionChains(driver).move_to_element(body).click().perform()
            _last_focus_click[tuple(path)] = now
            print(f"[Minigame] Klik fokus ke frame {path}")
        except Exception:
            pass


_last_focus_click = {}


# ---------------------------------------------------------------------------
# Mode standard
# ---------------------------------------------------------------------------

def handle_standard(path, text):
    global last_typed_text, last_action_time, stats
    if text == last_typed_text:
        return False
    # instruksi "Hold the j key while typing this lesson." -> tahan tombolnya
    hold_key, hold_instr = get_hold_lesson_key(path)
    print(f"[Standard] Mengetik {len(text)} karakter: {text[:24]!r}..."
          + (f" (TAHAN {hold_key!r})" if hold_key else ""))
    ensure_capslock_off()
    typed_ok = False
    try:
        if hold_key:
            pyautogui.keyDown(hold_key)
            time.sleep(0.15)
        typed_ok = type_chars(text)
    finally:
        if hold_key:
            try:
                pyautogui.keyUp(hold_key)
            except Exception:
                pass
    if not typed_ok:
        return False
    last_typed_text = text
    stats["std"] += 1
    last_action_time = time.time()

    # transisi level: buru tombol lanjut / pop-up / Enter skor selama 10 detik
    deadline = time.time() + 10
    while time.time() < deadline:
        if close_overlays_all_frames():
            time.sleep(0.6)
            continue
        state, _, _ = detect_all_frames()
        if state == "score" and is_brave_focused():
            if press_enter_guarded():
                print("[Skor] Enter ditekan")
            time.sleep(0.8)
        if state in ("std", "mini"):
            break
        time.sleep(0.25)

    # tunggu level baru siap
    deadline = time.time() + 8
    while time.time() < deadline:
        state, _, _ = detect_all_frames()
        if state != "unknown":
            break
        time.sleep(0.2)
    last_action_time = time.time()
    return True


# ---------------------------------------------------------------------------
# Mode tutorial "boxed" (perkenalan tombol baru: ` ~ angka shift dsb.)
# ---------------------------------------------------------------------------

_tut_sig = None
_tut_attempts = 0


def handle_tutorial(path, data):
    """Ketik seluruh urutan .boxed-char sekali per teks unik."""
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
    focus_game_frame(path)
    print(f"[Tutorial] ketik {text!r} (coba {_tut_attempts})")
    if not type_chars(text, slow=True):
        return False
    stats["tut"] += 1
    last_action_time = time.time()
    time.sleep(0.3)
    return True


# ---------------------------------------------------------------------------
# Mode minigame
# ---------------------------------------------------------------------------

def handle_minigame(path, data):
    global last_action_time, stats
    focus_game_frame(path)
    text = data.get("text", "")
    print(f"[Minigame/{data.get('source','?')}] Mengetik: {text[:18]!r}")
    if not type_chars(text, max_chars=14):
        return False
    stats["mini"] += 1
    last_action_time = time.time()
    time.sleep(0.15)
    return True


# ---------------------------------------------------------------------------
# Fallback OCR untuk minigame canvas
# ---------------------------------------------------------------------------

def ocr_words_from_frame(path):
    """Screenshot frame -> OCR -> daftar kata kandidat (bukan kata UI)."""
    try:
        enter_frame(path)
        png = None
        try:
            png = driver.find_element(By.TAG_NAME, "body").screenshot_as_png
        except Exception:
            png = None
        if not png:
            try:
                png = driver.get_screenshot_as_png()
            except Exception:
                return []
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
                    if 0.15 < cy < 0.90:  # hindari header/footer UI
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
    """Dipakai saat state unknown dan ada canvas. Return True jika sempat mengetik."""
    global last_ocr_time, last_action_time, stats
    if not OCR_AVAILABLE or not meta.get("canvas_paths"):
        return False
    now = time.time()
    if now - last_ocr_time < OCR_MIN_INTERVAL:
        return False
    last_ocr_time = now
    for path in meta["canvas_paths"]:
        words = ocr_words_from_frame(path)
        if not words:
            continue
        focus_game_frame(path)
        target = words[0]
        print(f"[Minigame/OCR] frame {path} kata: {words[:5]} -> mengetik {target!r}")
        if not type_chars(target):
            return False
        stats["ocr"] += 1
        last_action_time = time.time()
        return True
    return False


last_ocr_time = 0.0


# ---------------------------------------------------------------------------
# Minigame Phaser (Balloon Valley, dsb.): ketik via API internal game
#
# Temuan penting (reverse-engineering games.1237.min.js):
# - Game Phaser mendaftar di window.Phaser.GAMES
# - State aktif punya .core dengan record_keydown_time(char) = kanal input resmi
# - core.cur_char.chr = karakter yang diharapkan BERIKUTNYA (selalu benar)
# - Memberi char via API ini tidak butuh fokus jendela sama sekali
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


def handle_phaser_minigame():
    """Cari game Phaser di semua frame lalu beri karakter yang diharapkan via core API.
    Return True jika minimal satu karakter berhasil dikirim."""
    global last_action_time
    for path in iter_frame_paths():
        res = run_js(PHASER_FEED_JS)
        if res is None:
            continue
        label = "atas" if not path else "frame" + ".".join(map(str, path))
        if not res.get("fed"):
            continue  # game ditemukan tapi selesai/diam; biarkan handler lain proses
        print(f"[Minigame/Phaser] {label}: game aktif, memberi ketikan via core API...")
        fed_total = 1
        stalled = 0
        last_idx = res.get("idx")
        while fed_total < 150:
            time.sleep(random.uniform(0.05, 0.11))
            res = run_js(PHASER_FEED_JS)
            if not res or not res.get("fed"):
                break
            idx = res.get("idx")
            if idx == last_idx:
                stalled += 1
                if stalled >= 8:
                    print("[Minigame/Phaser] indeks tidak maju, mundur ke loop utama")
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
# Level "tahan tombol sambil mengetik" (mis. "Hold the j key while typing")
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


def get_hold_lesson_key(path):
    """Baca instruksi 'Hold the X key while typing this lesson.' di frame tsb."""
    res = run_js(HOLD_LESSON_JS)
    if res and res.get("key"):
        return res["key"], res.get("instr", "")
    return None, None


# ---------------------------------------------------------------------------
# Level video: klik play (CDP, bukan JS), percepat, lompat ke akhir
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
    """Video tutorial: mulai (klik nyata), lalu percepat dan lompat ke akhir."""
    global last_action_time
    for path in iter_frame_paths():
        info = run_js(VIDEO_STATE_JS)
        if not info:
            continue
        try:
            enter_frame(path)
        except Exception:
            continue
        if info.get("paused"):
            try:
                btn = driver.find_elements(By.CSS_SELECTOR, ".vjs-big-play-button")
                if btn:
                    ActionChains(driver).move_to_element(btn[0]).click().perform()
                    time.sleep(0.8)
            except Exception:
                pass
        run_js(VIDEO_SKIP_JS)
        stats["video"] += 1
        last_action_time = time.time()
        print(f"[Video] frame {path}: diputar cepat 16x & dilompat ke akhir")
        time.sleep(0.5)
        return True
    return False


# ---------------------------------------------------------------------------
# Langkah intro "Type the f key" / "Press Enter" (level pengenalan tombol)
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

INTRO_KEY_MAP = {"space": "space", "space bar": "space", "spacebar": "space",
                 "spasi": "space", "bar": "space", "enter": "enter"}

_intro_sig = None
_intro_attempts = 0


def handle_intro_steps():
    """Ikuti instruksi 'Type the X key' / 'Press Enter' dengan tombol fisik."""
    global _intro_sig, _intro_attempts, last_action_time
    for path in iter_frame_paths():
        res = run_js(INTRO_JS)
        if not res:
            continue
        key = res.get("key")
        if res["type"] == "type":
            key = INTRO_KEY_MAP.get(key, key)
            if not key or len(key) > 12:
                continue
        else:
            key = "enter"
        sig = (res["type"], key)
        if sig == _intro_sig:
            _intro_attempts += 1
            if _intro_attempts > 6:
                continue  # jangan spam tombol yang sama
        else:
            _intro_sig = sig
            _intro_attempts = 1
        if not is_brave_focused():
            return False
        focus_game_frame(path)
        print(f"[Intro] instruksi: {res['type']} {key!r} (coba {_intro_attempts})")
        try:
            pyautogui.press(key)
        except pyautogui.FailSafeException:
            raise
        stats["intro"] += 1
        last_action_time = time.time()
        time.sleep(0.8)
        return True
    return False


# ---------------------------------------------------------------------------
# Level "tahan tombol" (hold) / keyboard layar / video tutorial
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
    "space": "space", "space bar": "space", "spacebar": "space", "spasi": "space",
    "bar": "space", "shift": "shift", "ctrl": "ctrl", "control": "ctrl", "alt": "alt",
    "enter": "enter", "return": "enter", "tab": "tab", "esc": "escape", "escape": "escape",
    "backspace": "backspace", "delete": "delete", "up": "up", "down": "down",
    "left": "left", "right": "right",
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
    """Deteksi instruksi 'hold <tombol>' lalu tahan tombol fisik dengan aman."""
    global last_hold_raw, hold_attempts, last_action_time
    for path in iter_frame_paths():
        instr = run_js(HOLD_JS)
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
        if not is_brave_focused():
            return False
        focus_game_frame(path)
        duration = min(1.5 * hold_attempts, 8.0)
        print(f"[Hold] instruksi '{raw}' -> menahan '{key}' {duration:.1f}s "
              f"(percobaan {hold_attempts})")
        try:
            pyautogui.keyDown(key)
            time.sleep(duration)
        finally:
            try:
                pyautogui.keyUp(key)
            except Exception:
                pass
        stats["hold"] += 1
        last_action_time = time.time()
        return True
    return False


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
    """Level tutorial keyboard layar: klik tombol yang di-highlight."""
    global last_action_time
    for path in iter_frame_paths():
        hit = run_js(SCREENKEY_JS)
        if hit:
            print(f"[Keyboard-layar] klik '{hit.get('key')}' ({hit.get('sel')})")
            stats["uikey"] += 1
            last_action_time = time.time()
            return True
    return False


# ---------------------------------------------------------------------------
# Debug dump (throttled)
# ---------------------------------------------------------------------------

def dump_debug_info():
    try:
        print("---- DEBUG (tiap frame) ----")
        for path in iter_frame_paths():
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
            """)
            if info:
                label = "TOP" if not path else "frame " + ".".join(map(str, path))
                print(f"DEBUG {label}: core={info.get('core')} canvas={info.get('canvases')} url={info.get('url')}")
                for t in info.get("texts", []):
                    print(f"DEBUG {label} dom: {t}")
        print("---------------------------")
    except Exception as ex:
        print(f"DEBUG gagal: {ex}")


# ---------------------------------------------------------------------------
# State global + loop utama
# ---------------------------------------------------------------------------

last_typed_text = ""
last_action_time = time.time()
last_debug_dump = 0.0
last_url = ""
stats = {"std": 0, "mini": 0, "ocr": 0, "popup": 0, "hold": 0, "uikey": 0, "tut": 0,
         "phaser": 0, "video": 0, "intro": 0}

ensure_capslock_off()

if not switch_to_typing_tab():
    print("Tab edclub belum ada. Buka edclub.com di Brave, bot akan menunggu.")

print("Bot autopilot aktif. Fokuskan Brave untuk mulai mengetik. Ctrl+C untuk stop.")

while True:
    try:
        if not ensure_typing_site():
            time.sleep(1)
            continue

        # log perubahan URL = progres level
        try:
            url = driver.current_url
            if url != last_url:
                if last_url:
                    print(f"[PROGRES] {last_url.split('/')[-1]} -> {url.split('/')[-1]}  "
                          f"(std={stats['std']} tut={stats['tut']} mini={stats['mini']} "
                          f"phaser={stats['phaser']} ocr={stats['ocr']} "
                          f"hold={stats['hold']} popup={stats['popup']})")
                last_url = url
        except Exception:
            pass

        # 1) pop-up / iklan premium / achievement selalu duluan
        if close_overlays_all_frames():
            stats["popup"] += 1
            time.sleep(0.6)
            continue

        # 2) deteksi isi level
        state, path, data = detect_all_frames()

        if state == "std":
            handle_standard(path, data)
        elif state == "tut":
            handle_tutorial(path, data)
        elif state == "mini":
            handle_minigame(path, data)
        elif state == "score":
            if press_enter_guarded():
                print("[Skor] Enter ditekan")
                last_action_time = time.time()
            time.sleep(0.5)
        else:
            # unknown: intro-step -> Phaser -> hold -> keyboard layar -> video -> OCR
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
                # stagnan terlalu lama -> dump untuk diagnosis
                if time.time() - last_action_time > STALL_WARN_SECONDS \
                        and time.time() - last_debug_dump > STALL_WARN_SECONDS:
                    last_debug_dump = time.time()
                    print("[PERINGATAN] Tidak ada aktivitas, dumping state...")
                    dump_debug_info()

        time.sleep(0.15)

    except pyautogui.FailSafeException:
        print("Failsafe aktif (mouse di pojok). Bot berhenti.")
        break
    except KeyboardInterrupt:
        print("Dihentikan manual.")
        break
    except Exception as ex:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        time.sleep(0.5)

print(f"Selesai. Total: lesson={stats['std']} tutorial={stats['tut']} minigame={stats['mini']} "
      f"phaser={stats['phaser']} ocr={stats['ocr']} hold={stats['hold']} "
      f"keyboard-layar={stats['uikey']} popup={stats['popup']}")
