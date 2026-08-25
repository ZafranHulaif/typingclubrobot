"""Mesin ketik CDP: delay, verifikasi konsumsi, deteksi intervensi user asli, anti-pause."""

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

from playwright.sync_api import sync_playwright

from . import state
from . import jsutil
from .config import (SPEEDS)
from .jstemplates import (ANTI_PAUSE_JS, ERR_COUNT_JS, ESC_FALLBACK_JS, MODAL_HINT_JS, QUIET_ALIVE_JS, READ_REMAINING_JS, STATE_JS, USER_WATCH_JS)




# ---------------------------------------------------------------------------
# Mesin ketik (CDP via Playwright - tidak butuh fokus jendela OS)
# ---------------------------------------------------------------------------


def _clear_modifiers():
    """Lepas modifier yang mungkin nyangkut (Shift/Ctrl/Alt). key-up tidak
    menghasilkan karakter, jadi aman - mencegah simbol/huruf salah pada
    lesson berikutnya (mis. sisa Shift dari lesson hold)."""
    for key in ("Shift", "Control", "Alt", "Meta"):
        try:
            state.PAGE.keyboard.up(key)
        except Exception:
            pass


def _char_delay(slow=False):
    """Jeda per karakter dari target WPM (1 kata = 5 karakter).
    Delay dikurangi overhead verifikasi yang terukur (loop mengukur sendiri
    via _loop_overhead) supaya LAJU AKHIR benar-benar mendekati target:
    140 wpm = ~86 ms/kar total, 200 = 60, 85 = 141.
    slow=True (tutorial boxed): engine butuh waktu animasi per karakter -
    jangan turun di bawah cadence aman (0.14-0.24 s)."""
    wpm = SPEEDS[state.SPEED_IDX][0]
    if slow:
        state._last_char_delay = random.uniform(0.14, 0.24)
        return state._last_char_delay
    base = 12.0 / wpm - state._loop_overhead
    base = max(base, 0.004)
    state._last_char_delay = base * random.uniform(0.85, 1.15)
    return state._last_char_delay


def type_chars(text, max_chars=None, slow=False):
    """Ketik via CDP. slow=True untuk tutorial boxed (animasi scroll-garis).
    TIDAK ada jeda untuk 'aktivitas user': input CDP isTrusted=true sehingga
    deteksi keydown mempan false-positive, dan klik mouse di tengah
    halaman tidak mengganggu engine. Gangguan user yang betulan (klik
    halaman / tekan tombol) terdeteksi otomatis oleh
    loop verifikasi handle_standard (karakter tak terkonsumsi -> koreksi
    backspace / re-fokus), bukan oleh jeda di sini."""
    for char in (text if max_chars is None else text[:max_chars]):
        while state.PAUSED and not state.STOP:
            time.sleep(0.15)
        if state.STOP:
            return False
        try:
            if char == "\n":
                state.PAGE.keyboard.press("Enter")
                time.sleep(0.03 + 0.02 * random.random())
            elif char == "\t":
                state.PAGE.keyboard.press("Tab")
                time.sleep(_char_delay(slow))
            elif char == " ":
                # wajib type() bukan press(): engine butuh event keypress/input
                # penuh untuk spasi - press() hanya kirim down/up = ditandai salah
                state.PAGE.keyboard.type(" ")
                time.sleep(_char_delay(slow))
            else:
                state.PAGE.keyboard.type(char)
                time.sleep(_char_delay(slow))
        except Exception:
            return False
    return True


def _mark_bot_click(frame=None, ms=900):
    """Panggil SEBELUM bot mengklik dengan mouse CDP: event mousedown-
    nya jangan dihitung sebagai 'aktivitas user' (echo klik sendiri)."""
    jsutil.run_js(f"window.__tb_ignore = Date.now() + {int(ms)}; return 1;",
           frame if frame is not None else state.PAGE.main_frame)


