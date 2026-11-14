"""Fallback OCR canvas untuk minigame non-Phaser."""

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
from .. import typing_core
from .. import jsutil
from ..config import (OCR_AVAILABLE, OCR_MIN_INTERVAL, UI_WORDS)

import asyncio
from PIL import Image
try:
    import winocr
except Exception:
    winocr = None




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
    if not OCR_AVAILABLE or not meta.get("canvas_frames"):
        return False
    now = time.time()
    if now - state.last_ocr_time < OCR_MIN_INTERVAL:
        return False
    state.last_ocr_time = now
    for fr in meta["canvas_frames"]:
        words = ocr_words_from_frame(fr)
        if not words:
            continue
        typing_core.focus_frame(fr)
        target = words[0]
        print(f"[Minigame/OCR] kata: {words[:5]} -> mengetik {target!r}")
        if not typing_core.type_chars(target):
            return False
        state.stats["ocr"] += 1
        state.last_action_time = time.time()
        return True
    return False


def _ocr_tokens(frame):
    """Semua token [a-z] dgn posisi tengah (px frame) - huruf TUNGGAL
    pun diambil (balon valley = 1 huruf per balon, filter lama
    [a-z]{2,12} membuangnya semua = OCR 'menang tapi tak bertindak')."""
    try:
        png = frame.locator("body").first.screenshot(timeout=3000)
        img = Image.open(io.BytesIO(png)).convert("RGB")
        w, h = img.size
        result = asyncio.run(winocr.recognize_pil(img))
        out = []
        for line in result.lines:
            for word in line.words:
                t = (word.text or "").strip().lower().strip(".,!?;:'\"()")
                if not re.fullmatch(r"[a-z]+", t) or t in UI_WORDS:
                    continue
                r = word.bounding_rect
                out.append((t, r.x + r.width / 2, r.y + r.height / 2))
        return out
    except Exception:
        return []


def _balloon_frame():
    """Frame game balloon valley (URL mengandung 'balloon')."""
    for fr in jsutil.all_frames():
        try:
            if "balloon" in (fr.url or ""):
                return fr
        except Exception:
            continue
    return None


def try_ocr_balloon():
    """Balloon valley (phaser01balloonvalley.edclub.app): canvas Phaser
    TANPA API core (core=False, log live lesson 2995). Dulu deteksi
    'mini' mengambil teks pelajaran di frame utama
    ('PartyPurpleQuality') dan mengetiknya ke arah tak berpihak =
    balon lolos, 3 hati habis, 'Type SPACE to try again' berulang
    (keluhan user 14 Nov 2026). Penanganan di sini:
    - layar 'Type SPACE to begin/try again' -> tekan spasi
    - balon huruf (OCR, urut kiri->kanan per baris) -> ketik urut
    - tombol 'Move On' -> klik mouse via rect OCR
    Return True kalau ada aksi. Throttle sendiri 2 dtk (lebih rapat
    dari OCR_MIN_INTERVAL - balon datang terus)."""
    if not OCR_AVAILABLE:
        return False
    fr = _balloon_frame()
    if fr is None:
        return False
    now = time.time()
    if now - getattr(state, "last_balloon_ocr", 0.0) < 0.35:
        return False
    state.last_balloon_ocr = now
    toks = _ocr_tokens(fr)
    if not toks:
        return False
    joined = " ".join(t[0] for t in toks)
    if "space" in joined:
        typing_core.focus_frame(fr)
        typing_core._mark_bot_click()
        state.PAGE.keyboard.press("Space")
        print("[Minigame/Balloon] layar SPACE - spasi ditekan")
        state.last_action_time = time.time()
        return True
    if "move" in joined:
        for t, cx, cy in toks:
            if t != "move":
                continue
            try:
                box = fr.locator("canvas").first.bounding_box(timeout=2000)
                cw = fr.evaluate(
                    "() => { const c = document.querySelector('canvas');"
                    " return c ? c.getBoundingClientRect().width : 0; }")
                if box and cw:
                    s = box["width"] / float(cw)
                    typing_core._mark_bot_click()
                    state.PAGE.mouse.click(box["x"] + cx * s,
                                           box["y"] + cy * s)
                    print("[Minigame/Balloon] tombol Move On diklik")
                    state.last_action_time = time.time()
                    return True
            except Exception:
                pass
    # balon huruf: SATU huruf per siklus (paling kiri pita teratas =
    # huruf yang ditunggu game) - dulu 10 huruf di-blast sekaligus
    # (400wpm) = game melompat ~20 huruf, berhenti, lalu spam sampai
    # hati habis (keluhan user 14 Nov). OCR sendiri ~0.3-0.6 dtk jadi
    # kadensi alami ~1 huruf/dtk = aman untuk semua kata.
    urut = sorted(toks, key=lambda it: (int(it[2] // 60), it[1]))
    huruf = [t for t, _x, _y in urut if len(t) == 1]
    if huruf:
        target = huruf[0]
    elif urut:
        target = urut[0][0][0]   # huruf pertama kata paling kiri
    else:
        return False
    typing_core.focus_frame(fr)
    print(f"[Minigame/Balloon] balon berikut: {target!r}")
    if not typing_core.type_chars(target):
        return False
    time.sleep(0.15)
    state.stats["ocr"] += 1
    state.last_action_time = time.time()
    return True
