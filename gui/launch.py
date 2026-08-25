"""Jendela utama - bagian launch."""

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

from .dialogs import (dialog_aktivasi, dialog_buka_browser, dialog_pilih_browser, dialog_pilih_profil, dialog_tips, dialog_tutup_paksa)
from .icons import _ikon_widget
from .theme import (ACCENT, BROWSER_WARNA, CARD, CARD_HOVER, DIM, EDGE, FG, LOG_FILE, SETTINGS_FILE)


class LaunchMixin:
    """Mixin: dipadukan di gui/app.py."""


    # ------------------------------------------------------------------ bot

    def _load_bot(self):
        try:
            self.log_file = open(LOG_FILE, "w", encoding="utf-8", buffering=1)
        except Exception:
            self.log_file = None
        sys.stdout = self._Writer(self)
        sys.stderr = self._Writer(self)
        try:
            import autopilot_pw as bot
            self.bot = bot
            bot.set_confirmer(self._confirm_kill)
            self._ui_queue.put(self._deteksi_browser)
            self._log("Modul bot dimuat. Klik Start untuk mulai.")
        except Exception as ex:
            self._log(f"GAGAL memuat bot: {ex}")


    def _confirm_kill(self, nama, pid, exe=""):
        """Dialog 'port 9222 dipakai aplikasi lain, tutup paksa?'.
        Tkinter hanya boleh dari thread utama -> jadwalkan via root.after."""
        hasil = {"ok": False}
        selesai = threading.Event()

        def tanya():
            try:
                hasil["ok"] = dialog_tutup_paksa(self.root, nama, pid, exe)
            except Exception:
                hasil["ok"] = False
            finally:
                selesai.set()

        try:
            self.root.after(0, tanya)
        except Exception:
            return False
        selesai.wait(timeout=180)
        return hasil["ok"]


    def on_tips(self):
        det = ", ".join(n for n, _ in self._detected) or "tidak terdeteksi"
        dialog_tips(self.root, det)


    # ------------------------------------------------------ lisensi & browser

    def _minta_lisensi(self):
        if self.lisensi_ok:
            return
        if dialog_aktivasi(self.root):
            self.lisensi_ok = True
            self._judul()
            self._log("Lisensi AKTIF. Terima kasih!")
            self._set_state("⏻ Siap", FG)


    def _deteksi_browser(self):
        """Isi ulang dropdown browser. Dipanggil di thread utama setelah
        modul bot termuat (daftar kandidat browser ada di modul itu)."""
        det = []
        try:
            for cand in self.bot.BROWSER_CANDIDATES:
                for p in cand["paths"]:
                    if os.path.isfile(p):
                        det.append((cand["name"], p))
                        break
        except Exception as ex:
            self._log(f"[GUI] deteksi browser gagal: {ex}")
        self._detected = det
        pilihan = ["Otomatis"] + [n for n, _ in det]
        # browser dropdown sudah dihapus dari jendela utama; stub menelan
        # set_values dari kode lama
        self.browser_dd.set_values(pilihan)
        try:
            simpan = json.load(open(SETTINGS_FILE, encoding="utf-8"))
            if simpan.get("browser") in pilihan:
                self.browser_var.set(simpan["browser"])
            if simpan.get("last_browser") and os.path.isfile(simpan["last_browser"]):
                self._last_browser_path = simpan["last_browser"]
            if "hotkey" in simpan:
                self._hotkey = bool(simpan["hotkey"])
                if self.bot:
                    self.bot.HOTKEY_AKTIF = self._hotkey
                self.root.after(0, self._perbarui_hotkey_lbl)
            if simpan.get("profile") in ("bot", "saya"):
                self._profile = simpan["profile"]
            self._profile_dir = simpan.get("profile_dir", "") or ""
            self._profile_label = simpan.get("profile_label", "") or ""
        except Exception:
            pass
        try:
            self.root.after(0, self._perbarui_chip_browser)
        except Exception:
            pass
        self._first_run = not os.path.exists(SETTINGS_FILE)
        self._log("Browser terdeteksi: "
                  + (", ".join(n for n, _ in det) or "tidak ada"))


    def _perbarui_chip_browser(self):
        """Gambar ulang kartu browser persegi (kanan atas): logo besar +
        nama pilihan (Otomatis menampilkan browser aktual yang dipakai).
        Semua widget anak ikut di-bind klik (label/canvas menelan klik
        kalau hanya frame yang di-bind - dulu chip tak bisa diklik)."""
        try:
            for w in self.chip.winfo_children():
                w.destroy()
        except Exception:
            return
        pilih = self.browser_var.get()
        det = dict(self._detected)
        path, label, sub = "", pilih, "klik untuk ganti"
        if pilih == "Otomatis":
            aktif = ""
            try:
                if self.bot_thread and self.bot and self.bot.BROWSER:
                    aktif = self.bot.BROWSER.get("name", "")
            except Exception:
                aktif = ""
            if aktif:
                label, sub = aktif, "Otomatis • aktif"
                path = det.get(aktif, "")
            elif self._last_browser_path:
                for n, p in self._detected:
                    if p == self._last_browser_path:
                        label, sub = n, "Otomatis • terakhir"
                        path = p
                        break
            else:
                label, sub = "Otomatis", "belum ada riwayat"
        else:
            path = det.get(pilih, "")
        # keterangan profil: singkat supaya muat di kartu
        if self._profile == "saya":
            sub = (f"profilmu: {self._profile_label}"
                   if self._profile_label else "pakai profilmu")
        isi = tk.Frame(self.chip, bg=CARD)
        isi.pack(expand=True, fill="both")
        # ukuran ikon & wrap disesuaikan kartu 132x96 (teks tidak boleh
        # terpotong -; label pendek + wraplength)
        ikon = _ikon_widget(isi, path, pilih, BROWSER_WARNA.get(pilih, "#7c5cff"),
                            42, char="⚡" if pilih == "Otomatis" else None)
        ikon.pack(pady=(5, 0))
        tk.Label(isi, text=label, font=("Segoe UI", 10, "bold"),
                 fg=FG, bg=CARD, wraplength=118).pack()
        tk.Label(isi, text=sub, font=("Segoe UI", 8), fg=DIM,
                 bg=CARD, wraplength=118).pack(pady=(0, 3))
        # ukuran kartu dari isi -> persegi (auto, tahan DPI). Ukuran fix px
        # + font 125-150% = teks terpotong .
        try:
            isi.update_idletasks()
            wj = max(isi.winfo_reqwidth(), ikon.winfo_reqwidth()) + 18
            hj = isi.winfo_reqheight() + 14
            sisi = max(wj, hj, 96)
            self.chip.configure(width=sisi, height=sisi)
        except Exception:
            pass
        # bind klik + hover ke frame dan semua anak (anak menelan event kalau
        # tidak di-bind sendiri; canvas ikon termasuk)
        semua = [self.chip, isi, ikon] + self.chip.winfo_children() \
            + isi.winfo_children()

        def klik(_e=None):
            self._safe(self._ganti_browser)

        def hover(_e):
            for w2 in semua:
                try:
                    w2.configure(bg=CARD_HOVER)
                except Exception:
                    pass
            self.chip.configure(highlightbackground=ACCENT)

        def leave(_e):
            for w2 in semua:
                try:
                    w2.configure(bg=CARD)
                except Exception:
                    pass
            self.chip.configure(highlightbackground=EDGE)

        for w2 in semua:
            try:
                w2.bind("<Button-1>", klik)
                w2.bind("<Enter>", hover)
                w2.bind("<Leave>", leave)
            except Exception:
                pass


    def _nama_browser_profil(self):
        """Nama browser yang profilenya ditampilkan/dipakai mode 'saya'.
        Otomatis -> ikuti preferensi engine (browser terakhir/deteksi)."""
        pilih = self.browser_var.get()
        if pilih != "Otomatis":
            return pilih
        if self._last_browser_path:
            for n, p in self._detected:
                if p == self._last_browser_path:
                    return n
        if self.bot:
            try:
                return (self.bot._find_browser() or {}).get("name", "Brave")
            except Exception:
                pass
        return "Brave"


    def _pilih_profil_untuk(self, nama_browser):
        """Buka dialog pilih profil milik browser. Return dict profil atau
        None (batal/tidak terbaca -> pemanggil memakai profil khusus)."""
        daftar = []
        if self.bot:
            try:
                daftar = self.bot._profil_daftar(nama_browser)
            except Exception as ex:
                self._log(f"[GUI] baca profil gagal: {ex}")
        return dialog_pilih_profil(self.root, nama_browser, daftar,
                                   self._profile_dir)


    def _ganti_browser(self):
        """Klik chip browser: buka popup kartu logo untuk mengganti."""
        hasil = dialog_pilih_browser(self.root, self._detected,
                                     self.browser_var.get(), self._profile)
        if not (isinstance(hasil, tuple) and len(hasil) == 2):
            return
        nama, profil = hasil
        self.browser_var.set(nama)
        self._profile = profil
        if profil == "saya":
            p = self._pilih_profil_untuk(self._nama_browser_profil())
            if p:
                self._profile_dir = p["dir"]
                self._profile_label = p["nama"]
                self._log(f"Profil dipilih: {p['nama']} "
                          f"({p.get('email') or 'tanpa email'}).")
            else:
                self._profile = "bot"
                self._profile_dir = self._profile_label = ""
        else:
            self._profile_dir = self._profile_label = ""
        self._simpan_pengaturan()
        self._first_run = False
        self._perbarui_chip_browser()
        if self.bot_thread:
            self._log(f"Browser diganti ke {nama} - berlaku saat Start "
                      "berikutnya.")


    def on_start(self):
        bot = self.bot
        if not bot:
            return
        if self.bot_thread:
            if self.bot_thread.is_alive():
                self._log("Bot masih menyiapkan sesi sebelumnya. "
                          "Klik Stop, tunggu beberapa detik, lalu Start lagi.")
            return
        if not self.lisensi_ok:
            self._minta_lisensi()
            if not self.lisensi_ok:
                return
        # Rentang level ditanyakan setelah tersambung & login diketahui
        # (bukan sebelum Start) - lihat _poll.
        self._tanya_rentang = True
        # Popup pilih browser hanya pertama kali (belum ada pengaturan).
        # Setelah itu pilihan tersimpan; ganti lewat chip di tengah atas.
        if self._first_run:
            hasil = dialog_pilih_browser(self.root, self._detected,
                                         self.browser_var.get(), self._profile)
            if not (isinstance(hasil, tuple) and len(hasil) == 2):
                return
            self.browser_var.set(hasil[0])
            self._profile = hasil[1]
            if self._profile == "saya":
                p = self._pilih_profil_untuk(self._nama_browser_profil())
                if p:
                    self._profile_dir = p["dir"]
                    self._profile_label = p["nama"]
                else:
                    self._profile = "bot"
                    self._profile_dir = self._profile_label = ""
            self._first_run = False
        pilih = self.browser_var.get()
        # mode profil: berlaku ke engine sebelum koneksi dibuat
        if hasattr(bot, "PROFILE_MODE"):
            bot.PROFILE_MODE = self._profile
            bot.PROFILE_DIR = self._profile_dir
            bot.PROFILE_LABEL = self._profile_label
        deteksi = bot._find_browser() or {}
        # Otomatis: beri tahu engine browser terakhir yang dipakai
        bot.LAST_BROWSER = self._last_browser_path if pilih == "Otomatis" else ""
        bot.FORCE_BROWSER = next((p for n, p in self._detected if n == pilih), "")
        self._simpan_pengaturan()
        self._perbarui_chip_browser()
        # Konfirmasi 'buka browser?' tepat saat bot akan meluncurkan jendela
        # browser: port mati (bot membuka baru), atau port dipegang browser/
        # aplikasi lain (ditutup dulu, lalu bot membuka pilihan user - dulu
        # kasus ini tidak dikonfirmasi,). Kalau port sudah
        # dipegang browser pilihan sendiri (atau Otomatis menempel browser
        # yang sudah jalan), jendela dipakai ulang -> popup tidak perlu.
        proc = deteksi.get("proc", "").lower()
        port_hidup = bool(bot._cek_debug_port())
        pemegang = bot._siapa_pegang_port() if port_hidup else []
        nama_pemegang = " ".join(n.lower() for _, n in pemegang)
        akan_buka = (not port_hidup) or (not pemegang) \
            or (proc != "" and proc not in nama_pemegang \
                and pilih != "Otomatis")
        if akan_buka:
            det = {n: p for n, p in self._detected}
            nm = pilih if pilih in det else deteksi.get("name", "browser")
            if not dialog_buka_browser(self.root, nm, det.get(nm),
                                       self._profile, self._profile_label):
                return
        bot.STOP = False
        bot.PAUSED = False
        bot.RENTANG_SELESAI = False
        self._selesai_info = False
        self._aktiv_sub_teks = ""
        bot.LEVEL_START = self._rentang_mulai
        bot.LEVEL_END = self._rentang_akhir
        if self._rentang_mulai > 1 or self._rentang_akhir:
            self._log(f"Rentang level aktif: {self._rentang_mulai} - "
                      f"{self._rentang_akhir or 'akhir kursus'}.")
        self.bot_thread = threading.Thread(target=self._run_bot, daemon=True)
        self.bot_thread.start()


    def _run_bot(self):
        try:
            self.bot.connect()
            # Otomatis: ingat browser yang BENAR2 dipakai (menempel ke yang
            # sudah jalan / preferensi terakhir) untuk sesi berikutnya.
            try:
                if self.browser_var.get() == "Otomatis" and self.bot.BROWSER:
                    exe = self.bot.BROWSER.get("exe", "")
                    if exe and exe != self._last_browser_path:
                        self._last_browser_path = exe
                        self._simpan_pengaturan()
                    self.root.after(0, self._perbarui_chip_browser)
            except Exception:
                pass
            self.bot.main_loop()
        except SystemExit:
            if self.bot and self.bot.STOP:
                self._log("Bot dihentikan.")
            else:
                self._log("Gagal menyambung ke browser.")
                self._log("Tutup semua jendela browser, lalu klik Start lagi.")
        except BaseException as ex:
            self._log(f"[GUI] bot berhenti: {ex}")
        finally:
            # Putuskan Playwright supaya Start berikutnya koneksi bersih
            # dari thread baru (objek Playwright tidak boleh lintas thread).
            try:
                self.bot.disconnect()
                self._log("Bot berhenti. Klik Start untuk mulai lagi.")
            except Exception:
                pass
        self.bot_thread = None


    def on_pause(self):
        if self.bot:
            self.bot.PAUSED = not self.bot.PAUSED


    def on_stop(self):
        if self.bot:
            self.bot.STOP = True
            self.bot.PAUSED = False
            self._tunggu_pilih_halaman = False
            self.bot.TUNGGU_RENTANG = False
            self._log("Bot sedang berhenti... kalau masih menyambung, "
              "tunggu beberapa detik.")


    def on_speed(self, _=None):
        if not self.bot:
            return
        idx = {"Normal (140)": 0, "Cepat (200)": 1, "Santai (85)": 2}.get(self.speed_var.get(), 0)
        self.bot.SPEED_IDX = idx
