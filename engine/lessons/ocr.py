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


BALLOON_BRIDGE_JS = r"""
const c = (typeof window.core !== 'undefined') ? window.core :
  ((window.Phaser && Phaser.GAMES && Phaser.GAMES.length &&
    Phaser.GAMES[0].state) ?
   Phaser.GAMES[0].state.states[Phaser.GAMES[0].state.current].core : null);
if (!c) return null;
if (c.has_ended) return {ended: true};
if (c.paused) { try { c.paused = false; } catch (e) {} }
const cur = c.cur_char ? String(c.cur_char.chr) : '';
if (!cur) return {wait: true, idx: c.cur_char_index,
                  mulai: !c.has_started};
if ('FEED') {
    // ARGUMEN WAKTU WAJIB (live 15 Nov malam, game yeti varian
    // baru): panggilan 1-argumen TIDAK mengkonsumsi huruf - game
    // mentok 'Type SPACE to begin' selamanya. performance.now()
    // terbukti diterima (huruf terkonsumsi, live).
    c.record_keydown_time(cur, 109);  // 109ms/huruf = 110wpm terukur
    return {fed: true, idx: c.cur_char_index};
}
return {chr: cur, idx: c.cur_char_index, ended: false};
"""
BALLOON_STATE_JS = BALLOON_BRIDGE_JS.replace("'FEED'", "0")
# FEED BATCH kontinu (live 15 Nov, permintaan user): rantai
# setTimeout 60ms berjalan terus sampai (a) level selesai, (b) 3.5
# dtk per eval (biar supervisor responsif), (c) huruf pertama yang
# TAK dikonsumsi game (balon belum siap = berhenti, tanpa spam).
# Python segera panggil ulang (jeda 0.12s) = terasa ngegemes
# kontinu. Dulu 8 huruf @80ms + jeda 0.5s = 'nendaskendat'.
BALLOON_FEED_JS = r"""
const c = (typeof window.core !== 'undefined') ? window.core :
  ((window.Phaser && Phaser.GAMES && Phaser.GAMES.length &&
    Phaser.GAMES[0].state) ?
   Phaser.GAMES[0].state.states[Phaser.GAMES[0].state.current].core : null);
if (!c) return null;
if (c.has_ended) return {ended: true};
if (c.paused) { try { c.paused = false; } catch (e) {} }
if (!c.has_started) {
    // reset stat: duration sisa usia halaman (performance.now)
    // pernah dikira jeda = membengkak = wpm hancur (18 Nov)
    try { c.reset_stats(); } catch (e) {}
    // Dua varian mulai (live 15 Nov): (a) huruf-pertama - cur_char
    // sudah diisi (balloon valley, yeti 'b'...) = feed huruf itu;
    // (b) spasi - cur null (yeti 2970) = ketuk spasi. PENTING:
    // record(' ') TIDAK memulai varian spasi, dan event document
    //-lah yang didengar listener game (bukan window)
    // VARIAN BARU EDCLUB (live 15 Nov malam): setelah spasi
    // has_started TETAP false (huruf pertama langsung siap) -
    // dulu bila di sini = rantai mati 'Type SPACE' selamanya.
    // Kini: cuma tunggu bila cur_char memang belum ada.
    const c0 = c.cur_char ? String(c.cur_char.chr) : '';
    if (!c0) {
        document.dispatchEvent(new KeyboardEvent('keydown',
          {key: ' ', code: 'Space', keyCode: 32, which: 32,
           bubbles: true, cancelable: true}));
        setTimeout(() => document.dispatchEvent(new KeyboardEvent('keyup',
          {key: ' ', code: 'Space', keyCode: 32, which: 32,
           bubbles: true})), 40);
        if (!c.cur_char) return {fed: false, idx: -1, wait: true};
    }
}
const __tbSalah = (ch) => { const p = 'asdfghjklqwertyuiopzxcvbnm'; let w = ch;
    while (w === ch || w === String(ch).toLowerCase()) w = p[Math.floor(Math.random() * p.length)]; return w; };
let fed = '';
const t0 = Date.now();
return new Promise((selesai) => {
    const berhenti = () => selesai(
        fed ? {fed: true, idx: c.cur_char_index, huruf: fed} :
              {fed: false, idx: c.cur_char_index});
    const langkah = () => {
        if (c.has_ended || Date.now() - t0 > 3500) { berhenti(); return; }
        const cur = c.cur_char ? String(c.cur_char.chr) : '';
        if (!cur) { berhenti(); return; }
        const sebelum = c.cur_char_index;
        // target bintang (v4 N7): Dart mengatur jadwal 1 huruf per
        // panggilan, jeda = waktu nyata sejak huruf sebelumnya, dan huruf
        // salah yang disengaja (hanya huruf a-z)
        const pace = window.__tbPace;
        if (pace) {
            window.__tbPace = null;
            let k = cur, salah = false;
            if (pace.salah && /[a-z]/i.test(cur)) { k = __tbSalah(cur); salah = true; }
            c.record_keydown_time(k, pace.ms);
            fed = k;
            selesai({fed: true, idx: c.cur_char_index, huruf: k, salah: salah, paced: true});
            return;
        }
        // dua argumen: lihat catatan di atas (varian baru wajib waktu)
        c.record_keydown_time(cur, 109);  // 109ms/huruf = 110wpm terukur
        // VARIAN BARU mengkonsumsi ASINKRON (tick game sendiri) - dulu
        // idx dicek seketika = selalu 'belum dikonsumsi' = rantai
        // berhenti tiap huruf & feeder lama ikut nyerang. Kini tunggu
        // maks 8x60ms sampai idx maju.
        let nunggu = 0;
        const cek = () => {
            if (c.cur_char_index !== sebelum) {
                fed += cur;
                setTimeout(langkah, 60);
                return;
            }
            if (++nunggu > 8 || c.has_ended) { berhenti(); return; }
            setTimeout(cek, 60);
        };
        cek();
    };
    langkah();
});
"""


