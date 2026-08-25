"""Level tutorial boxed."""

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

from .. import state
from .. import jsutil
from .. import typing_core
from ..jstemplates import (START_BANNER_JS, TUT_REMAIN_JS)




def _tut_read(frame):
    res = jsutil.run_js(TUT_REMAIN_JS, frame)
    return res if isinstance(res, dict) else None


def handle_tutorial(frame, data):
    text = data.get("text", "")
    if not text:
        return False
    if text == state._tut_sig and state._tut_attempts >= 6:
        return False
    if text != state._tut_sig:
        state._tut_sig = text
        state._tut_attempts = 0
        state._tut_full = text
    state._tut_attempts += 1
    typing_core.focus_frame(frame)
    print(f"[Tutorial] ketik {text!r} (coba {state._tut_attempts})")
    if jsutil.run_js(START_BANNER_JS, frame):
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
    if (state._tut_attempts >= 2 and state._tut_full and res
            and isinstance(res.get("rem"), str)
            and 0 < len(res["rem"]) < len(state._tut_full)
            and state._tut_full.endswith(res["rem"])):
        rem = res["rem"]
        print(f"[Tutorial] lanjut dari sisa {len(rem)} karakter")
    CH = 10   # potongan kecil utk keep-alive senyap di selanya
    while rem:
        if state.STOP:
            return False
        while state.PAUSED and not state.STOP:
            time.sleep(0.15)
        n = min(CH, len(rem))
        if not typing_core.type_chars(rem[:n]):
            break
        typing_core.keep_alive_quiet(frame)
        rem = rem[n:]
    # akhir pola: Enter (pola user: sequence > enter). Kalau layar skor
    # sudah muncul duluan, Enter justru menekan lanjut - aman dua-duanya.
    time.sleep(0.8)
    try:
        state.PAGE.keyboard.press("Enter")
        print("[Tutorial] selesai - Enter")
    except Exception:
        pass
    state.stats["tut"] += 1
    state.last_action_time = time.time()
    time.sleep(0.3)
    return True
