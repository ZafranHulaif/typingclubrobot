"""Langkah intro "Type the f key" / "Press Enter"."""

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
from ..jstemplates import (INTRO_JS, INTRO_KEY_MAP)




def _click_labeled_key(key):
    """Klik mouse SUNGGUHAN tombol keyboard layar yang BERLABEL huruf
    target (mis. tombol 'f'). Input valid utk user sentuh. Dipakai HANYA
    sebagai cadangan coba-4 (ketikan CDP beberapa kali tidak masuk)."""
    if not key or len(key) != 1:
        return False
    for fr in jsutil.all_frames():
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
    if state._intro_attempts >= 8:
        return False
    for fr in jsutil.all_frames():
        res = jsutil.run_js(INTRO_JS, fr)
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
        if sig != state._intro_sig:
            state._intro_sig = sig
            state._intro_attempts = 0
        state._intro_attempts += 1
        # pola tutorial (terbukti): tunggu layar stabil dulu sebelum menekan
        # (jendela mati transisi; menekan terlalu dini = keystroke hilang).
        # Layar pertama di sebuah level: jendela matinya panjang (habis load
        # level) -> 2x baca @0.25s. Layar berikutnya dalam alur intro yang
        # sama (f->j->d->k): engine sudah hidup -> 2x baca @0.10s, tekanan
        # berikutnya praktis instan (pola user "fj" cepat).
        wait = 0.10 if state._intro_flow else 0.25
        stable = 0
        for _ in range(10):
            time.sleep(wait)
            now = jsutil.run_js(INTRO_JS, fr)
            same = bool(now) and (now.get("key"), now.get("type")) == (res.get("key"), res.get("type"))
            if same:
                stable += 1
            else:
                if now:
                    res = now
                stable = 0
            if stable >= 2:
                break
        typing_core.focus_frame(fr)
        print(f"[Intro] instruksi: {res['type']} {key!r} (coba {state._intro_attempts})")
        # satu tekanan bersih. Tekanan ekstra saat layar sudah pindah =
        # tombol salah di layar berikutnya (flash merah).
        if state._intro_attempts >= 4 and state._intro_attempts % 2 == 0:
            _click_labeled_key(key)
        else:
            try:
                if key == "Enter":
                    state.PAGE.keyboard.press("Enter")
                else:
                    state.PAGE.keyboard.type(key)
            except Exception:
                return False
        # tunggu instruksi berganti secepat mungkin (poll 80 ms) supaya
        # f->j praktis instan seperti tekanan manusia beruntun
        for _ in range(30):
            time.sleep(0.08)
            now = jsutil.run_js(INTRO_JS, fr)
            if not now or (now.get("key"), now.get("type")) != (res.get("key"), res.get("type")):
                state.stats["intro"] += 1
                state._intro_flow = True   # alur intro hidup: layar berikutnya cepat
                state.last_action_time = time.time()
                return True
        state.stats["intro"] += 1
        state.last_action_time = time.time()
        return True
    state._intro_flow = False   # tidak ada instruksi intro -> alur intro selesai
    return False
