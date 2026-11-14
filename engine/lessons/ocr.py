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
    """Semua token [a-z] dgn posisi tengah TERNORMALISASI 0..1 -
    huruf TUNGGAL pun diambil (balon valley = 1 huruf per balon,
    filter lama [a-z]{2,12} membuangnya semua)."""
    try:
        png = frame.locator("body").first.screenshot(timeout=3000)
        img = Image.open(io.BytesIO(png)).convert("RGB")
        # naikkan 3x: Windows OCR sering gagal baca huruf tunggal
        # balon (live 15 Nov - token cuma teks DOM); huruf besar =
        # jauh lebih bisa dibaca
        w, h = img.size
        img = img.resize((w * 3, h * 3))
        result = _recognize(img)
        out = []
        for line in result.lines:
            for word in line.words:
                t = (word.text or "").strip().lower().strip(".,!?;:'\"()")
                if not re.fullmatch(r"[a-z]+", t) or t in UI_WORDS:
                    continue
                r = word.bounding_rect
                out.append((t, (r.x + r.width / 2) / (w * 3),
                            (r.y + r.height / 2) / (h * 3)))
        return out
    except Exception:
        return []


BALLOON_CORE_JS = r"""
const g = window.Phaser ? (Phaser.GAMES || [])[0] : null;
if (!g || !g.state) return null;
const st = g.state.states[g.state.current];
if (!st || !st.core) return null;
const c = st.core;
if (c.has_ended) return {ended: true};
const cur = c.cur_char ? String(c.cur_char.chr) : '';
if (!cur) return {wait: true};
const curX = st.balloonCursor ? st.balloonCursor.x : 300;
let best = null;
for (const b of (st.balloons || [])) {
    if (!b || b.visible === false || b.x === undefined || b.x === null) continue;
    const d = Math.abs(b.x - curX);
    if (best === null || d < best) best = d;
}
return {chr: cur, idx: c.cur_char_index, dist: best, wait: false};
"""


def try_balloon_core():
    """Balloon valley new-look: game HIDUP DI FRAME UTAMA (sportal
    .play) dgn API core standar + balloonCursor (zona pukul x=300,
    balon spacing 200 - bukti live 15 Nov). Baca cur_char, ketik HANYA
    saat balon sudah dekat cursor (dist<=90); anti-spam: (chr,idx) yg
    sama tak diketik ulang kecuali >5 dtk. Return True kalau ketik."""
    res = jsutil.run_js(BALLOON_CORE_JS)
    if not res:
        return False
    if res.get("ended"):
        # layar akhir (live 15 Nov): tombol DOM 'Try again' / '→ Press
        # Enter' - maju dulu, kalau tak ada tombol maju = ulang (hati
        # baru, feed tanpa salah = akhirnya selesai)
        klik = jsutil.run_js(r"""
const want = ['press enter', 'move on', '\u2192', 'continue', 'next',
              'try again'];
for (const w of want) {
  for (const el of document.querySelectorAll('button, a, [role=button]')) {
    const t = (el.innerText || '').trim().toLowerCase();
    if (!t.includes(w)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 30) continue;
    el.click();
    return t;
  }
}
return null;
""")
        if klik:
            print(f"[Minigame/Balloon] layar akhir - klik {klik!r}")
            state.last_action_time = time.time()
        return False
    chr_ = res.get("chr")
    idx = res.get("idx")
    dist = res.get("dist")
    if dist is not None and dist > 90:
        return False          # balon belum sampai zona pukul
    kini = time.time()
    terakhir = getattr(state, "_balloon_core_last", None)
    if terakhir and terakhir[0] == chr_ and terakhir[1] == idx \
            and kini - terakhir[2] < 5.0:
        return False          # sudah diketik, tunggu game maju
    typing_core._mark_bot_click()
    state.PAGE.keyboard.type(chr_)
    state._balloon_core_last = (chr_, idx, kini)
    print(f"[Minigame/Balloon] core: {chr_!r} idx={idx} dist={dist}")
    state.stats["ocr"] += 1
    state.last_action_time = time.time()
    return True