def _user_active(batas=2.0):
    """True kalau user asli aktif dalam `batas` detik terakhir di halaman
    edclub (klik/ketik/scroll/ambil fokus). Cache 0.5 dtk supaya murah
    dipanggil per karakter. Kegagalan baca = dianggap tidak aktif."""
    now = time.time()
    if now - state._user_watch_cache["t"] < 0.5:
        return state._user_watch_cache["elapsed"] < batas
    state._user_watch_cache["t"] = now
    terbaik = 1e9
    try:
        for fr in jsutil._edclub_frames():
            v = jsutil.run_js(USER_WATCH_JS, fr)
            if isinstance(v, (int, float)) and v < terbaik:
                terbaik = v
    except Exception:
        pass
    state._user_watch_cache["elapsed"] = terbaik
    return terbaik < batas


def _wait_for_user(url):
    """User sedang menjelajah (bukan di lesson) - catat & tunggu; kalau
    lebih dari 2 menit, minta GUI menanyakan lanjut/stop."""
    st = state._wait_user_since
    if st["url"] != url:
        st["url"] = url
        st["t"] = time.time()
        print("[USER] kamu sedang memakai browser bot - bot menunggu "
              "(lanjut otomatis begitu kamu diam / buka lesson)")
    elif time.time() - st["t"] > 120 and not state.ASK_NEXT_LEVEL:
        state.ASK_NEXT_LEVEL = True
    time.sleep(0.5)


def _user_idle_again(url):
    """Reset status menunggu (dipanggil saat bot bisa bekerja lagi)."""
    if state._wait_user_since["url"]:
        state._wait_user_since.update(url="", t=0.0)
        state.ASK_NEXT_LEVEL = False
        print("[USER] halaman tenang - bot lanjut bekerja.")


def press_enter_guarded():
    """Enter untuk menu skor: maks 3x per 6 detik, lalu jeda 15 detik."""
    now = time.time()
    state._enter_times = [t for t in state._enter_times if now - t < 6]
    if len(state._enter_times) >= 3:
        print("[Skor] Enter berulang tanpa efek, jeda 15 detik")
        state._enter_times = [now + 15]
        return False
    if state._enter_times and state._enter_times[0] > now:
        return False
    state._enter_times.append(now)
    try:
        state.PAGE.keyboard.press("Enter")
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
            loc = state.PAGE.locator(sel)
            if loc.count() == 0:
                continue
            _mark_bot_click()
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
    jsutil.run_js("try{window.focus();if(document.body&&document.body.focus)document.body.focus();}catch(e){}", frame)


def keep_alive_frames():
    """Jalankan anti-pause di semua frame. Return True jika banner diklik."""
    clicked = False
    for fr in jsutil._edclub_frames():
        res = jsutil.run_js(ANTI_PAUSE_JS, fr)
        if res == "banner":
            clicked = True
    return clicked


def keep_alive_quiet(frame):
    """Anti-pause tanpa klik apa pun (dipakai selama mengetik)."""
    jsutil.run_js(QUIET_ALIVE_JS, frame)


def esc_modals_only(frame):
    """Kirim ESC hanya jika ada modal achievement/premium betul-betul tampil.
    Tidak ada klik sama sekali - aman di tengah ketikan."""
    hint = jsutil.run_js(MODAL_HINT_JS, frame)
    if hint and (hint.get("achievement") or hint.get("premium")):
        jsutil.run_js(ESC_FALLBACK_JS, frame)
        print(f"[Pop-up] modal ditutup via ESC saat mengetik "
              f"({'achievement' if hint.get('achievement') else 'premium'})")


def read_remaining(frame):
    """Sisa teks lesson (hanya token pending). None jika tak ada token."""
    return jsutil.run_js(READ_REMAINING_JS, frame)


def count_errors(frame):
    """Jumlah karakter yang sudah ditandai salah di lesson."""
    n = jsutil.run_js(ERR_COUNT_JS, frame)
    return n if isinstance(n, int) else None


def read_state(frame):
    """(sisa_teks, jumlah_salah) dalam SATU evaluate. None teks = tak ada
    token pending. Dipakai di loop ketik per-karakter supaya cepat."""
    res = jsutil.run_js(STATE_JS, frame)
    if not isinstance(res, list) or len(res) != 2:
        return None, None
    rem = res[0] if isinstance(res[0], str) else None
    err = res[1] if isinstance(res[1], int) else None
    return rem, err