def _core_bridge_frame():
    """Frame yg punya jembatan core GAME BARU: window.core (iframe
    balloonvalley/monsterattack - live 15 Nov: cur_char/
    record_keydown_time ada, URL frame kosong di playwright!) atau
    Phaser core (main frame sportal .play). HANYA keluarga phaserNN/
    balloon: frame coreclassictyping pelajaran NORMAL juga punya
    window.core - dulu probe semua frame = pelajaran normal ikut
    ter-feed pace balon ~185wpm tetap ngebatch, keluhan user 15 Nov.
    Cache 3 dtk, re-validate kalau frame mati."""
    kini = time.time()
    cached = getattr(state, "_balloon_bridge", None)
    if cached and kini - cached[1] < 3.0:
        try:
            if cached[0].evaluate("() => 1") == 1:
                return cached[0]
        except Exception:
            pass
    for fr in jsutil.all_frames():
        try:
            if fr is state.PAGE.main_frame:
                # game Phaser lama di frame utama sportal .play saja
                u = (fr.url or "").lower()
                if "sportal" in u and ".play" in u:
                    ada = jsutil.run_js(
                        "return !!(window.core || (window.Phaser && "
                        "Phaser.GAMES && Phaser.GAMES.length));", fr)
                    if ada:
                        state._balloon_bridge = (fr, kini)
                        return fr
                continue
            # iframe game: href DI DALAM frame satu-satunya kebenaran
            # (URL metadata playwright sering kosong saat mount awal)
            ada = jsutil.run_js(
                "const h = String(location.href);"
                # \d satu backslash di JS: dulu \\\\d = backslash literal
                # -> phaser02monsterattack TAK PERNAH kena, cuma jalur
                # 'balloon' lolos = yeti tak di-feed selamanya (live 16
                # Nov, reproduksi di laptop dev)
                "if (!/phaser\\d+|balloon/i.test(h)) return false;"
                "return !!(window.core || (window.Phaser && Phaser.GAMES"
                " && Phaser.GAMES.length));", fr)
            if ada:
                state._balloon_bridge = (fr, kini)
                return fr
        except Exception:
            continue
    state._balloon_bridge = None
    return None


_MAJU_LABEL = ("['next', 'move on', 'continue', 'lanjut', "
               "'lanjutkan', 'play next', 'next level', 'keep going', "
               "'done']")

_MAJU_DASAR = r"""
const maju = __LABEL__;
const cocok = (el) => {
  const t = (el.innerText || '').trim().toLowerCase();
  if (t && maju.some(w => t.includes(w))) return true;
  const a = ((el.getAttribute('aria-label') || '') + ' ' +
             (el.getAttribute('title') || '')).toLowerCase();
  return !!a && maju.some(w => a.includes(w));
};
for (const el of document.querySelectorAll('button, a, [role=button]')) {
  if (!cocok(el)) continue;
  const r = el.getBoundingClientRect();
  if (r.width < 30 || r.height < 12) continue;
  __AKSI__
}
return null;
"""

_CARI_MAJU_JS = _MAJU_DASAR.replace("__LABEL__", _MAJU_LABEL).replace(
    "__AKSI__",
    "  const label = (el.innerText || '').trim().slice(0, 20) || "
    "el.getAttribute('aria-label') || 'tombol'; "
    "el.click(); "
    "return label;")
