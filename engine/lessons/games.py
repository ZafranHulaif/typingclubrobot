"""Minigame DOM & Phaser."""

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
from .. import levels
from .. import typing_core
from ..jstemplates import (PHASER_CHECK_JS, PHASER_FEED_JS, PHASER_PROBE_JS, PREMIUM_MODAL_JS)




def handle_minigame(frame, data):
    now = time.time()
    key = frame.url or frame.name
    if now - state._last_focus_click.get(key, 0) > 30:
        state._last_focus_click[key] = now
        typing_core.focus_frame(frame)
    text = data.get("text", "")
    print(f"[Minigame/{data.get('source','?')}] Mengetik: {text[:18]!r}")
    if not typing_core.type_chars(text, max_chars=14):
        return False
    state.stats["mini"] += 1
    state.last_action_time = time.time()
    time.sleep(0.15)
    return True


def _premium_modal_action():
    """Cek modal premium di semua frame edclub. Kalau tombol X ada ->
    klik mouse ASLI dan return 'clicked' (edclub lalu lanjut ke lesson
    berikutnya sendiri; terbukti live di 2968 & 3094). Kalau modal ada
    tanpa X -> return dict pm ({zombie:true} dll). Kalau tidak ada
    modal -> None. Catatan: modal X cuma muncul ~3 detik di awal level,
    lalu menghilang sendiri dan game jadi beku - jadi ini harus
    dipanggil SERING di awal level (watch window)."""
    for fr in jsutil._edclub_frames():
        pm = jsutil.run_js(PREMIUM_MODAL_JS, fr)
        if pm and pm.get("x") is not None:
            try:
                typing_core._tandai_klik_bot()
                state.PAGE.mouse.click(pm["x"], pm["y"])
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
        loc = state.PAGE.locator(".navbar-continue, a.navbar-continue, "
                           "[data-testid='lesson-next-btn'], .a-btn.next, "
                           ".btn-continue, .continue-button, .next-button") \
            .first
        if loc.count() and loc.is_visible():
            loc.click(timeout=2000)
            print("[Minigame/Phaser] game beku - level dilewati via tombol lanjut")
            state._phaser_freeze["count"] = 0
            state._phaser_freeze["clicked"] = False
            return True
    except Exception:
        pass
    # Fallback: tombol berteks lanjut (di luar kontainer premium/iframe,
    # titik klik terverifikasi elementFromPoint) -> klik mouse asli.
    for fr in jsutil._edclub_frames():
        pt = jsutil.run_js(r"""
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
                typing_core._tandai_klik_bot()
                state.PAGE.mouse.click(pt["x"], pt["y"])
                print("[Minigame/Phaser] game beku - level dilewati "
                      "via tombol berteks lanjut")
                state._phaser_freeze["count"] = 0
                state._phaser_freeze["clicked"] = False
                return True
            except Exception:
                pass
    return False


def handle_phaser_minigame():
    if time.time() < state._phaser_cooldown["until"]:
        return False
    # Level premium: modal menutupi canvas, game mengabaikan ketikan
    # (cur_char.valid=false). Modal+X muncul singkat di awal - klik X.
    if _premium_modal_action() == "clicked":
        state.last_action_time = time.time()
        return True
    for fr in jsutil.all_frames():
        res = jsutil.run_js(PHASER_FEED_JS, fr)
        if res is None or not res.get("fed"):
            continue
        print(f"[Minigame/Phaser] {jsutil.frame_label(fr)}: memberi ketikan via core API...")
        fed_total = 1
        stalled = 0
        probed = False
        last_idx = res.get("idx")
        while fed_total < 150:
            time.sleep(random.uniform(0.05, 0.11))
            res = jsutil.run_js(PHASER_FEED_JS, fr)
            if not res or not res.get("fed"):
                break
            idx = res.get("idx")
            if idx == last_idx:
                stalled += 1
                # modal premium bisa muncul kapan saja & mematikan game -
                # cek X di tiap stall (modal X hanya hidup ~3 dtk)
                if stalled >= 2 and _premium_modal_action() == "clicked":
                    state.last_action_time = time.time()
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
                        chk = jsutil.run_js(PHASER_CHECK_JS, fr)
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
                    url_now = state.PAGE.url
                    if state._phaser_freeze["url"] != url_now:
                        state._phaser_freeze["url"] = url_now
                        state._phaser_freeze["count"] = 0
                        state._phaser_freeze["clicked"] = False
                    state._phaser_freeze["count"] += 1
                    if not state._phaser_freeze["clicked"]:
                        state._phaser_freeze["clicked"] = True
                        try:
                            cv = fr.locator("canvas").first
                            if cv.count():
                                cv.click(timeout=1500)
                                print("[Minigame/Phaser] coba klik canvas "
                                      "(start game)")
                                time.sleep(1.5)
                                chk = jsutil.run_js(PHASER_CHECK_JS, fr)
                                if (chk or {}).get("idx") != last_idx:
                                    stalled = 0
                                    continue
                        except Exception:
                            pass
                    if state._phaser_freeze["count"] >= 2:
                        # modal premium bisa menutup canvas - cek X
                        if _premium_modal_action() == "clicked":
                            state.last_action_time = time.time()
                            return True
                    if state._phaser_freeze["count"] >= 3:
                        if _phaser_try_advance():
                            state.last_action_time = time.time()
                            return True
                        if levels._skip_to_next_lesson("minigame beku"):
                            state.last_action_time = time.time()
                            return True
                    print("[Minigame/Phaser] indeks tidak maju, jeda 6 detik "
                          f"(beku #{state._phaser_freeze['count']})")
                    state._phaser_cooldown["until"] = time.time() + 6
                    break
            else:
                stalled = 0
                last_idx = idx
            fed_total += 1
            state.last_action_time = time.time()
        state.stats["phaser"] += fed_total
        print(f"[Minigame/Phaser] {fed_total} karakter dikirim")
        state.last_action_time = time.time()
        time.sleep(0.4)
        return True
    return False
