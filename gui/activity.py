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
import uuid
import zlib
from ctypes import wintypes
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from .dialogs import (_fokus_jendela_browser, dialog_rentang, dialog_selesai)
from .theme import (ACCENT, BTN_FG, CARD, DIM, EDGE, FAINT, FG, GREEN, ORANGE, PANEL, RED, SETTINGS_FILE, YELLOW)
from .translator import _teks_ramah


class ActivityMixin:
    """Mixin: dipadukan di gui/app.py."""


    def _poll(self):
        try:
            while True:
                fn = self._ui_queue.get_nowait()
                self._safe(fn)
        except queue.Empty:
            pass
        try:
            while True:
                line = self.log_q.get_nowait()
                ramah = _teks_ramah(line)
                if ramah:
                    self._aktiv_sub_teks = ramah
        except queue.Empty:
            pass

        bot = self.bot
        bot_thread_hidup = bool(self.bot_thread and self.bot_thread.is_alive())
        nama_level = ""
        if bot:
            url = getattr(bot, "STATUS_URL", "")
            # Indikator level: label asli dari teks halaman ("Lesson 87:").
            # Rumus URL lama (URL-115) salah untuk banyak akun - hanya
            # dipakai sebagai cadangan kalau label belum terbaca.
            label = getattr(bot, "STATUS_LABEL", "")
            if label.startswith("L"):
                nama_level = f"Level {label[1:]}"
            elif ".game" in url:
                nama_level = "Daftar pelajaran"
            else:
                # cadangan: peta terbalik id URL -> level (instan, pasti)
                lvl = None
                try:
                    lvl = bot.url_ke_level(url)
                except Exception:
                    pass
                if lvl:
                    nama_level = f"Level {lvl}"
                else:
                    m = re.search(r"/program-\d+/(\d+)\.play", url)
                    nama_level = f"Level ? (URL {m.group(1)})" if m else ""
            self._aktiv_nama = nama_level

            # popup 'login dulu': muncul saat sesi edclub mati, tertutup
            # sendiri saat sesi kembali aktif. tidak muncul lagi selama
            # user masih berada di halaman login (dia sedang mengerjakannya;
            # dulu popup muncul lagi di tengah user mengetik sandi).
            url_now = (getattr(bot, "STATUS_URL", "") or "").lower()
            di_halaman_login = any(k in url_now
                                   for k in ("signin", "login", "signup"))
            if getattr(bot, "PERLU_LOGIN", False):
                if (self._login_win is None and not self._login_dismiss
                        and not di_halaman_login
                        and not self._rentang_terbuka
                        and time.time() > self._login_grace):
                    self._login_popup()
            elif self._login_win is not None:
                self._login_win.destroy()
                self._login_win = None
                self._login_grace = 0
                self._log("Login edclub aktif - bot lanjut bekerja.")
            elif self._login_dismiss:
                self._login_dismiss = False

            # >2 menit tanpa lesson karena user memakai browser bot
            # (saat menunggu pilihan level di halaman, popup ini mubazir -
            # kartu aktivitas sudah menjelaskan apa yang harus dilakukan)
            if getattr(bot, "MINTA_TANYA_LANJUT", False) and self._tanya_win is None \
                    and not self._tunggu_pilih_halaman:
                bot.MINTA_TANYA_LANJUT = False
                self._tanya_dialog()

            # user memilih level awal sendiri: tunggu dia membuka pelajaran
            # di jendela browser (bot diam sampai itu terjadi)
            if self._tunggu_pilih_halaman:
                if not bot_thread_hidup:
                    self._tunggu_pilih_halaman = False
                    bot.TUNGGU_RENTANG = False
                else:
                    url_p = getattr(bot, "STATUS_URL", "") or ""
                    lbl_p = getattr(bot, "STATUS_LABEL", "") or ""
                    lvl_p = 0
                    if lbl_p.startswith("L") and lbl_p[1:].isdigit():
                        lvl_p = int(lbl_p[1:])
                    if not lvl_p:
                        try:
                            lvl_p = bot.url_ke_level(url_p) or 0
                        except Exception:
                            pass
                    if ".play" in url_p:
                        self._tunggu_pilih_halaman = False
                        bot.TUNGGU_RENTANG = False
                        if lvl_p:
                            self._rentang_mulai = lvl_p
                            self._simpan_rentang_settings()
                            self._terapkan_rentang_ke_bot(
                                bot, lvl_p, self._rentang_akhir)
                            self._log(f"[RENTANG] mulai dari level "
                                      f"pilihanmu: {lvl_p}.")
                        else:
                            # kursus tak dikenali di peta -> kerjakan dari
                            # posisi sekarang saja
                            self._terapkan_rentang_ke_bot(bot, 1, 0)
                            self._log("[RENTANG] mulai dari pelajaran yang "
                                      "kamu buka.")

            # tanya rentang setelah tersambung + login dicek + tidak sedang
            # butuh login. Kalau user sudah berada dalam lesson -> pakai level
            # itu sebagai awal otomatis (tanpa popup). Kalau tidak -> dialog.
            if (self._tanya_rentang and bot_thread_hidup
                    and getattr(bot, "LOGIN_DICEK", False)
                    and not getattr(bot, "PERLU_LOGIN", False)
                    and getattr(bot, "STATUS_URL", "")):
                self._tanya_rentang = False
                lvl = 0
                try:
                    lvl = bot.url_ke_level(bot.STATUS_URL) or 0
                except Exception:
                    pass
                if lvl:
                    self._rentang_mulai = lvl
                    bot.LEVEL_START = lvl
                    bot._rentang_jump_done = True
                    bot.RENTANG_SIAP = True
                    self._rentang_btn.configure(
                        text=f"🎯  {lvl} - "
                             f"{self._rentang_akhir or self._total_level}")
                    self._log(f"[RENTANG] kamu sudah di level {lvl} - "
                              "mulai dari situ, lanjut otomatis.")
                else:
                    # tahan bot diam selama popup rentang terbuka (dulu:
                    # recovery malah membuka level terdepan akun)
                    bot.TUNGGU_RENTANG = True
                    try:
                        r = self._buka_rentang()
                        if r == "halaman":
                            # user memilih sendiri: bot tetap diam sampai
                            # pelajaran pilihan dibuka (lihat blok tunggu di
                            # atas); TUNGGU_RENTANG tidak dilepas
                            self._tunggu_pilih_halaman = True
                        elif r:
                            bot.LEVEL_START = self._rentang_mulai
                            bot.LEVEL_END = self._rentang_akhir
                            bot.RENTANG_SELESAI = False
                            bot._rentang_jump_done = False
                            bot.RENTANG_SIAP = True
                        else:
                            # dilewati = jalan dari posisi sekarang; rentang
                            # lama tidak boleh dipakai (live: bot pernah
                            # melompat ke level 662 persis setelah login,
                            # sebelum user menjawab apapun)
                            bot.LEVEL_START = 1
                            bot.LEVEL_END = 0
                            bot.RENTANG_SELESAI = False
                            bot._rentang_jump_done = True
                            bot.RENTANG_SIAP = True
                            self._log("Rentang dilewati - bot jalan otomatis "
                                      "dari posisi sekarang.")
                    finally:
                        if not self._tunggu_pilih_halaman:
                            bot.TUNGGU_RENTANG = False

            # bot menanyakan level start yang terkunci
            tanya = getattr(bot, "LEVEL_TANYA", None)
            if tanya and tanya.get("aktif") and self._terkunci_win is None \
                    and not getattr(bot, "PERLU_LOGIN", False):
                self._terkunci_dialog(tanya)
            # login dibutuhkan -> dialog terkunci tidak relevan, tutup
            if getattr(bot, "PERLU_LOGIN", False) and self._terkunci_win is not None:
                try:
                    self._terkunci_win._tb_tutup() if hasattr(
                        self._terkunci_win, "_tb_tutup") else None
                except Exception:
                    pass
                self._terkunci_win.destroy()
                self._terkunci_win = None
                tanya2 = getattr(bot, "LEVEL_TANYA", None)
                if tanya2 and tanya2.get("aktif"):
                    tanya2["jawab"] = "mulai"
                    if tanya2.get("event") is not None:
                        tanya2["event"].set()
                self._log("[RENTANG] cek level terkunci ditunda sampai login.")

            # bot mencapai level akhir rentang -> popup sekali.
            # try: error di sini pernah membunuh _poll seluruhnya
            # (reschedule after(150) tak jalan -> status beku 'Berjalan').
            if getattr(bot, "RENTANG_SELESAI", False) and not self._selesai_info:
                self._selesai_info = True
                self._log("Rentang level selesai - bot berhenti sendiri.")
                try:
                    dialog_selesai(self.root, self._rentang_akhir
                                   or self._total_level)
                except Exception as ex:
                    self._log(f"[GUI] popup selesai gagal: {ex!r}")

            if not self.lisensi_ok:
                self._set_state("⚠ Perlu aktivasi", ORANGE)
            elif getattr(bot, "RENTANG_SELESAI", False):
                self._set_state("🏁 Selesai (rentang)", GREEN)
            elif not bot_thread_hidup:
                # tidak ada sesi bot berjalan: jangan tampilkan 'Berjalan'
                # (dulu: aplikasi baru dibuka langsung bilang Berjalan).
                if bot.STOP:
                    self._set_state("⏹ Berhenti", RED)
                else:
                    self._set_state("⏻ Siap", FAINT)
            elif getattr(bot, "MENUNGGU_SETUP", False):
                self._set_state("🧭 Menunggu set-up browser", YELLOW)
            elif self._rentang_terbuka:
                # dialog rentang terbuka = fokus user ada di situ, bukan login
                # (dulu label masih 'Menunggu login' saat popup muncul)
                self._set_state("🎯 Memilih level", ACCENT)
            elif getattr(bot, "PERLU_LOGIN", False):
                self._set_state("⚠ Menunggu login", YELLOW)
            elif self._tunggu_pilih_halaman:
                self._set_state("🎯 Memilih level", ACCENT)
            elif bot.STOP:
                self._set_state("⏹ Berhenti", RED)
            elif bot.PAUSED:
                self._set_state("⏸ Jeda", YELLOW)
            else:
                self._set_state("● Berjalan", GREEN)

            # kartu aktivitas: kalimat besar mengikuti keadaan bot
            if not self.lisensi_ok:
                self._set_aktivitas("Perlu aktivasi",
                                    "Masukkan kunci aktivasi untuk memakai "
                                    "TypingBot.")
            elif getattr(bot, "RENTANG_SELESAI", False):
                self._set_aktivitas(
                    "Selesai!",
                    f"Semua level sampai level {self._rentang_akhir or self._total_level} "
                    "sudah dikerjakan. Klik Start untuk lanjut.")
            elif bot.PAUSED:
                self._set_aktivitas("Jeda",
                                    "Klik Lanjut atau tekan F9 untuk melanjutkan.")
            elif getattr(bot, "MENUNGGU_SETUP", False):
                self._set_aktivitas(
                    "Menyiapkan browser...",
                    "Selesaikan setelan awal di jendela browser, lalu tutup "
                    "halamannya.")
            elif self._rentang_terbuka:
                self._set_aktivitas("Memilih level",
                                    "Pilih rentang level di jendela yang muncul.")
            elif getattr(bot, "PERLU_LOGIN", False):
                self._set_aktivitas("Menunggu login",
                                    "Selesaikan login edclub di jendela browser.")
            elif self._tunggu_pilih_halaman:
                self._set_aktivitas(
                    "Pilih level awal",
                    "Buka pelajaran pilihanmu di jendela browser - "
                    "bot mulai dari situ.")
            elif bot.STOP:
                self._set_aktivitas("Berhenti", "Klik Start untuk mulai lagi.")
            elif not bot_thread_hidup:
                self._set_aktivitas("Siap", "Klik Start untuk mulai.")
            elif ".play" not in url:
                # pengguna membuka halaman lain (daftar level dll.) saat bot
                # jalan - bot menunggu; jangan tampilkan 'Sedang mengetik...'
                # yang basi dari lesson sebelumnya
                self._aktiv_sub_teks = ""
                self._set_aktivitas(
                    "Kamu sedang memakai browser bot",
                    "Bot menunggu. Buka pelajaran mana pun - bot lanjut "
                    "dari sana.")
            elif nama_level:
                self._set_aktivitas(nama_level,
                                    self._aktiv_sub_teks
                                    or "Sedang dikerjakan otomatis.")
            else:
                self._set_aktivitas("Bot sedang bekerja",
                                    self._aktiv_sub_teks
                                    or "Buka pelajaran mana pun di jendela browser.")

            self.btn_pause.configure(
                text="⏸  Pause" if not bot.PAUSED else "▶  Lanjut")
            self.btn_pause["state"] = "normal" if self.bot_thread else "disabled"
            self.btn_stop["state"] = "normal" if self.bot_thread else "disabled"
            self.btn_start["state"] = "disabled" if self.bot_thread else "normal"
        else:
            self._set_aktivitas("Siap", "Klik Start untuk mulai.")

        self.root.after(150, self._poll)


    # ------------------------------------------------------ popup login edclub

    def _muat_rentang(self):
        try:
            s = json.load(open(SETTINGS_FILE, encoding="utf-8"))
            return int(s.get("start", 1)), int(s.get("end", 0))
        except Exception:
            return 1, 0


    def on_rentang(self):
        """Buka dialog rentang (dipakai alur Start; tidak ada tombol GUI)."""
        self._buka_rentang()


    def _buka_rentang(self):
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
            bot.MINTA_BANGUN_PETA = True
            self._log("Membangun peta level di latar belakang "
                      "(lihat progres [PETA] di log / jangan Stop).")

        self._rentang_terbuka = True
        try:
            hasil = dialog_rentang(self.root, self._rentang_mulai,
                                   self._rentang_akhir, jumlah,
                                   self._total_level, on_bangun)
        finally:
            self._rentang_terbuka = False
        if hasil == "halaman":
            return "halaman"
        if hasil is None:
            return False
        self._rentang_mulai = hasil["mulai"]
        self._rentang_akhir = hasil["akhir"]
        self._simpan_rentang_settings()
        self._log(f"Rentang level: {self._rentang_mulai} - "
                  f"{self._rentang_akhir or 'akhir kursus'}.")
        return True


    def _simpan_rentang_settings(self):
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
    def _terapkan_rentang_ke_bot(bot, mulai, akhir):
        bot.LEVEL_START = mulai
        bot.LEVEL_END = akhir
        bot.RENTANG_SELESAI = False
        bot._rentang_jump_done = True
        bot.RENTANG_SIAP = True


    def _terkunci_dialog(self, tanya):
        """Popup 'level start terkunci' - jawaban dikirim balik ke bot."""
        if self._terkunci_win is not None:
            return
        bot = self.bot
        win = tk.Toplevel(self.root)
        self._terkunci_win = win
        win.title("Level terkunci")
        win.configure(bg=PANEL)
        win.resizable(False, False)
        try:
            win.attributes("-topmost", True)
        except Exception:
            pass

        def jawab(pilihan):
            tanya["jawab"] = pilihan
            if tanya.get("event") is not None:
                tanya["event"].set()
            self._terkunci_win = None
            try:
                win.destroy()
            except Exception:
                pass

        head = tk.Frame(win, bg=PANEL)
        head.pack(fill="x", padx=24, pady=(20, 4))
        box = tk.Canvas(head, width=46, height=46, bg=PANEL, highlightthickness=0)
        box.pack(side="left")
        box.create_oval(2, 2, 44, 44, fill=ORANGE, width=0)
        box.create_text(23, 25, text="🔒", font=("Segoe UI Emoji", 15, "bold"),
                        fill="white")
        jt = tk.Frame(head, bg=PANEL)
        jt.pack(side="left", padx=(14, 0))
        tk.Label(jt, text=f"Level {tanya['start']} masih terkunci",
                 font=("Segoe UI", 14, "bold"), fg=FG, bg=PANEL).pack(anchor="w")
        tk.Label(jt, text="Akunmu baru terbuka sampai level "
                          f"{tanya['fallback']} - level terkunci memuat "
                          "halaman kosong.",
                 font=("Segoe UI", 9), fg=DIM, bg=PANEL, wraplength=360,
                 justify="left").pack(anchor="w", pady=(2, 0))
        body = tk.Frame(win, bg=PANEL)
        body.pack(fill="x", padx=24, pady=12)
        tk.Label(body, text=f"Mulai dari level {tanya['fallback']} "
                            "(posisi terdepan akunmu) sekarang?",
                 font=("Segoe UI", 10), fg=FG, bg=PANEL,
                 wraplength=420, justify="left").pack(anchor="w")
        foot = tk.Frame(win, bg=PANEL)
        foot.pack(fill="x", padx=24, pady=(4, 18))
        b1 = tk.Label(foot, text=f"Mulai dari {tanya['fallback']}",
                      font=("Segoe UI", 10, "bold"), fg=BTN_FG, bg=ACCENT,
                      padx=18, pady=7, cursor="hand2")
        b1.pack(side="right")
        b1.bind("<Button-1>", lambda e: jawab("mulai"))
        b1._tb_klik = lambda: jawab("mulai")
        b2 = tk.Label(foot, text="Stop", font=("Segoe UI", 10, "bold"),
                      fg=FG, bg=CARD, padx=16, pady=7, cursor="hand2",
                      highlightthickness=1, highlightbackground=EDGE)
        b2.pack(side="right", padx=(0, 8))
        b2.bind("<Button-1>", lambda e: jawab("stop"))
        b2._tb_klik = lambda: jawab("stop")
        win.protocol("WM_DELETE_WINDOW", lambda: jawab("mulai"))
        win.update_idletasks()
        ix, iy = self.root.winfo_rootx(), self.root.winfo_rooty()
        iw, ih = self.root.winfo_width(), self.root.winfo_height()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        win.geometry(f"+{max(ix + (iw - w) // 2, 40)}+{max(iy + (ih - h) // 2, 40)}")


    def _tanya_dialog(self):
        """Popup 'bot menunggu >2 menit' - dibangun di thread UI (Tkinter
        tidak boleh dari thread lain), pola sama dengan _login_popup."""
        bot = self.bot
        win = tk.Toplevel(self.root)
        self._tanya_win = win
        win.title("Bot menunggu")
        win.configure(bg=PANEL)
        win.resizable(False, False)
        try:
            win.attributes("-topmost", True)
        except Exception:
            pass

        def selesai(stop=False):
            self._tanya_win = None
            try:
                win.destroy()
            except Exception:
                pass
            if stop and bot:
                bot.STOP = True
                bot.PAUSED = False
                self._log("Bot dihentikan dari popup 'menunggu'.")

        head = tk.Frame(win, bg=PANEL)
        head.pack(fill="x", padx=24, pady=(20, 4))
        box = tk.Canvas(head, width=46, height=46, bg=PANEL, highlightthickness=0)
        box.pack(side="left")
        box.create_oval(2, 2, 44, 44, fill=YELLOW, width=0)
        box.create_text(23, 25, text="⏳", font=("Segoe UI Emoji", 16, "bold"),
                        fill="white")
        jt = tk.Frame(head, bg=PANEL)
        jt.pack(side="left", padx=(14, 0))
        tk.Label(jt, text="Bot menunggu", font=("Segoe UI", 14, "bold"),
                 fg=FG, bg=PANEL).pack(anchor="w")
        tk.Label(jt, text="Lebih dari 2 menit tidak ada lesson terbuka.",
                 font=("Segoe UI", 9), fg=DIM, bg=PANEL,
                 wraplength=360, justify="left").pack(anchor="w", pady=(2, 0))

        body = tk.Frame(win, bg=PANEL)
        body.pack(fill="x", padx=24, pady=12)
        for t in ("•  Sepertinya kamu sedang memakai jendela browser bot",
                  "•  Bot jalan lagi otomatis begitu kamu membuka lesson "
                  "atau berhenti memakai browser itu"):
            tk.Label(body, text=t, font=("Segoe UI", 10), fg=FG, bg=PANEL,
                     anchor="w", wraplength=420,
                     justify="left").pack(anchor="w", pady=1)

        foot = tk.Frame(win, bg=PANEL)
        foot.pack(fill="x", padx=24, pady=(4, 18))
        b1 = tk.Label(foot, text="Stop Bot", font=("Segoe UI", 10, "bold"),
                      fg=BTN_FG, bg=RED, padx=18, pady=7, cursor="hand2")
        b1.pack(side="right")
        b1.bind("<Button-1>", lambda e: selesai(stop=True))
        b2 = tk.Label(foot, text="Lanjut Menunggu", font=("Segoe UI", 10, "bold"),
                      fg=FG, bg=CARD, padx=16, pady=7, cursor="hand2",
                      highlightthickness=1, highlightbackground=EDGE)
        b2.pack(side="right", padx=(0, 8))
        b2.bind("<Button-1>", lambda e: selesai(stop=False))

        win.protocol("WM_DELETE_WINDOW", lambda: selesai(stop=False))
        win.update_idletasks()
        ix, iy = self.root.winfo_rootx(), self.root.winfo_rooty()
        iw, ih = self.root.winfo_width(), self.root.winfo_height()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        win.geometry(f"+{max(ix + (iw - w) // 2, 40)}+{max(iy + (ih - h) // 2, 40)}")


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
                  "(akun sekolah / Google / Microsoft)"),
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
        tk.Label(body, text="Klik kuning = login Individual Edition (email & "
                            "sandi); \"Akun Sekolah\" = portal sekolah "
                            "(login Google/Clever).",
                 font=("Segoe UI", 8), fg=FAINT, bg=PANEL, wraplength=420,
                 justify="left").pack(anchor="w", pady=(8, 0))
        tk.Label(body, text="Sekali login cukup - profil bot mengingatnya. "
                            "Jendela ini hanya muncul kalau sesi benar-benar mati.",
                 font=("Segoe UI", 8), fg=FAINT, bg=PANEL, wraplength=420,
                 justify="left").pack(anchor="w", pady=(8, 0))

        foot = tk.Frame(win, bg=PANEL)
        foot.pack(fill="x", padx=24, pady=(4, 18))

        def buka_login(url):
            if bot:
                bot.MINTA_LOGIN_URL = url
                bot.MINTA_LOGIN_NAV = True
                self._log(f"Membuka halaman login di jendela browser bot: {url}")
                # angkat jendela browser ke depan setelah navigasi bot
                # dimulai (delay pendek); GUI baru menerima klik = punya
                # izin foreground di Windows.
                self.root.after(1200, _fokus_jendela_browser)
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
            lambda: buka_login(bot.LOGIN_URL_INDIVIDU if bot else "")))
        b1._tb_klik = lambda: buka_login(bot.LOGIN_URL_INDIVIDU if bot else "")

        b15 = tk.Label(foot, text="Akun Sekolah", font=("Segoe UI", 9, "bold"),
                       fg=FG, bg=CARD, padx=12, pady=7, cursor="hand2",
                       highlightthickness=1, highlightbackground=EDGE)
        b15.pack(side="right", padx=(0, 8))
        b15.bind("<Button-1>", lambda e: self._safe(
            lambda: buka_login(bot.LOGIN_URL_SEKOLAH if bot else "")))
        b15._tb_klik = lambda: buka_login(bot.LOGIN_URL_SEKOLAH if bot else "")

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