_CEMAI_MAJU_JS = _MAJU_DASAR.replace("__LABEL__", _MAJU_LABEL).replace(
    "__AKSI__", "  return true;")
_TITIK_MAJU_JS = _MAJU_DASAR.replace("__LABEL__", _MAJU_LABEL).replace(
    "__AKSI__",
    "  return {x: r.x + r.width / 2, y: r.y + r.height / 2};")

_CARI_ULANG_JS = r"""
const ulang = ['try again', 'press enter', '→'];
for (const w of ulang) {
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
"""

def try_balloon_core():
    """Balloon valley new-look: feed via jembatan core (window.core
    iframe ATAU Phaser core main frame). Pace: ketik cur_char sekali,
    tunggu game mengonsumsi (idx maju) sebelum huruf berikut - dulu
    burst 14 huruf instan diterima tapi balon kabur = hati hilang
    (keluhan user 15 Nov). Return True kalau ada aksi."""
    fr = _core_bridge_frame()
    if fr is None:
        # GERBANG AUDIO 'Ready to start?' (live 17 Nov, yeti): game
        # menuntut klik Start sebelum iframe terpasang - tanpa ini bot
        # berdiri selamanya di depan gerbang. Klik sekali per 5 dtk,
        # cuma di halaman lesson .play & teks gerbang terlihat.
        if time.time() - getattr(state, "_gerbang_audio_t", 0) < 5:
            return False
        try:
            main = state.PAGE.main_frame
            u = (main.url or "").lower()
            if ".play" not in u or "sportal" not in u:
                return False
            klik = jsutil.run_js(r"""
if (!/ready to start/i.test(document.body.innerText || ''))
  return false;
const el = Array.from(document.querySelectorAll('button'))
  .find(b => /^start\b/i.test((b.innerText || '').trim())
       && b.getBoundingClientRect().width > 30);
if (!el) return false;
el.click();
return true;
""", main)
            if klik:
                state._gerbang_audio_t = time.time()
                state.last_action_time = time.time()
                print("[Minigame/Balloon] gerbang audio 'Ready to "
                      "start?' - Start diklik")
                return True
        except Exception:
            pass
        return False
    res = jsutil.run_js(BALLOON_STATE_JS, fr)
    if not res:
        return False
    if res.get("ended"):
        # Layar akhir - poll tombol MAJU di SEMUA frame SEGAR tiap
        # siklus (dulu: frame utama + frame CACHE; iframe hasil kadang
        # DIGANTI game -> cache mati, klik tak pernah sampai = 'next
        # sudah muncul tapi bot nunggu lama' - live teman user 3.5.2).
        # el.click() juga kadang diabaikan game selama animasi tombol
        # belum selesai -> kalau tombol masih ada setelah klik,
        # eskalasi klik mouse ASLI via CDP (isTrusted, ala modal
        # premium lama). Sambil nunggu: klik tengah canvas tiap 1.2
        # dtk = skip animasi (efek 'animation stopped' yang memang
        # diinginkan). Fallback 25 dtk: ulang level.
        if not getattr(state, "_balloon_end_t", 0):
            state._balloon_end_t = time.time()
        if time.time() - getattr(state, "_balloon_skip_t", 0) > 1.2:
            state._balloon_skip_t = time.time()
            jsutil.run_js(r"""
const c = document.querySelector('canvas');
if (c) { const r = c.getBoundingClientRect();
  const o = {bubbles: true, clientX: r.x + r.width / 2,
             clientY: r.y + r.height / 2};
  c.dispatchEvent(new MouseEvent('pointerdown', o));
  c.dispatchEvent(new MouseEvent('pointerup', o));
  c.dispatchEvent(new MouseEvent('click', o));
}""", fr)
        klik = None
        fr_lbl = ""
        fr_obj = None
        for f2 in jsutil.all_frames():
            k2 = jsutil.run_js(_CARI_MAJU_JS, f2)
            if k2:
                klik = k2
                fr_obj = f2
                fr_lbl = jsutil.frame_label(f2)
                break
        if klik:
            # level ini TAMAT sesi ini -> dorong jangkar rentang ke
            # level BERIKUTNYA. Dulu jangkar diam di LEVEL_START:
            # validator 'kembali ke level' menyeret balik ke level
            # yang barusan selesai begitu user memutus dengan
            # browsing (live 18 Nov: 217 tamat -> diseret balik ke
            # yeti terus = seolah dibajak)
            try:
                _angka = re.search(r"\d+", state.STATUS_LABEL or "")
                if _angka:
                    state._range_max_seen = max(
                        getattr(state, "_range_max_seen", 0),
                        int(_angka.group()) + 1)
            except Exception:
                pass
            masih = jsutil.run_js(_CEMAI_MAJU_JS, fr_obj)
            if masih:
                titik = jsutil.run_js(_TITIK_MAJU_JS, fr_obj)
                if titik and titik.get("x"):
                    typing_core._mark_bot_click()
                    try:
                        state.PAGE.mouse.click(titik["x"], titik["y"])
                        print(f"[Minigame/Balloon] layar akhir - klik "
                              f"mouse asli {klik!r} @{fr_lbl}")
                    except Exception:
                        print(f"[Minigame/Balloon] layar akhir - klik "
                              f"{klik!r} @{fr_lbl} (mouse gagal)")
                else:
                    print(f"[Minigame/Balloon] layar akhir - klik "
                          f"{klik!r} @{fr_lbl} (tanpa titik)")
            else:
                print(f"[Minigame/Balloon] layar akhir - klik {klik!r} "
                      f"@{fr_lbl}")
            state.last_action_time = time.time()
            state._balloon_end_t = 0
            return False
        if time.time() - state._balloon_end_t > 25:
            klik2 = jsutil.run_js(_CARI_ULANG_JS)
            if not klik2:
                klik2 = jsutil.run_js(_CARI_ULANG_JS, fr)
            if klik2:
                print(f"[Minigame/Balloon] tanpa tombol maju 25 dtk - "
                      f"ulang {klik2!r}")
            state._balloon_end_t = 0
        return True
    chr_ = res.get("chr")
    idx = res.get("idx")
    kini = time.time()
    state._balloon_end_t = 0     # game hidup lagi = reset penanda akhir
    last = getattr(state, "_balloon_core_last", None)
    if last and last[0] == chr_ and last[1] == idx \
            and kini - last[2] < 3.5:
        return True     # sudah diketik, game belum konsumsi = klaim siklus (dulu False -> cabang pop-up menyela, bot mundur, monster menyusul - live 17 Nov)
    if kini - getattr(state, "_balloon_core_typed", 0.0) < 0.12:
        return True      # panggil ulang cepat = klaim siklus
    fed = jsutil.run_js(BALLOON_FEED_JS, fr)
    if fed and fed.get("fed"):
        huruf = fed.get("huruf", "")
        state._balloon_core_last = (chr_, fed.get("idx", idx), kini)
        state._balloon_core_typed = kini
        print(f"[Minigame/Balloon] core: {huruf!r} idx->{fed.get('idx')}")
        state.stats["phaser"] += len(huruf)
        state.last_action_time = time.time()
        return True
    return False


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
    """Frame game balloon valley: (a) iframe dgn 'balloon' di URL,
    (b) NEW LOOK: game DI FRAME UTAMA halaman sportal .play, (c) iframe
    baru-mount yang URL-nya KOSONG di playwright (live 15 Nov: 3 frame
    '' - deteksi lama tak pernah cocok = probe & feeder tak jalan).
    Selalu catat waktu terakhir dilihat utk peluruhan supervisor."""
    kini = time.time()
    for fr in jsutil.all_frames():
        try:
            u = fr.url or ""
            # 'balloon' klasik ATAU seluruh keluarga game baru
            # phaser01balloonvalley / phaser02monsterattack / dst -
            # prarolong game bisa 14 dtk; jangan sampai void
            if "balloon" in u or re.search(r"phaser\d+", u):
                state._balloon_frame_seen = kini
                if "balloon" in u:
                    _probe_iframe(fr)
                return fr
        except Exception:
            continue
    try:
        main = state.PAGE.main_frame
        u = (main.url or "").lower()
        if "sportal" in u and ".play" in u:
            state._balloon_frame_seen = kini
            return main
    except Exception:
        pass
    # frame ber-URL kosong: cek ada Phaser di dalamnya (cache 3 dtk
    # biar tak evaluate tiap siklus)
    if kini - getattr(state, "_balloon_empty_ck", 0.0) < 3.0:
        return state._balloon_empty_frame
    state._balloon_empty_ck = kini
    for fr in jsutil.all_frames():
        try:
            u = (fr.url or "").strip()
            if u and u != "about:blank":
                continue
            ada = jsutil.run_js(
                "return !!(window.Phaser && Phaser.GAMES "
                "&& Phaser.GAMES.length);", fr)
            if ada:
                state._balloon_frame_seen = kini
                state._balloon_empty_frame = fr
                _probe_iframe(fr)
                return fr
        except Exception:
            continue
    state._balloon_empty_frame = None
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
