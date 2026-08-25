"""Util frame & JS Playwright: deteksi state per frame, tutup pop-up/premium, debug dump."""

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
from . import browser
from . import typing_core
from .jstemplates import (BADGE_STREAK_JS, DETECT_JS, ESC_FALLBACK_JS, MODAL_HINT_JS, OVERLAY_JS, SCORE_JS)




# ---------------------------------------------------------------------------
# Util frame & JS (Playwright: semua frame otomatis tersedia)
# ---------------------------------------------------------------------------

def all_frames():
    """Semua frame halaman (main + semua iframe, termasuk cross-origin)."""
    try:
        return list(state.PAGE.frames)
    except Exception:
        try:
            return [state.PAGE.main_frame]
        except Exception:
            return []


def _edclub_frames():
    """Semua frame milik edclub (frame Stripe/checkout dikecualikan)."""
    return [fr for fr in all_frames() if browser._frame_edclub(fr)]


def run_js(js, frame=None):
    """evaluate JS di frame (default main). Aman dari error."""
    fr = frame if frame is not None else state.PAGE.main_frame
    try:
        return fr.evaluate("() => {" + js + "}")
    except Exception:
        return None


def frame_label(frame):
    if frame == state.PAGE.main_frame:
        return "atas"
    return "frame:" + (frame.url[-60:] if frame.url else frame.name)


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
        if fr == state.PAGE.main_frame and run_js(SCORE_JS, fr):
            return "score", fr, None
    return "unknown", None, {"canvases": canvases, "canvas_frames": canvas_frames}


def close_overlays_all_frames():
    """Jalankan penutup pop-up di semua frame. Return jumlah aksi."""
    if time.time() < state._repeat_click["until"]:
        return 0
    total = 0
    # Badge streak: tidak punya tombol tutup - ESC keyboard asli (CDP,
    # isTrusted) menutupnya (live terverifikasi; KeyboardEvent sintetis
    # berisiko tidak dipercaya seperti JS .click()).
    try:
        if run_js(BADGE_STREAK_JS, state.PAGE.main_frame):
            state.PAGE.keyboard.press("Escape")
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
            if first == state._repeat_click["label"]:
                state._repeat_click["count"] += 1
                if state._repeat_click["count"] >= 3:
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
                            typing_core._tandai_klik_bot()
                            state.PAGE.mouse.click(pt["x"], pt["y"])
                        except Exception:
                            pass
                    state._repeat_click["until"] = time.time() + 8
                    state._repeat_click["count"] = 0
            else:
                state._repeat_click["label"] = first
                state._repeat_click["count"] = 1
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
