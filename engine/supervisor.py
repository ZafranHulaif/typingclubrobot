"""Loop utama: supervisor det machine."""

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
from .lessons import games
from .lessons import holdkey
from .lessons import intro
from . import jsutil
from . import levels
from .lessons import ocr
from . import recovery
from . import rentang
from .lessons import screenkey
from . import session
from .lessons import standard
from .lessons import tutorial
from . import typing_core
from .lessons import video
from .config import (LIST_URL)
from .jstemplates import (BUKA_BLOK_JS, MODAL_HINT_JS)




def main_loop():
    if state.PAGE is None:
        try:
            browser.connect()
        except SystemExit:
            return
    # Validasi level start terkunci kini non-blokir di dalam loop
    # (_range_validate_step) setelah gerbang login - lihat catatan di
    # fungsinya (bug: 00:04: blokir pra-loop membekukan semuanya).
    state._range_validated = False
    state._range_max_seen = 0    # level tertinggi yang dilihat sesi ini (anti lompat balik)
    renderer_gagal = 0
    pulih_selesai = 0
    _nav_time = 0.0           # waktu tiba di URL saat ini (grace pemulihan)
    _tunggu_rentang_baru = False
    state._range_jump_done = False   # lompat ke LEVEL_START hanya sekali, dan
    # hanya kalau saat mulai tidak sedang berada di lesson (user yang membuka
    # level sendiri = kerjakan saja level itu, jangan paksa lompat)
    try:
        # PENTING: baca URL lewat properti (lokal, instan), BUKAN
        # _real_url (round-trip JS ke renderer). Bug live: renderer yang
        # di-suspend Windows (tab lama dibuang) menggantungkan evaluate
        # TANPA timeout -> bot mati diam total tepat setelah 'Terhubung!'
        # sebelum sempat masuk loop (gerbang _page_alive belum jalan).
        state._range_jump_done = ".play" in ((state.PAGE.url or "")
                                             if state.PAGE else "")
        if state._range_jump_done and state.LEVEL_START > 1:
            print(f"[RENTANG] sudah ada lesson terbuka - kerjakan ini dulu "
                  f"(lompatan ke level {state.LEVEL_START} dilewati).")
    except Exception:
        pass
    while True:
        try:
            if state.STOP:
                print("Bot dihentikan.")
                break
            if state.PAUSED:
                time.sleep(0.2)
                continue

            # Gerbang kesehatan renderer sebelum evaluasi apa pun: evaluate
            # di renderer suspend menghang tanpa timeout (bug: log mati
            # total tepat setelah 'Terhubung!'). 2x gagal -> restart browser.
            if not session._page_alive(state.PAGE):
                renderer_gagal += 1
                if renderer_gagal == 1:
                    print("[PEMULIHAN] Tab tidak merespons, memberi 5 detik...")
                    time.sleep(5)
                    continue
                if time.time() - pulih_selesai < 60:
                    print("[PEMULIHAN] Baru saja restart tapi masih mati - "
                          "stop (cek jendela browser secara manual).")
                    state.STOP = True
                    break
                if session._recover_renderer():
                    pulih_selesai = time.time()
                    renderer_gagal = 0
                    continue
                state.STOP = True
                break
            renderer_gagal = 0

            # anti-pause ringan tiap iterasi (banner "Start Typing dll.")
            typing_core.keep_alive_frames()
            session._sweep_stripe_tabs()
            session._sweep_ad_tabs()

            # Browser ditutup user: page.url Playwright tetap melaporkan
            # URL lama (stale, tanpa round-trip) -> STATUS_URL tak berubah
            # dan kartu GUI terpaku 'Mengerjakan level ...' (keluhan live).
            # is_connected() lokal/instan - tanpa round-trip ke renderer.
            # Daftar halaman kosong ikut dicek: window ditutup bisa
            # menyisakan proses hidup beberapa detik (is_connected masih
            # True) padahal tidak ada tab lagi.
            if (state.browser is None or not state.browser.is_connected()
                    or not browser._pages_alive()):
                if not state.BROWSER_CLOSED:
                    state.BROWSER_CLOSED = True
                    state.STATUS_URL = ""
                    state.STATUS_LABEL = ""
                    print("[BOT] Browser ditutup - bot menunggu. Tekan Stop "
                          "lalu Start untuk buka browser baru.")
                time.sleep(0.5)
                continue
            state.BROWSER_CLOSED = False

            url = state.PAGE.url
            # page.url Playwright bisa stale: tab berisi Stripe checkout
            # masih melaporkan URL edclub . Percayai
            # location.href; kalau host = stripe/checkout = tab dibajak.
            try:
                real = browser._real_url(state.PAGE)
            except Exception:
                real = url
            if browser._is_edclub_url(real):
                url = real
            else:
                try:
                    rh = (urlparse(real).hostname or "").lower()
                except Exception:
                    rh = ""
                if "stripe" in rh or "checkout" in rh:
                    url = real
            state.STATUS_URL = url
            # label level bisa kosong saat pertama datang (halaman belum
            # selesai memuat) -> coba lagi berkala sampai dapat
            if not state.STATUS_LABEL and time.time() - state._label_retry > 2:
                state._label_retry = time.time()
                try:
                    state.STATUS_LABEL = levels._level_label()
                except Exception:
                    pass
            if not browser._is_edclub_url(url):
                # tab bisa ter-bawa navigasi ke Stripe checkout (dibuktikan
                # live: klik di area iframe premium = top-level navigation).
                # Tutup tab stripe yang menganggur, lalu cari/buat tab edclub.
                session._sweep_stripe_tabs(force=True)
                # coba cari ulang tab edclub (prioritas yang di halaman .play)
                found = None
                for pg in state.browser.contexts[0].pages:
                    pu = browser._real_url(pg)
                    if browser._is_edclub_url(pu):
                        if ".play" in pu:
                            found = pg
                            break
                        if found is None:
                            found = pg
                if found:
                    state.PAGE = found
                else:
                    # Tidak ada tab edclub sama sekali. Buka tab baru (bukan
                    # goto dari konteks Stripe - pernah diblokir Brave), lalu
                    # tutup tab lama. Lesson yang sama dibajak 2x = level
                    # premium rusak -> langsung lompat ke berikutnya.
                    if time.time() - state._nav_try > 10:
                        state._nav_try = time.time()
                        key = state.last_url if (state.last_url and ".play" in state.last_url) else url
                        n = state._hijack_counts.get(key, 0) + 1
                        state._hijack_counts[key] = n
                        if n >= 2 and levels._skip_to_next_lesson(
                                "tab berulang kali dibawa ke Stripe"):
                            state._hijack_counts.pop(key, None)
                            continue
                        target = key if ".play" in key else LIST_URL
                        newpg = None
                        try:
                            newpg = browser._tab_latar(state.PAGE.context)
                            newpg.goto(target, timeout=25000)
                            old = state.PAGE
                            state.PAGE = newpg
                            try:
                                if old is not newpg:
                                    old.close()
                            except Exception:
                                pass
                            state.last_url = state.PAGE.url
                            state.last_action_time = time.time()
                            print(f"[NAV] tab dibajak Stripe - tab baru ke "
                                  f"{target.split('/')[-1]}")
                        except Exception:
                            if newpg is not None:
                                try:
                                    newpg.close()
                                except Exception:
                                    pass
                    time.sleep(1)
                    continue

            low = url.lower()
            session._login_patrol(url)
            if state.NEEDS_LOGIN:
                # Jangan buang level untuk sesi mati: berhenti mengetik,
                # GUI memunculkan popup; lanjut sendiri setelah login.
                if time.time() - state._login_notice > 30:
                    state._login_notice = time.time()
                    print("[LOGIN] Menunggu login edclub di jendela browser bot...")
                time.sleep(1)
                continue
            if not state.LOGIN_DICEK:
                # gerbang keras: status login belum pasti (belum terbaca
                # in/out). Dilarang mengetik / recovery / klik apapun.
                # Bug live 2x: saat status belum terbaca, (1) popup rentang
                # dimunculkan padahal belum login, (2) recovery macetnya
                # daftar pelajaran malah membuka pelajaran gratis 116 dan
                # bot mengetik tanpa login & tanpa rentang.
                if time.time() - state._login_notice > 15:
                    state._login_notice = time.time()
                    print("[LOGIN] Menunggu status login terbaca "
                          "(jangan melakukan apapun dulu)...")
                time.sleep(1)
                continue
            if "login" in low or "signin" in low or "sign-in" in low or "signup" in low:
                # belum login: jangan spam recovery, tunggu user login manual
                if time.time() - state._login_notice > 30:
                    state._login_notice = time.time()
                    print("[LOGIN] Halaman login terdeteksi. Login dulu di "
                          "browser bot, bot menunggu di sini...")
                time.sleep(2)
                continue

            # validasi level start terkunci (non-blokir, hanya setelah
            # status login pasti; selama menunggu jawaban GUI, loop berhenti
            # di sini dan tidak menyentuh halaman)
            if not levels._range_validate_step():
                state.STOP = True
                return

            # user asli sedang memakai browser bot di luar lesson (daftar
            # level, pengaturan, profil) - jangan ambil alih; tunggu sampai
            # user diam atau masuk lesson sendiri. >2 menit -> GUI bertanya.
            if ".play" not in url and typing_core._user_active(25.0):
                typing_core._wait_for_user(url)
                continue
            typing_core._user_idle_again(url)

            if url != state.last_url:
                # level baru: cooldown Phaser dari game sebelumnya tidak
                # berlaku lagi (dulu bikin minigame berikutnya tunda 20 dtk)
                state._phaser_cooldown["until"] = 0.0
                state._phaser_freeze["url"] = ""
                state._phaser_freeze["count"] = 0
                state._phaser_freeze["clicked"] = False
                state._intro_flow = False   # layar intro pertama level ini = settle penuh
                state._premlock_since = 0.0
                state.STATUS_LABEL = ""
                if state.last_url:
                    print(f"[PROGRES] {levels._level_label() or '?'} "
                          f"({state.last_url.split('/')[-1]} -> {url.split('/')[-1]})  "
                          f"(std={state.stats['std']} tut={state.stats['tut']} mini={state.stats['mini']} "
                          f"phaser={state.stats['phaser']} ocr={state.stats['ocr']} hold={state.stats['hold']} "
                          f"video={state.stats['video']} popup={state.stats['popup']})")
                # label level asli untuk indikator GUI (bukan rumus URL:
                # nomor URL acak per akun dan pernah salah terus)
                try:
                    state.STATUS_LABEL = levels._level_label()
                except Exception:
                    state.STATUS_LABEL = ""
                state.last_url = url
                # Navigasi = aktivitas: budget stall baru untuk halaman
                # yang baru dibuka. Dulu timer stall tidak direset saat
                # pindah halaman -> waktu menunggu dialog rentang/login
                # terakumulasi -> tepat setelah lompatan rentang, recovery
                # menembak '[tunda] 107s' padahal halaman baru dimuat
                # .
                state.last_action_time = time.time()
                _nav_time = time.time()

            # permintaan bangun peta level dari GUI
            if state.ASK_BUILD_MAP:
                state.ASK_BUILD_MAP = False
                levels.build_level_map()
                continue
            # pemulihan manual dari tombol GUI: jalankan recovery sekarang
            # (satu thread dengan Playwright - aman dipanggil di sini)
            if state.ASK_RECOVERY:
                state.ASK_RECOVERY = False
                print("[PEMULIHAN] diminta manual - memeriksa & memulihkan "
                      "lesson...")
                if recovery.recover_and_restart_lesson():
                    state.last_action_time = time.time()
                continue
            # rentang sedang ditanyakan GUI -> berhenti bergerak (dulu:
            # recovery menembak & membuka level terdepan L106 saat popup
            # rentang masih terbuka)
            if state.AWAIT_RANGE:
                _tunggu_rentang_baru = True
                time.sleep(0.3)
                continue
            if _tunggu_rentang_baru:
                _tunggu_rentang_baru = False
                # dialog rentang selesai dijawab: budget stall baru (waktu
                # user berpikir di depan popup bukan 'halaman mati')
                state.last_action_time = time.time()
            # rentang level pilihan user (lompat awal / berhenti di akhir)
            if rentang._range_check(url):
                continue

            # Watch window: klik X modal premium sebelum penutup pop-up
            # dan handler mana pun. modal premium edclub
            # hanya sekali per page-load; ESC/klik salah dari penutup
            # pop-up pernah mengkonsumsi modal itu (log 08:02: 'kirim ESC
            # (premium)') -> level premium berikutnya tak pernah dapat
            # modal -> game beku. X diklik = edclub lanjut sendiri.
            # (berlaku sepanjang waktu, bukan hanya awal level: upsell
            # premium juga muncul di akhir lesson, macam di 2967)
            if games._premium_modal_action() == "clicked":
                state.last_action_time = time.time()
                time.sleep(0.8)
                continue

            # Level video DULUAN sebelum penutup pop-up: dulu penutup
            # mencocokkan elemen X di halaman video, klik berulang tanpa
            # hasil + eskalasi ESC/klik mouse - iterasi selalu 'continue'
            # sebelum handler video giliran (video tak pernah dilompat,
            # halaman malah terbawa ke halaman program; log live 116).
            if ".play" in url and video.handle_video_level():
                continue

            if jsutil.close_overlays_all_frames():
                state.stats["popup"] += 1
                time.sleep(0.6)
                continue

            det, frame, data = jsutil.detect_all_frames()

            if det == "std":
                standard.handle_standard(frame, data)
            elif det == "tut":
                tutorial.handle_tutorial(frame, data)
            elif det == "mini":
                games.handle_minigame(frame, data)
            elif det == "score":
                if typing_core.advance_score_screen():
                    state.last_action_time = time.time()
                time.sleep(0.6)
            else:
                # Modal premium: setelah watch window, modal zombie
                # (fullscreen checkout tanpa X) -> tunggu 12 dtk lalu
                # lewati sesuai urutan daftar.
                pm = games._premium_modal_action()
                if pm == "clicked":
                    state.last_action_time = time.time()
                    time.sleep(0.6)
                    continue
                if pm and pm.get("zombie"):
                    if state._premlock_since == 0.0:
                        state._premlock_since = time.time()
                        print("[Premium] modal fullscreen tanpa X "
                              "(checkout Stripe) - menunggu...")
                    elif time.time() - state._premlock_since > 12.0:
                        if levels._skip_to_next_lesson("modal premium tak tertutup"):
                            state._premlock_since = 0.0
                            continue
                else:
                    state._premlock_since = 0.0
                if intro.handle_intro_steps():
                    time.sleep(0.05)
                    continue
                if games.handle_phaser_minigame():
                    time.sleep(0.3)
                    continue
                if holdkey.try_hold_level():
                    time.sleep(0.4)
                    continue
                if screenkey.click_screen_keyboard():
                    time.sleep(0.4)
                    continue
                if not ocr.try_ocr_minigame(data or {}):
                    stalled = time.time() - state.last_action_time
                    # user asli aktif (memegang halaman)? Semua aksi ambil-
                    # alih (klik lanjut, ganti tab, recovery) ditunda -
                    # dulu intervensi user salah dibaca 'level selesai/
                    # mati' dan bot menekan tombol sendiri.
                    user_sibuk = typing_core._user_active(25.0)
                    # heartbeat: bot tidak boleh pernah diam tanpa kabar.
                    # (dulu: det unknown = sunyi total, kelihatan mati)
                    if stalled > 10 and time.time() - state.last_debug_dump > 10:
                        state.last_debug_dump = time.time()
                        print(f"[TUNDA] tidak ada aktivitas {stalled:.0f}s di "
                              f"{url.split('/')[-1]} - dumping state...")
                        jsutil.dump_debug_info()
                    # Layar gelap premium: X modal (termasuk modal terblokir
                    # CSS) dicoba watch window tiap iterasi - klik X = edclub
                    # lanjut sendiri ke lesson berikutnya. Tombol lanjut
                    # dicoba untuk sisa modal yang sudah tertutup (edclub
                    # bug, level 106). Dulu: tanpa tombol lanjut = langsung
                    # di-skip di 6 dtk - di load dingin modal premium bisa
                    # baru muncul/setelah X terpasang lewat dari 6 dtk
                    # (live: 3 level premium ter-skip beruntun di awal
                    # rentang 540), dan modal terblokir CSS bisa TANPA X
                    # (animasi tampil tidak jalan di display:none) ->
                    # blokir dibongkar sesaat supaya modal tampil dan jalur
                    # klik X terbukti yang bekerja. Baru setelah 20 dtk
                    # tanpa kemajuan level dianggap rusak.
                    if stalled > 6 and not user_sibuk:
                        prem = False
                        for fr2 in jsutil.all_frames():
                            h = jsutil.run_js(MODAL_HINT_JS, fr2)
                            if h and h.get("premium"):
                                prem = True
                                break
                        if prem:
                            # tanpa Enter (form checkout bisa menangkap Enter)
                            # - langsung klik mouse asli di tombol lanjut.
                            try:
                                loc = state.PAGE.locator(
                                    ".navbar-continue, a.navbar-continue").first
                                if loc.count() and loc.is_visible():
                                    loc.click(timeout=2000)
                                    print("[Premium] layar gelap premium - "
                                          "lanjut ke lesson berikutnya")
                                    state.last_action_time = time.time()
                                    continue
                            except Exception:
                                pass
                            if stalled > 8:
                                for fr2 in jsutil.all_frames():
                                    if jsutil.run_js(BUKA_BLOK_JS, fr2):
                                        print("[Premium] modal premium tanpa X "
                                              "saat diblokir - blokir dibuka "
                                              "sesaat")
                                        break
                            if stalled > 20 and levels._skip_to_next_lesson(
                                    "layar gelap premium tanpa tombol lanjut"):
                                state.last_action_time = time.time()
                                continue
                            time.sleep(0.4)
                            continue
                    # Tab edclub lain mungkin punya pekerjaan (bot bisa
                    # nyangkut di tab yang salah setelah navigasi manual).
                    if stalled > 6 and not user_sibuk and recovery._switch_to_playable_tab():
                        continue
                    if stalled > 12 and not user_sibuk and time.time() - state._last_recovery > 25 \
                            and time.time() - _nav_time > 25:
                        # halaman kemungkinan mati/kosong -> pulihkan otomatis
                        # (grace 25 dtk sejak tiba: halaman yang baru dinavigasi
                        # (mis. lompatan rentang) boleh lambat memuat - jangan
                        # langsung dikira mati dan di-reload). Recovery DULU:
                        # dulu probe daftar level (stalled>10) berjalan lebih
                        # dulu & memblokir puluhan detik -> freeze panjang di
                        # transisi lesson (keluhan live 245 -> 246).
                        if not recovery.recover_and_restart_lesson():
                            state._last_recovery = time.time()
                    if stalled > 20 and not user_sibuk:
                        # level terkunci = halaman .play kosong (live: L100
                        # logout memuat body kosong) - reload tidak akan
                        # menolong; lompat ke urutan daftar. Di-throttle 60
                        # dtk: probe memblokir (redirect daftar), jangan
                        # diulang tiap iterasi.
                        nomor = 0
                        if state.STATUS_LABEL.startswith("L"):
                            try:
                                nomor = int(state.STATUS_LABEL[1:])
                            except ValueError:
                                pass
                        if (nomor and state._unlock_set is None
                                and time.time() - state._unlock_ck > 60):
                            state._unlock_ck = time.time()
                            state._unlock_set = levels._read_unlock_set()
                        if nomor and state._unlock_set and nomor not in state._unlock_set:
                            if levels._skip_to_next_lesson("level terkunci untuk akun"):
                                state.last_action_time = time.time()
                                continue

            time.sleep(0.15)

        except KeyboardInterrupt:
            print("Dihentikan manual.")
            break
        except Exception as ex:
            # jangan menelan exception diam-diam (bug: loop error 2x/dtk
            # tanpa satu baris log pun - bot 'mati diam'). Throttled 30 dtk.
            if time.time() - state._last_loop_err > 30:
                state._last_loop_err = time.time()
                print(f"[LOOP] error (diabaikan, lanjut): {ex!r}")
            time.sleep(0.5)

    session._sweep_stripe_tabs(force=True)
    print(f"Selesai. Total: lesson={state.stats['std']} tutorial={state.stats['tut']} "
          f"minigame={state.stats['mini']} phaser={state.stats['phaser']} ocr={state.stats['ocr']} "
          f"hold={state.stats['hold']} video={state.stats['video']} popup={state.stats['popup']}")


if __name__ == "__main__":
    main_loop()