def _recognize(img):
    """winocr di thread terpisah - thread engine membawa event loop
    playwright (sync API), asyncio.run di sana = RuntimeError 'cannot
    be called from a running event loop' -> OCR MATI TOTAL sejak
    selalu (stats ocr=0 di semua log live)."""
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(1) as ex:
        return ex.submit(lambda: asyncio.run(
            winocr.recognize_pil(img))).result(timeout=25)


def _balloon_frame():
    """Frame game balloon valley: (a) iframe klasik dgn 'balloon' di
    URL, (b) NEW LOOK: game HIDUP DI FRAME UTAMA halaman sportal
    .play dgn API core standar (bukti live 15 Nov: 55/55 huruf via
    core feed). Selalu catat waktu terakhir dilihat utk peluruhan
    jangan-ketik-void di supervisor."""
    for fr in jsutil.all_frames():
        try:
            if "balloon" in (fr.url or ""):
                state._balloon_frame_seen = time.time()
                _probe_iframe(fr)
                return fr
        except Exception:
            continue
    try:
        main = state.PAGE.main_frame
        u = (main.url or "").lower()
        if "sportal" in u and ".play" in u:
            state._balloon_frame_seen = time.time()
            return main
    except Exception:
        pass
    return None


def _probe_iframe(fr):
    """Varian IFRAME (core=False) masih dipakai sebagian akun/rollout
    - log strukturnya SEKALI per start bot supaya bisa ditangani
    tepat (live 14 Nov: cur_char tak ada, balloons di mana?)."""
    if getattr(state, "_balloon_probe_done", False):
        return
    state._balloon_probe_done = True
    info = jsutil.run_js(r"""
const o = {phaser: typeof window.Phaser !== 'undefined'};
try {
  const g = window.Phaser ? Phaser.GAMES[0] : null;
  if (g) {
    o.ver = Phaser.VERSION;
    const st = g.state.states[g.state.current];
    o.cur = g.state.current;
    o.stateKeys = st ? Object.keys(st).filter(k => !k.startsWith('_'))
      .filter(k => /balloon|char|word|key|core|input|text|cursor|glow/i.test(k))
      .slice(0, 30) : null;
    o.hasCore = st ? !!st.core : null;
    if (st && st.core) {
      o.coreKeys = Object.keys(st.core).slice(0, 25);
      o.curChar = st.core.cur_char ? String(st.core.cur_char.chr) : null;
    }
  }
} catch (e) { o.err = String(e).slice(0, 100); }
return o;
""", fr)
    print(f"[Minigame/Balloon] probe iframe: "
          f"{json.dumps(info)[:300] if info else 'None'}")


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
    mulai = ("begin" in joined or "again" in joined
             or "letter" in joined or "space" in joined)
    if mulai and "space" in joined:
        # layar 'Type SPACE to begin/try again' (varian lama)
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
                if box:
                    typing_core._mark_bot_click()
                    state.PAGE.mouse.click(
                        box["x"] + cx * box["width"],
                        box["y"] + cy * box["height"])
                    print("[Minigame/Balloon] tombol Move On diklik")
                    state.last_action_time = time.time()
                    return True
            except Exception:
                pass
    # kandidat balon: huruf tunggal di pita terbang game (buang UI
    # atas 'Zafran' cy<0.08, bawah 'Hide' cy>0.75, tepi kanan)
    urut = sorted(toks, key=lambda it: (int(it[2] * 8), it[1]))
    huruf = [(t, cx) for t, cx, cy in urut
             if len(t) == 1 and 0.08 < cy < 0.75 and cx <= 0.93]
    if not huruf:
        return False
    target, cx0 = huruf[0]
    if cx0 > 0.30:
        # balon terdekat belum di zona pukul (balon menyala live di
        # x~0.24) - ketik sekarang = SALAH. Tunggu.
        return False
    typing_core.focus_frame(fr)
    if mulai:
        print(f"[Minigame/Balloon] mulai via huruf {target!r} "
              f"(x={cx0:.2f})")
    else:
        print(f"[Minigame/Balloon] balon di zona: {target!r} "
              f"(x={cx0:.2f})")
    if not typing_core.type_chars(target):
        return False
    time.sleep(0.15)
    state.stats["ocr"] += 1
    state.last_action_time = time.time()
    return True
