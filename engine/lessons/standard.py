"""Level ketik standar (verifikasi per karakter)."""

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
from . import games
from .. import jsutil
from .. import typing_core
from ..jstemplates import (HOLD_LESSON_JS, MODAL_HINT_JS, QUIET_ALIVE_JS, START_BANNER_JS)




def handle_standard(frame, text):
    # Level terkunci premium: modal premium menutupi lesson, input mati.
    # Dulu bot mencoba mengetik 3x (gagal, buang waktu) bahkan sempat
    # mengklik tombol CTA premium yang membawa ke Stripe Checkout.
    # Sekarang: langsung lewati level via tombol lanjut (klik mouse asli).
    for fr in jsutil.all_frames():
        hint = jsutil.run_js(MODAL_HINT_JS, fr)
        if hint and hint.get("premium"):
            print("[Premium] level terkunci premium - lewati via tombol lanjut")
            try:
                typing_core._tandai_klik_bot()
                state.PAGE.locator(".navbar-continue, a.navbar-continue") \
                    .first.click(timeout=2500)
            except Exception:
                pass
            state.last_action_time = time.time()
            return True
    hold = jsutil.run_js(HOLD_LESSON_JS, frame) or {}
    hold_key = hold.get("key")

    rem = typing_core.read_remaining(frame)
    if rem is None:
        return False
    # anti-busur: teks sama persis & sudah dicoba 3x -> diamkan (biarkan
    # handler lain / recovery yang bekerja)
    if rem == state._std_last_rem:
        state._std_attempts += 1
        if state._std_attempts > 3:
            return False
    else:
        state._std_last_rem = rem
        state._std_attempts = 1

    print(f"[Standard] Sisa {len(rem)} karakter: {rem[:24]!r}..."
          + (f" (TAHAN {hold_key!r})" if hold_key else ""))
    typing_core.focus_frame(frame)

    # stabilisasi: sisa teks tidak berubah sebentar (halaman siap)
    for _ in range(8):
        time.sleep(0.12)
        r2 = typing_core.read_remaining(frame)
        if r2 is None or r2 != rem:
            rem = r2
            continue
        break
    if rem is None:
        return False

    # aktifkan lesson: klik banner "Start Typing" jika sedang tampil
    if jsutil.run_js(START_BANNER_JS, frame):
        print("[Standard] banner Start Typing diklik")
        time.sleep(0.4)
        rem = typing_core.read_remaining(frame) or ""

    typed_any = False
    try:
        if hold_key:
            state.PAGE.keyboard.down(hold_key)
            time.sleep(0.15)
        # ketik per-karakter terverifikasi (prinsip: tidak boleh salah):
        # Karakter berikutnya tidak pernah dikirim sebelum karakter saat ini
        # terverifikasi dikonsumsi dengan benar oleh engine lesson.
        # - salah tidak pernah berantai: deteksi terjadi 1 karakter, bukan 20.
        # - kalau konsumsi tidak persis (keystroke hilang / DOM berganti /
        # banner pause), ketikan berhenti dan realign ke DOM - tidak
        # pernah lanjut berdasarkan asumsi.
        # - modifier (Shift dll.) dilepas dulu: sisa modifier = karakter
        # salah pada lesson berikutnya.
        # - karakter yang ditandai salah (_err) segera di-Backspace sekali;
        # kalau situs tidak mengizinkan, dicatat dan lanjut (maks 1 char).
        # penting: selama mengetik tidak ada klik apa pun - klik di tengah
        # ketikan bisa me-reset lesson.
        typing_core._clear_modifiers()
        pre_err = typing_core.count_errors(frame)
        if pre_err:
            print(f"[Standard] {pre_err} karakter salah sudah ada sebelum mulai, "
                  "coba koreksi dengan Backspace")
            try:
                for _ in range(pre_err):
                    state.PAGE.keyboard.press("Backspace")
                    time.sleep(0.06)
                time.sleep(0.4)
            except Exception:
                pass
            left = typing_core.count_errors(frame)
            if left is not None and left < pre_err:
                rem = typing_core.read_remaining(frame) or rem
            else:
                print("[Standard] koreksi awal tidak mempan (salah terkunci) "
                      "- lanjut, akurasi lesson ini bisa < 100%")
        stall = 0
        verified = 0
        bs_ok = True
        err_prev = typing_core.count_errors(frame)
        if err_prev is None:
            err_prev = 0
        while True:
            if state.STOP:
                break
            while state.PAUSED and not state.STOP:
                time.sleep(0.15)
            if not rem:
                break
            ch = rem[0]
            t_char = time.time()
            if not typing_core.type_chars(ch):
                break
            typed_any = True
            rem2, err_after = typing_core.read_state(frame)
            if err_after is None:
                err_after = err_prev
            if err_after > err_prev and bs_ok:
                # 1 karakter tertandai salah - coba hapus sekarang
                try:
                    state.PAGE.keyboard.press("Backspace")
                    time.sleep(0.25)
                except Exception:
                    pass
                r_chk, err_chk = typing_core.read_state(frame)
                if err_chk is not None and err_chk < err_after:
                    rem2 = r_chk  # token kembali pending
                    err_after = err_chk
                else:
                    bs_ok = False
                    print("[Standard] 1 karakter salah tidak bisa dihapus "
                          "(lanjut - tercatat di akurasi)")
                    rem2 = r_chk
            if rem2 is None or rem2 == "":
                # bisa berarti selesai, tapi juga "baris berikut belum
                # muncul di DOM" (render progresif). Jangan langsung anggap
                # selesai: tunggu grace, ketik ulang tidak boleh (Enter
                # dobel = salah). Baris baru muncul < 300 ms di situs asli,
                # jadi grace singkat cukup.
                got = None
                for _ in range(8):
                    time.sleep(0.10)
                    r = typing_core.read_remaining(frame)
                    if r:
                        got = r
                        break
                if got:
                    rem = got
                    stall = 0
                    continue
                break  # benar-benar tidak ada token = lesson selesai
            if rem2 == rem:
                # Karakter tidak terkonsumsi. Penyebab umum: klik user (di
                # halaman / di luar window -> blur -> engine pause sesaat,
                # caret pindah). pulihkan sekarang, bukan tangga jeda:
                # dulu stall 1-7 menumpuk sleep 0.05+0.15 (~0.5-3 dtk
                # tersendat per klik) dan spam-klik mencapai stall>=8 ->
                # tombol lanjut diklik -> typing berhenti total (keluhan
                # live 2x). Sekarang: fokus + banner dipulihkan tiap
                # iterasi (murah, tanpa klik mouse), poll cepat; eskalasi
                # tombol lanjut hanya kalau user tidak sedang memegang
                # halaman (klik user = mouse-only watcher, aman dari
                # ketikan bot sendiri).
                stall += 1
                user_kehadian = typing_core._user_aktif(3.0)
                if user_kehadian:
                    stall = min(stall, 3)
                    if not state._stall_user_note:
                        state._stall_user_note = True
                        print("[Standard] user memegang halaman - fokus "
                              "dipulihkan terus, mengetik tidak berhenti")
                else:
                    state._stall_user_note = False
                jsutil.run_js(QUIET_ALIVE_JS, frame)
                typing_core.focus_frame(frame)
                if jsutil.run_js(START_BANNER_JS, frame):
                    print("[Standard] banner pause muncul, diklik")
                    time.sleep(0.15)
                time.sleep(0.04)
                r_retry, _ = typing_core.read_state(frame)
                if r_retry is not None and r_retry != rem:
                    rem = r_retry
                    stall = 0
                    verified += 1
                    if verified % 20 == 0:
                        typing_core.keep_alive_quiet(frame)
                    if verified % 25 == 0:
                        typing_core.esc_modals_only(frame)
                    continue
                if stall >= 8 and not user_kehadian:
                    # benar-benar macet tanpa user: kemungkinan lesson
                    # selesai tapi layar skor tidak muncul (bug situs,
                    # terbukti L87/192) - satu klik tombol lanjut langsung
                    # ke lesson berikutnya.
                    print("[Standard] ketikan tidak masuk - mungkin selesai "
                          "tanpa layar skor, coba tombol lanjut")
                    if games._phaser_try_advance():
                        state.last_action_time = time.time()
                        time.sleep(0.6)
                        return True
                    break
                err_prev = err_after
                continue
            # terkonsumsi / DOM berubah -> selalu percaya DOM terbaru
            rem = rem2
            stall = 0
            verified += 1
            err_prev = err_after
            # kalibrasi laju: overhead aktual per karakter (verifikasi dll.)
            # diukur & dikompensasikan di jeda karakter berikutnya.
            oh = (time.time() - t_char) - state._last_char_delay
            oh = min(max(oh, 0.0), 0.15)
            state._loop_overhead = 0.7 * state._loop_overhead + 0.3 * oh
            if verified % 20 == 0:
                typing_core.keep_alive_quiet(frame)
            if verified % 25 == 0:
                typing_core.esc_modals_only(frame)
    finally:
        if hold_key:
            try:
                state.PAGE.keyboard.up(hold_key)
            except Exception:
                pass
        typing_core._clear_modifiers()
    if not typed_any:
        return False
    state.last_typed_text = text
    state.stats["std"] += 1
    state.last_action_time = time.time()
    err_total = typing_core.count_errors(frame)
    if err_total:
        print(f"[Standard] lesson selesai dengan {err_total} karakter salah")

    # Tunggu transisi post-lesson. penting: keluar segera begitu URL
    # berganti (level baru) - intro/skor->level baru tidak pernah
    # menghasilkan det std/mini/tut, dulu loop ini burn deadline penuh
    # (10+8 dtk) padahal level berikutnya sudah siap dikerjakan.
    # Kasus nyata (L113): lesson selesai tapi layar skor tidak pernah
    # muncul (bug situs) - tombol lanjut ada, klik mouse asli langsung.
    entry_url = state.PAGE.url
    no_score_clicked = False
    entry_wait_start = time.time()
    deadline = time.time() + 10
    while time.time() < deadline:
        if jsutil.close_overlays_all_frames():
            time.sleep(0.6)
            continue
        det, _, _ = jsutil.detect_all_frames()
        if det == "score":
            typing_core.advance_score_screen()
            time.sleep(0.8)
        if det in ("std", "mini", "tut"):
            break
        if state.PAGE.url != entry_url:
            break   # level sudah pindah - jangan tunggu sisa deadline
        if not no_score_clicked and time.time() > entry_wait_start + 3.0:
            # 3 dtk tanpa skor/URL: kemungkinan layar skor tidak muncul
            # -> satu klik lanjut (mouse asli) menyelesaikannya.
            try:
                loc = state.PAGE.locator(".navbar-continue, a.navbar-continue").first
                if loc.count() and loc.is_visible():
                    loc.click(timeout=2000)
                    no_score_clicked = True
                    print("[Standard] layar skor belum muncul - klik "
                          "tombol lanjut")
                    time.sleep(0.8)
                    continue
            except Exception:
                pass
        time.sleep(0.25)

    deadline = time.time() + 8
    while time.time() < deadline:
        det, _, _ = jsutil.detect_all_frames()
        if det != "unknown":
            break
        if state.PAGE.url != entry_url:
            break
        time.sleep(0.2)
    state.last_action_time = time.time()
    return True
