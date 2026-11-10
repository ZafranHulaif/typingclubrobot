"""Jendela utama - bagian activity."""

import base64
import ctypes
import hashlib
import hmac
import json
import os
import queue
import re
import socket
import sys
import threading
import time
import tkinter as tk

from .widgets import _Dialog
import uuid
import zlib
from ctypes import wintypes
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from .dialogs import (_focus_browser_window, _minimize_browser_windows,
                      dialog_range, dialog_done)
from .theme import (ACCENT, BTN_FG, CARD, DIM, EDGE, FAINT, FG, GREEN, ORANGE, PANEL, RED, SETTINGS_FILE, YELLOW)
from .translator import _friendly_text


class ActivityMixin:
    """Mixin: dipadukan di gui/app.py."""

    def _app_depan(self):
        """Angkat jendela app ke depan sekali (topmost sekejap lalu lepas).
        Dipakai saat bot selesai tersambung: browser merebut fokus saat
        dibuka, user tidak perlu alt-tab hanya untuk membaca status bot."""
        try:
            self.root.attributes("-topmost", True)
            self.root.lift()
            self.root.focus_force()
            self.root.after(400,
                            lambda: self.root.attributes("-topmost", False))
        except Exception:
            pass

    def _poll(self):
        # pasang timer BERIKUTNYA di awal, bukan di akhir: callback antrean
        # bisa memblokir lama di dalam dialog modal (show() menunggu
        # window) - kalau after() ada di ekor, rantai timer mati selama
        # dialog terbuka dan _ui_queue tak pernah diproses lagi (bug:
        # popup aktivasi tidak pernah menutup sendiri).
        self.root.after(150, self._poll)
        try:
            while True:
                fn = self._ui_queue.get_nowait()
                self._safe(fn)
        except queue.Empty:
            pass
        try:
            while True:
                line = self.log_q.get_nowait()
                ramah = _friendly_text(line)
                if ramah:
                    self._aktiv_sub_teks = ramah
        except queue.Empty:
            pass

        bot = self.bot
        bot_thread_hidup = bool(self.bot_thread and self.bot_thread.is_alive())
        # app kembali ke depan 1x saat bot selesai tersambung: browser
        # selalu merebut fokus saat dibuka - tanpa ini user harus alt-tab
        # sendiri hanya untuk melihat status bot (live: terasa 'bot hilang')
        if bot_thread_hidup and getattr(bot, "PAGE", None) is not None:
            if not self._fokus_sambung:
                self._fokus_sambung = True
                self._app_depan()
        elif not bot_thread_hidup:
            self._fokus_sambung = False
        # engine selesai memuat halaman login -> angkat jendela BROWSER
        # (bukan saat masih blank: dulu user menatap layar kosong dan
        # ragu bot hidup atau tidak)
        _fokus_at = getattr(bot, "FOCUS_BROWSER_AT", 0.0) if bot else 0.0
        # mode embedded: browser = app ini sendiri - 'fokus jendela
        # browser' cuma akan mencuri/mengalihkan fokus jendela app lain
        # (bahkan jendela browser MILIK user yang kebetulan membuka
        # typingclub -> app 'minimizing itself' ala user)
        if (_fokus_at and _fokus_at > self._fokus_browser_at
                and not getattr(self, "_embed_aktif", False)):
            self._fokus_browser_at = _fokus_at
            self.root.after(150, _focus_browser_window)
        # fokus browser HANYA saat ada yang harus dikerjakan user di sana:
        # set-up first-run dan alur 'pilih level sendiri di browser'.
        # (peluncuran browser sendiri kini di belakang - engine.browser)
        if bot_thread_hidup and getattr(bot, "WAITING_SETUP", False) \
                and not self._fokus_setup and not getattr(self, "_embed_aktif", False):
            self._fokus_setup = True
            self.root.after(150, _focus_browser_window)
        elif not bot_thread_hidup:
            self._fokus_setup = False
        if self._tunggu_pilih_halaman and not self._fokus_pilih \
                and not getattr(self, "_embed_aktif", False):
            # mode embedded: 'angkat jendela browser' = app sendiri -
            # SwitchToThisWindow justru melempar fokus ke jendela browser
            # MILIK user yang judulnya kebetulan edclub (app 'minimizing
            # itself' - keluhan user). Halaman pilihan SUDAH terlihat.
            self._fokus_pilih = True
            self.root.after(150, _focus_browser_window)
        elif not self._tunggu_pilih_halaman:
            self._fokus_pilih = False
        nama_level = ""
        if bot:
            url = getattr(bot, "STATUS_URL", "")
            # Indikator level: label asli dari teks halaman ("Lesson 87:").
            # Rumus URL lama (URL-115) salah untuk banyak akun - hanya
            # dipakai sebagai cadangan kalau label belum terbaca.
            # Hanya boleh mengaku "Level X" kalau URL memang lesson:
            # label/URL bisa jeda lama (engine sedang mengetik) - dulu
            # user pindah ke daftar level tapi kartu tetap "Level ...".
            label = getattr(bot, "STATUS_LABEL", "")
            if ".play" in url:
                if label.startswith("L"):
                    nama_level = f"Level {label[1:]}"
                else:
                    # cadangan: peta terbalik id URL -> level (instan, pasti)
                    lvl = None
                    try:
                        lvl = bot.url_to_level(url)
                    except Exception:
                        pass
                    if lvl:
                        nama_level = f"Level {lvl}"
                    else:
                        m = re.search(r"/program-\d+/(\d+)\.play", url)
                        nama_level = f"Level ? (URL {m.group(1)})" if m else ""
            elif ".game" in url:
                nama_level = "Daftar pelajaran"
            self._aktiv_nama = nama_level

            # popup 'login dulu': muncul saat sesi edclub mati, tertutup
            # sendiri saat sesi kembali aktif. tidak muncul lagi selama
            # user masih berada di halaman login (dia sedang mengerjakannya;
            # dulu popup muncul lagi di tengah user mengetik sandi).
            url_now = (getattr(bot, "STATUS_URL", "") or "").lower()
            di_halaman_login = any(k in url_now
                                   for k in ("signin", "login", "signup"))
            # v3.3: alur OAuth (pilih akun Google / callback token) = login
            # BERLANGSUNG. url-nya tak mengandung 'signin' -> dulu popup ask
            # mengira user 'bukan di halaman login' dan melempar app balik
            # ke /signin di tengah pilih akun (loop tanpa ujung).
            oauth_now = any(h in url_now for h in (
                "accounts.google.com", "accounts.youtube.com",
                "auth_callback"))
            if getattr(bot, "NEEDS_LOGIN", False):
                if getattr(self, "_embed_aktif", False):
                    # v3.2: browser DI DALAM app - popup 'login dulu' sudah
                    # tidak relevan. Akun ada = sesi lanjut sendiri; tidak
                    # ada = halaman di atas otomatis diarahkan ke login.
                    # Tanpa fokus-minimize dance apa pun. RE-ASK dilarang
                    # selagi halaman SUDAH di login/signup - dulu goto
                    # ulang mereset form di tengah user daftar akun baru.
                    if (time.time() > self._login_grace
                            and not di_halaman_login and not oauth_now):
                        bot.ASK_LOGIN_URL = getattr(bot,
                                                    "LOGIN_URL_INDIVIDUAL", "")
                        bot.ASK_LOGIN_NAV = True
                        self._login_grace = time.time() + 300
                        self._log("[LOGIN] Menuju halaman login di app...")
                elif (self._login_win is None and not self._login_dismiss
                        and not self._rentang_terbuka
                        and time.time() > self._login_grace
                        and (not self._login_ever or not di_halaman_login)):
                    self._login_ever = True
                    self._login_popup()
            elif self._login_win is not None:
                self._login_win.destroy()
                self._login_win = None
                self._login_grace = 0
                self._login_ever = False
                self._log("Login edclub aktif - bot lanjut bekerja.")
                # login selesai = tidak ada lagi yang perlu di browser:
                # kecilkan lagi ke belakang (bot mengetik via CDP), app
                # tidak perlu merebut fokus - statusnya yang bercerita
                if not getattr(self, "_embed_aktif", False):
                    self.root.after(600, _minimize_browser_windows)
            elif self._login_dismiss:
                self._login_dismiss = False
            else:
                self._login_ever = False

            # >2 menit tanpa lesson karena user memakai browser bot
            # (saat menunggu pilihan level di halaman, popup ini mubazir -
            # kartu aktivitas sudah menjelaskan apa yang harus dilakukan)
            if getattr(bot, "ASK_NEXT_LEVEL", False) and self._tanya_win is None \
                    and not self._tunggu_pilih_halaman:
                bot.ASK_NEXT_LEVEL = False
                self._ask_dialog()

            # user memilih level awal sendiri: tunggu dia membuka pelajaran
            # di jendela browser (bot diam sampai itu terjadi)
            if self._tunggu_pilih_halaman:
                if not bot_thread_hidup:
                    self._tunggu_pilih_halaman = False
                    bot.AWAIT_RANGE = False
                else:
                    url_p = getattr(bot, "STATUS_URL", "") or ""
                    lbl_p = getattr(bot, "STATUS_LABEL", "") or ""
                    lvl_p = 0
                    if lbl_p.startswith("L") and lbl_p[1:].isdigit():
                        lvl_p = int(lbl_p[1:])
                    if not lvl_p:
                        try:
                            lvl_p = bot.url_to_level(url_p) or 0
                        except Exception:
                            pass
                    if ".play" in url_p:
                        self._tunggu_pilih_halaman = False
                        bot.AWAIT_RANGE = False
                        # level pilihan terbuka = kerja pindah ke bot:
                        # browser kembali ke belakang
                        if not getattr(self, "_embed_aktif", False):
                            self.root.after(600, _minimize_browser_windows)
                        if lvl_p:
                            self._rentang_mulai = lvl_p
                            self._save_range_settings()
                            self._apply_range_to_bot(
                                bot, lvl_p, self._rentang_akhir)
                            self._log(f"[RENTANG] mulai dari level "
                                      f"pilihanmu: {lvl_p}.")
                        else:
                            # kursus tak dikenali di peta -> kerjakan dari
                            # posisi sekarang saja
                            self._apply_range_to_bot(bot, 1, 0)
                            self._log("[RENTANG] mulai dari pelajaran yang "
                                      "kamu buka.")

            # tanya rentang setelah tersambung + login dicek + tidak sedang
            # butuh login. Kalau user sudah berada dalam lesson -> pakai level
            # itu sebagai awal otomatis (tanpa popup). Kalau tidak -> dialog.
            if (self._tanya_rentang and bot_thread_hidup
                    and getattr(bot, "LOGIN_DICEK", False)
                    and not getattr(bot, "NEEDS_LOGIN", False)
                    and getattr(bot, "STATUS_URL", "")):
                self._tanya_rentang = False
                lvl = 0
                try:
                    lvl = bot.url_to_level(bot.STATUS_URL) or 0
                except Exception:
                    pass
                if lvl:
                    self._rentang_mulai = lvl
                    bot.LEVEL_START = lvl
                    bot._range_jump_done = True
                    bot.RANGE_READY = True
                    self._rentang_btn.configure(
                        text=f"🎯  {lvl} - "
                             f"{self._rentang_akhir or self._total_level}")
                    self._log(f"[RENTANG] kamu sudah di level {lvl} - "
                              "mulai dari situ, lanjut otomatis.")
                else:
                    # tahan bot diam selama popup rentang terbuka (dulu:
                    # recovery malah membuka level terdepan akun)
                    bot.AWAIT_RANGE = True
                    try:
                        r = self._open_range()
                        if r == "pindai":
                            # pemindaian progres akun berjalan di latar;
                            # picker dibuka otomatis saat selesai - bot
                            # tetap AWAIT_RANGE (jangan dilepas di finally)
                            return
                        if r == "halaman":
                            # user memilih sendiri: bot tetap diam sampai
                            # pelajaran pilihan dibuka (lihat blok tunggu di
                            # atas); AWAIT_RANGE tidak dilepas
                            self._tunggu_pilih_halaman = True
                            # bawa dia ke daftar level TAMPILAN BARU
                            # (course/3): dulu bisa tinggal di rute lama
                            # sportal/.game = UI tua penuh iklan (keluhan
                            # user: 'kenapa yang lama, yang baru lebih
                            # bagus')
                            if getattr(self, "_embed_aktif", False):
                                try:
                                    from gui.widgets import _DIALOG_LAYER
                                    if _DIALOG_LAYER is not None:
                                        _DIALOG_LAYER.ke_url(
                                            "https://www.edclub.com"
                                            "/student/course/3")
                                except Exception:
                                    pass
                        elif r == "lanjut":
                            # LANJUT = jalan dari posisi akun sekarang
                            # (level berikutnya yang terbuka) - jalur yang
                            # sama dgn rentang dilewati, tapi eksplisit
                            self._tunggu_pilih_halaman = False
                            bot.AWAIT_RANGE = False
                            bot.LEVEL_START = 1
                            bot.LEVEL_END = 0
                            bot.RANGE_DONE = False
                            bot._range_jump_done = True
                            bot.RANGE_READY = True
                            self._rentang_btn.configure(text="🎯  Lanjut")
                            self._log("Lanjut dari posisi akun sekarang.")
                        elif r:
                            # Simpan MENANG atas 'Pilih di Halaman' yang
                            # masih menggantung (dulu flag tunggu tidak
                            # dibersihkan -> bot tetap 'Menunggu kamu'
                            # padahal rentang sudah disimpan)
                            self._tunggu_pilih_halaman = False
                            bot.AWAIT_RANGE = False
                            bot.LEVEL_START = self._rentang_mulai
                            bot.LEVEL_END = self._rentang_akhir
                            bot.RANGE_DONE = False
                            bot._range_jump_done = False
                            bot.RANGE_READY = True
                            # rentang terjawab = bot yang kerja (lompat ke
                            # level awal) - browser kembali ke belakang,
                            # sama seperti alur pilih-sendiri-di-browser
                            if not getattr(self, "_embed_aktif", False):
                                self.root.after(1500,
                                                _minimize_browser_windows)
                        else:
                            # dilewati = jalan dari posisi sekarang; rentang
                            # lama tidak boleh dipakai (live: bot pernah
                            # melompat ke level 662 persis setelah login,
                            # sebelum user menjawab apapun)
                            bot.LEVEL_START = 1
                            bot.LEVEL_END = 0
                            bot.RANGE_DONE = False
                            bot._range_jump_done = True
                            bot.RANGE_READY = True
                            self._log("Rentang dilewati - bot jalan otomatis "
                                      "dari posisi sekarang.")
                    finally:
                        if not self._tunggu_pilih_halaman \
                                and not getattr(self, "_pindai_berjalan", False):
                            bot.AWAIT_RANGE = False

            # bot menanyakan level start yang terkunci
            tanya = getattr(bot, "LEVEL_ASKED", None)
            if tanya and tanya.get("aktif") and self._terkunci_win is None \
                    and not getattr(bot, "NEEDS_LOGIN", False):
                self._locked_dialog(tanya)
            # login dibutuhkan -> dialog terkunci tidak relevan, tutup
            if getattr(bot, "NEEDS_LOGIN", False) and self._terkunci_win is not None:
                try:
                    if hasattr(self._terkunci_win, "_tb_tutup"):
                        self._terkunci_win._tb_tutup()   # done() bereskan
                    elif hasattr(self._terkunci_win, "destroy"):
                        self._terkunci_win.destroy()
                except Exception:
                    pass
                self._terkunci_win = None
                tanya2 = getattr(bot, "LEVEL_ASKED", None)
                if tanya2 and tanya2.get("aktif"):
                    tanya2["jawab"] = "mulai"
                    if tanya2.get("event") is not None:
                        tanya2["event"].set()
                self._log("[RENTANG] cek level terkunci ditunda sampai login.")

            # bot mencapai level akhir rentang -> popup sekali.
            # try: error di sini pernah membunuh _poll seluruhnya
            # (reschedule after(150) tak jalan -> status beku 'Berjalan').
            if getattr(bot, "RANGE_DONE", False) and not self._selesai_info:
                self._selesai_info = True
                self._log("Rentang level selesai - bot berhenti sendiri.")
                try:
                    dialog_done(self.root, self._rentang_akhir
                                   or self._total_level)
                except Exception as ex:
                    self._log(f"[GUI] popup selesai gagal: {ex!r}")

            baru_jawab = (bot_thread_hidup and self._rentang_jawab
                          and time.time() - self._rentang_jawab < 6.0)
            # PAGE = None saat browser belum selesai di-connect. Fake bot
            # di suite uji tidak punya atribut ini -> pakai sentinel agar
            # state 'Membuka' hanya untuk bot sungguhan.
            pg_bot = getattr(bot, "PAGE", "tiada")
            if not self.lisensi_ok:
                self._set_state("⚠ Perlu aktivasi", ORANGE, "aktivasi")
            elif getattr(bot, "RANGE_DONE", False):
                self._set_state("🏁 Selesai (rentang)", GREEN, "selesai")
            elif not bot_thread_hidup:
                # tidak ada sesi bot berjalan: jangan tampilkan 'Berjalan'
                # (dulu: aplikasi baru dibuka langsung bilang Berjalan).
                if bot.STOP:
                    self._set_state("⏹ Berhenti", RED, "berhenti")
                else:
                    self._set_state("⏻ Siap", FAINT, "siap")
            elif getattr(bot, "BROWSER_CLOSED", False) \
                    and not getattr(self, "_embed_aktif", False):
                # jendela browser bot ditutup user: URL Playwright stale,
                # engine sudah menandai state.BROWSER_CLOSED. Di mode
                # embedded webview SELALU ada di dalam app - label itu
                # cuma membingungkan (keluhan user: browsernya kan
                # kelihatan hidup).
                self._set_state("✖ Browser ditutup", RED, "tutup")
            elif bot_thread_hidup and pg_bot is None:
                # browser sedang diluncurkan/di-connect (di belakang)
                if getattr(self, "_embed_aktif", False):
                    self._set_state("🚀 Menyambung ke edclub...",
                                    ACCENT, "membuka")
                else:
                    nama_br = ((getattr(bot, "BROWSER", None) or {}).get("name")
                               or "browser")
                    self._set_state(f"🚀 Membuka {nama_br}...", ACCENT,
                                    "membuka")
            elif getattr(bot, "WAITING_SETUP", False):
                self._set_state("🧭 Menunggu set-up browser", YELLOW, "membuka")
            elif self._rentang_terbuka:
                # dialog rentang terbuka = fokus user ada di situ, bukan login
                # (dulu label masih 'Menunggu login' saat popup muncul)
                self._set_state("🎯 Memilih level", ACCENT, "memilih")
            elif getattr(bot, "NEEDS_LOGIN", False):
                self._set_state("⚠ Menunggu login", YELLOW, "login")
            elif not getattr(bot, "LOGIN_DICEK", True):
                # antara browser terbuka dan status login terbaca: dulu
                # jatuh ke 'Menunggu kamu' padahal bot sedang memeriksa
                # sesi (keluhan live: 'state langsung kamu memakai bot')
                self._set_state("🔎 Memeriksa login", ACCENT, "memeriksa")
            elif self._tunggu_pilih_halaman:
                self._set_state("🎯 Memilih level", ACCENT, "memilih")
            elif bot.STOP:
                self._set_state("⏹ Berhenti", RED, "berhenti")
            elif bot.PAUSED:
                self._set_state("⏸ Jeda", YELLOW, "jeda")
            elif baru_jawab and ".play" not in url:
                # baru selesai memilih rentang: bot membuka level pilihan -
                # jangan flash 'Menunggu kamu' di sela-selang detik
                self._set_state("🎯 Menyiapkan level...", ACCENT, "menyiapkan")
            elif ".play" not in url:
                # user membuka halaman lain (daftar level dsb.) saat bot
                # jalan: bot menunggu - dulu pill tetap 'Berjalan' hijau,
                # terasa seperti bot masih sibuk mengetik padahal diam
                self._set_state("⏳ Menunggu kamu", YELLOW, "kamu")
            else:
                self._set_state("● Berjalan", GREEN, "berjalan")

            # kartu aktivitas: kalimat besar mengikuti keadaan bot
            if not self.lisensi_ok:
                self._set_activity("Perlu aktivasi",
                                    "Tunggu persetujuan pemilik, atau tekan "
                                    "Start untuk mengirim permintaan.")
            elif getattr(bot, "RANGE_DONE", False):
                self._set_activity(
                    "Selesai!",
                    f"Semua level sampai level {self._rentang_akhir or self._total_level} "
                    "sudah dikerjakan. Klik Start untuk lanjut.")
            elif bot.STOP:
                self._set_activity("Berhenti", "Klik Start untuk mulai lagi.")
            elif not bot_thread_hidup:
                self._set_activity("Siap", "Klik Start untuk mulai.")
            elif getattr(bot, "BROWSER_CLOSED", False) \
                    and not getattr(self, "_embed_aktif", False):
                self._set_activity(
                    "Browser ditutup",
                    "Jendela browser bot ditutup. Tekan Stop lalu Start "
                    "untuk membuka browser baru.")
            elif bot.PAUSED:
                self._set_activity("Jeda",
                                    "Klik Lanjut atau tekan F9 untuk melanjutkan.")
            elif getattr(bot, "WAITING_SETUP", False):
                self._set_activity(
                    "Menyiapkan browser...",
                    "Selesaikan setelan awal di jendela browser, lalu tutup "
                    "halamannya.")
            elif self._rentang_terbuka:
                self._set_activity(
                    "Memilih level",
                    "Pilih mode mulai di panel dalam app."
                    if getattr(self, "_embed_aktif", False)
                    else "Pilih rentang level di jendela yang muncul.")
            elif getattr(bot, "NEEDS_LOGIN", False):
                self._set_activity(
                    "Menunggu login",
                    "Selesaikan login edclub di dalam app."
                    if getattr(self, "_embed_aktif", False)
                    else "Selesaikan login edclub di jendela browser.")
            elif bot_thread_hidup and pg_bot is None:
                nama_br = ((getattr(bot, "BROWSER", None) or {}).get("name")
                           or "browser")
                self._set_activity(
                    f"Membuka {nama_br}...",
                    "Jendela browser dibuka di belakang - kamu tidak perlu "
                    "melakukan apa pun dulu.")
            elif bot_thread_hidup and not getattr(bot, "LOGIN_DICEK", True):
                self._set_activity("Memeriksa login...",
                                    "Memastikan sesi edclub kamu aktif.")
            elif self._tunggu_pilih_halaman:
                self._set_activity(
                    "Pilih level awal",
                    "Buka pelajaran pilihanmu di jendela browser - "
                    "bot mulai dari situ.")
            elif baru_jawab and ".play" not in url:
                self._set_activity("Menyiapkan level...",
                                    "Bot membuka pelajaran pilihanmu.")
            elif ".play" not in url:
                # pengguna membuka halaman lain (daftar level dll.) saat bot
                # jalan - bot menunggu; jangan tampilkan 'Sedang mengetik...'
                # yang basi dari lesson sebelumnya
                self._aktiv_sub_teks = ""
                self._set_activity(
                    "Kamu sedang memakai browser bot",
                    "Bot menunggu. Buka pelajaran mana pun - bot lanjut "
                    "dari sana.")
            elif nama_level:
                self._set_activity(nama_level,
                                    self._aktiv_sub_teks
                                    or "Sedang dikerjakan otomatis.")
            else:
                self._set_activity("Bot sedang bekerja",
                                    self._aktiv_sub_teks
                                    or "Buka pelajaran mana pun di jendela browser.")

            self.btn_pause.configure(
                text="⏸  Pause" if not bot.PAUSED else "▶  Lanjut")
            self._sync_btn_states()
            # slider kecepatan ikut kalau kecepatan diubah dari hotkey F10
            w = getattr(self.bot, "SPEED_WPM", 0)
            if w and w != getattr(self, "_speed_wpm", 0):
                self._apply_speed(w)
        else:
            self._set_activity("Siap", "Klik Start untuk mulai.")



    # ------------------------------------------------------ popup login edclub

    def _load_range(self):
        try:
            s = json.load(open(SETTINGS_FILE, encoding="utf-8"))
            return int(s.get("start", 1)), int(s.get("end", 0))
        except Exception:
            return 1, 0


    def on_rentang(self):
        """Buka dialog rentang (dipakai alur Start; tidak ada tombol GUI)."""
        self._open_range()


    def _open_range(self):
        """Dialog rentang level. Return: False batal, True simpan,
        'halaman' = user memilih level awal sendiri di jendela browser."""
        bot = self.bot
        jumlah = {"n": 0}
        if bot:
            try:
                jumlah["n"] = len(bot._level_map)
            except Exception:
                pass

        def on_bangun():
            if not bot:
                self._log("Klik Start dulu, lalu bangun peta.")
                return
            if not self.bot_thread or not self.bot_thread.is_alive():
                self._log("Bot belum berjalan - klik Start dulu, "
                          "lalu Bangun Peta.")
                return
            bot.ASK_BUILD_MAP = True
            self._log("Membangun peta level di latar belakang "
                      "(lihat progres [PETA] di log / jangan Stop).")

        self._rentang_terbuka = True
        # nomor untuk kartu 'Lanjut': level terakhir yang dikerjakan bot
        # (engine hidup + halaman sekarang + file posisi_level.json)
        pos = 0
        if bot:
            try:
                pos = int(getattr(bot, "POSISI_LEVEL", 0) or 0)
            except Exception:
                pos = 0
            try:
                pos = max(pos, int(bot.url_to_level(bot.STATUS_URL) or 0))
            except Exception:
                pass
        if not pos:
            try:
                from engine.levels import muat_posisi
                pos = muat_posisi()
            except Exception:
                pos = 0
        if not pos and not getattr(self, "_pindai_berjalan", False) \
                and not getattr(self, "_pindai_selesai", False):
            cache = getattr(self, "_progres_akun", None)
            if cache:
                # hasil pemindaian sebelumnya masih segar (sekali per sesi)
                pos = int(cache.get("pertama_baru") or 0)
            else:
                # instal baru: peta bot kosong & posisi bot 0, tapi edclub
                # tahu posisi akun - baca progres asli dari halaman course
                # (virtualized list, label aria-label kaya status).
                # Dulu: Lanjut/rentang default ke level 1 padahal akun di
                # level 90-an (keluhan live sim akun baru).
                self._set_activity("Memindai progres akun…",
                                   "Membaca posisi asli akun di edclub.")
                self._log("[PINDAI] pos bot 0 - baca progres akun dari "
                          "halaman course (latar belakang).")
                self._pindai_berjalan = True
                threading.Thread(target=self._pindai_progres,
                                 daemon=True).start()
                return "pindai"
        if pos:
            # default 'dari' = posisi akun (dulu selalu 1 utk instal baru)
            if not self._rentang_mulai or self._rentang_mulai <= 1:
                self._rentang_mulai = pos
            cache = getattr(self, "_progres_akun", None)
            if cache and cache.get("total"):
                self._total_level = max(self._total_level or 0,
                                        int(cache["total"]))
        try:
            hasil = dialog_range(self.root, self._rentang_mulai,
                                   self._rentang_akhir, jumlah,
                                   self._total_level, on_bangun,
                                   posisi=pos,
                                   baris=getattr(
                                       self, "_progres_akun", {}) or {})
        finally:
            self._rentang_terbuka = False
        if hasil in ("halaman", "lanjut"):
            self._rentang_jawab = time.time()
            return hasil
        if hasil is None:
            return False
        self._rentang_mulai = hasil["mulai"]
        self._rentang_akhir = hasil["akhir"]
        self._save_range_settings()
        self._log(f"Rentang level: {self._rentang_mulai} - "
                  f"{self._rentang_akhir or 'akhir kursus'}.")
        self._rentang_jawab = time.time()
        return True


    def _pindai_progres(self):
        """Thread kecil: baca progres ASLI akun via CDP webview (2-6 dtk).
        Hasil disimpan di self._progres_akun lalu picker dibuka ulang via
        antrean UI (dipanggil dari thread - jangan sentuh Tk di sini)."""
        port = 9222
        try:
            from engine import state as _est
            port = int(getattr(_est, "DEBUG_PORT", 9222) or 9222)
        except Exception:
            pass
        hasil = None
        try:
            from playwright.sync_api import sync_playwright
            from engine.levels import baca_progres_akun
            with sync_playwright() as pw:
                br = pw.chromium.connect_over_cdp(
                    f"http://localhost:{port}")
                pg = None
                for c in br.contexts:
                    for x in c.pages:
                        u = x.url or ""
                        if "edclub.com" in u and "/course/" in u:
                            pg = x
                            break
                if pg is not None:
                    hasil = baca_progres_akun(pg)
                else:
                    print("[PINDAI] tak ada halaman edclub /course/ di "
                          f"CDP :{port}")
        except Exception:
            import traceback as _tb
            print("[PINDAI] gagal:")
            _tb.print_exc()
            hasil = None
        self._progres_akun = hasil or {}
        self._ui_queue.put(self._lanjut_buka_range)

    def _lanjut_buka_range(self):
        """(UI thread) pemindaian tuntas - buka picker dgn data asli."""
        self._pindai_berjalan = False
        self._pindai_selesai = True
        bot = self.bot
        if not getattr(self, "_rentang_terbuka", False) \
                and bot is not None and getattr(bot, "AWAIT_RANGE", False):
            if self._progres_akun:
                self._log("Progres akun terbaca (level %s)."
                          % self._progres_akun.get("pertama_baru"))
            else:
                self._log("Progres akun tak terbaca - pakai default.")
            self._open_range()

    def _save_range_settings(self):
        try:
            s = json.load(open(SETTINGS_FILE, encoding="utf-8"))
        except Exception:
            s = {}
        s["start"] = self._rentang_mulai
        s["end"] = self._rentang_akhir
        try:
            json.dump(s, open(SETTINGS_FILE, "w", encoding="utf-8"))
        except Exception:
            pass


    @staticmethod
    def _apply_range_to_bot(bot, mulai, akhir):
        bot.LEVEL_START = mulai
        bot.LEVEL_END = akhir
        bot.RANGE_DONE = False
        bot._range_jump_done = True
        bot.RANGE_READY = True


    def _locked_dialog(self, tanya):
        """Popup 'level start terkunci' - jawaban dikirim balik ke bot.
        v3.1.4: _Dialog overlay (tampil DI DALAM app, menutupi area
        webview) - dulu jendela OS terpisah (keluhan user: popup jadul
        nongol di luar app). Kalau _DIALOG_LAYER kosong (mode browser
        eksternal) _Dialog otomatis jatuh ke jendela biasa."""
        if self._terkunci_win is not None:
            return
        d = _Dialog(self.root, f"Level {tanya['start']} masih terkunci",
                    "Akunmu baru terbuka sampai level "
                    f"{tanya['fallback']} - level terkunci memuat "
                    "halaman kosong.", ikon="🔒")

        def jawab(pilihan):
            if self._terkunci_win is None:
                return      # sudah dijawab / ditutup jalur lain
            self._terkunci_win = None
            tanya["jawab"] = pilihan
            if tanya.get("event") is not None:
                tanya["event"].set()
            d.done(pilihan)

        d._tb_tutup = lambda: jawab("mulai")   # penutup NEEDS_LOGIN
        tk.Label(d.body, text=f"Mulai dari level {tanya['fallback']} "
                              "(posisi terdepan akunmu) sekarang?",
                 font=("Segoe UI", 10), fg=FG, bg=PANEL,
                 wraplength=420, justify="left").pack(anchor="w")
        d.button(f"Mulai dari {tanya['fallback']}",
                 cmd=lambda: jawab("mulai"))
        d.button("Stop", primer=False, cmd=lambda: jawab("stop"))
        self._terkunci_win = d
        d.show()


    def _ask_dialog(self):
        """Popup 'bot menunggu >2 menit' - dibangun di thread UI. v3.1.4:
        _Dialog overlay DI DALAM app (dulu jendela OS terpisah - keluhan
        user). _login_popup TETAP jendela: harus bisa auto-tutup begitu
        sesi pulih, dan overlay menutupi halaman login di dalam app."""
        bot = self.bot
        d = _Dialog(self.root, "Bot menunggu",
                    "Lebih dari 2 menit tidak ada lesson terbuka.",
                    ikon="⏳")

        def done(stop=False):
            if self._tanya_win is None:
                return      # sudah dijawab
            self._tanya_win = None
            d.done("stop" if stop else "lanjut")
            if stop and bot:
                bot.STOP = True
                bot.PAUSED = False
                self._log("Bot dihentikan dari popup 'menunggu'.")

        for t in ("•  Sepertinya kamu sedang memakai jendela browser bot",
                  "•  Bot jalan lagi otomatis begitu kamu membuka lesson "
                  "atau berhenti memakai browser itu"):
            tk.Label(d.body, text=t, font=("Segoe UI", 10), fg=FG,
                     bg=PANEL, anchor="w", wraplength=420,
                     justify="left").pack(anchor="w", pady=1)
        d.button("Stop Bot", warna_btn=RED, cmd=lambda: done(True))
        d.button("Lanjut Menunggu", primer=False, cmd=lambda: done(False))
        self._tanya_win = d
        d.show()


    def _login_popup(self):
        """Jendela 'login dulu': muncul saat bot mendeteksi sesi edclub mati.
        Tertutup otomatis begitu sesi aktif kembali (dicek tiap poll)."""
        bot = self.bot
        win = tk.Toplevel(self.root)
        self._login_win = win
        win.title("Login edclub diperlukan")
        win.configure(bg=PANEL)
        win.resizable(False, False)
        try:
            win.attributes("-topmost", True)
            win.lift()
            win.focus_force()
        except Exception:
            pass

        head = tk.Frame(win, bg=PANEL)
        head.pack(fill="x", padx=24, pady=(20, 4))
        box = tk.Canvas(head, width=46, height=46, bg=PANEL, highlightthickness=0)
        box.pack(side="left")
        box.create_oval(2, 2, 44, 44, fill=YELLOW, width=0)
        box.create_text(23, 25, text="🔑", font=("Segoe UI Emoji", 16, "bold"),
                        fill="white")
        jt = tk.Frame(head, bg=PANEL)
        jt.pack(side="left", padx=(14, 0))
        tk.Label(jt, text="Login edclub dulu", font=("Segoe UI", 14, "bold"),
                 fg=FG, bg=PANEL).pack(anchor="w")
        tk.Label(jt, text="Sesi login mati atau belum login - kemajuan level "
                          "tidak tersimpan.",
                 font=("Segoe UI", 9), fg=DIM, bg=PANEL,
                 wraplength=360, justify="left").pack(anchor="w", pady=(2, 0))

        body = tk.Frame(win, bg=PANEL)
        body.pack(fill="x", padx=24, pady=12)
        langkah = (
            ("1", "Klik tombol kuning \"Buka Halaman Login\" di bawah"),
            ("2", "Login seperti biasa di jendela browser bot "
                  "(email & sandi edclub)"),
            ("3", "Selesai - jendela ini tertutup otomatis, bot lanjut"),
        )
        for nomor, teks in langkah:
            baris = tk.Frame(body, bg=PANEL)
            baris.pack(anchor="w", pady=3)
            c = tk.Canvas(baris, width=22, height=22, bg=PANEL,
                          highlightthickness=0)
            c.pack(side="left")
            c.create_oval(1, 1, 21, 21, fill=ACCENT, width=0)
            c.create_text(11, 12, text=nomor, font=("Segoe UI", 9, "bold"),
                          fill="white")
            tk.Label(baris, text=teks, font=("Segoe UI", 10), fg=FG, bg=PANEL,
                     anchor="w", wraplength=380, justify="left").pack(
                side="left", padx=(10, 0))
        tk.Label(body, text="Sekali login cukup - profil bot mengingatnya. "
                            "Jendela ini hanya muncul kalau sesi benar-benar mati.",
                 font=("Segoe UI", 8), fg=FAINT, bg=PANEL, wraplength=420,
                 justify="left").pack(anchor="w", pady=(8, 0))

        foot = tk.Frame(win, bg=PANEL)
        foot.pack(fill="x", padx=24, pady=(4, 18))

        def buka_login(url):
            if bot:
                bot.ASK_LOGIN_URL = url
                bot.ASK_LOGIN_NAV = True
                self._log(f"Membuka halaman login di jendela browser bot: {url}")
                # fokus browser kini dipegang engine: begitu halaman login
                # BENAR-BENAR selesai dimuat (bukan blank), engine mengibarkan
                # FOCUS_BROWSER_AT dan poll loop mengangkat jendelanya.
                # (dulu: fokus di 1,2 dtk -> user menatap layar blank.)
            # Popup ditutup: user sudah memilih pergi ke halaman login.
            # Kalau login tidak dilakukan, popup muncul lagi setelah 3
            # menit (selama user masih di halaman login, tidak muncul).
            self._login_grace = time.time() + 180
            self._login_win = None
            try:
                win.destroy()
            except Exception:
                pass

        b1 = tk.Label(foot, text="Buka Halaman Login", font=("Segoe UI", 10, "bold"),
                      fg=BTN_FG, bg=YELLOW, padx=18, pady=7, cursor="hand2")
        b1.pack(side="right")
        b1.bind("<Button-1>", lambda e: self._safe(
            lambda: buka_login(bot.LOGIN_URL_INDIVIDUAL if bot else "")))
        b1._tb_klik = lambda: buka_login(bot.LOGIN_URL_INDIVIDUAL if bot else "")

        def tutup():
            self._login_dismiss = True
            win.destroy()
            self._login_win = None

        b2 = tk.Label(foot, text="Tutup", font=("Segoe UI", 10, "bold"),
                      fg=FG, bg=CARD, padx=16, pady=7, cursor="hand2",
                      highlightthickness=1, highlightbackground=EDGE)
        b2.pack(side="right", padx=(0, 8))
        b2.bind("<Button-1>", lambda e: tutup())

        win.update_idletasks()
        ix, iy = self.root.winfo_rootx(), self.root.winfo_rooty()
        iw, ih = self.root.winfo_width(), self.root.winfo_height()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        win.geometry(f"+{max(ix + (iw - w) // 2, 40)}+{max(iy + (ih - h) // 2, 40)}")
