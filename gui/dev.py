"""Jendela utama - bagian dev."""

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

from .dialogs import dialog_buka_browser, dialog_pilih_browser
from .licensing import _kode_mesin
from .theme import (APP_VERSION, BG, CARD, EDGE, FG, LOG_FILE, PANEL, PEMBUAT, SETTINGS_FILE, _build_stamp)


class DevMixin:
    """Mixin: dipadukan di gui/app.py."""


    # ------------------------------------------------------------- dev window

    # ------------------------------------------------------ dev (tersembunyi)

    def _dev_gesture(self, _e=None):
        """Klik teks versi 5x dalam 3 detik -> buka jendela Dev."""
        now = time.time()
        self._dev_klik = [t for t in self._dev_klik if now - t < 3]
        self._dev_klik.append(now)
        if len(self._dev_klik) >= 5:
            self._dev_klik = []
            self.on_dev()


    def on_dev(self):
        """Jendela developer: identitas build, diagnosis, uji dialog."""
        win = tk.Toplevel(self.root)
        win.title(f"TypingBot {APP_VERSION} - Developer")
        win.geometry("700x560")
        win.configure(bg=PANEL)
        try:
            win.attributes("-topmost", True)
        except Exception:
            pass
        info = self._dev_info()
        txt = ScrolledText(win, bg=BG, fg="#c7cbd4", relief="flat",
                           font=("Consolas", 9), state="normal", wrap="word",
                           borderwidth=0, highlightthickness=0)
        txt.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        txt.insert("1.0", info)
        txt.configure(state="disabled")

        baris1 = tk.Frame(win, bg=PANEL)
        baris1.pack(fill="x", padx=8, pady=(2, 2))
        baris2 = tk.Frame(win, bg=PANEL)
        baris2.pack(fill="x", padx=8, pady=(2, 8))

        def tombol(induk, nama, cmd):
            b = tk.Label(induk, text=nama, font=("Segoe UI", 9, "bold"),
                         fg=FG, bg=CARD, padx=10, pady=4, cursor="hand2",
                         highlightthickness=1, highlightbackground=EDGE)
            b.pack(side="left", padx=(0, 6))
            b.bind("<Button-1>", lambda e: self._safe(cmd))

        tombol(baris1, "Salin info", lambda: self._dev_salin(info))
        tombol(baris1, "Uji: pilih browser", self._dev_uji_pilih)
        tombol(baris1, "Uji: buka browser", self._dev_uji_buka)
        tombol(baris2, "Kelola lisensi", self._minta_lisensi)
        tombol(baris2, "Reset pengaturan", self._dev_reset)
        tombol(baris2, "Buka bot.log", lambda: self._dev_buka(LOG_FILE))
        tombol(baris2, "Buka folder", lambda: self._dev_buka(BASE_DIR))


    def _dev_info(self):
        try:
            isi = open(SETTINGS_FILE, encoding="utf-8").read().strip()
        except Exception:
            isi = None
        baris = [
            f"Versi         : TypingBot {APP_VERSION}",
            f"Build         : {_build_stamp()}  (waktu file program dibuat)",
            f"Pembuat       : {PEMBUAT}  (github.com/{PEMBUAT})",
            f"Mode          : "
            + ("EXE (PyInstaller)" if getattr(sys, "frozen", False)
               else "skrip Python"),
            f"Lokasi program: {PROGRAM_PATH}",
            f"Folder data   : {BASE_DIR}",
            "",
            f"Lisensi       : "
            + ("AKTIF" if self.lisensi_ok else "BELUM AKTIF")
            + f"  (kode mesin {_kode_mesin()})",
            f"Pengaturan    : {SETTINGS_FILE}",
            f"               file ada={os.path.exists(SETTINGS_FILE)}"
            f", isi={isi if isi else '(kosong)'}",
            f"Popup tips    : "
            + ("BELUM pernah - akan muncul saat Start"
               if self._first_run else "sudah pernah tampil"),
            "",
        ]
        if self._detected:
            baris.append("Browser terdeteksi:")
            for n, p in self._detected:
                baris.append(f"  - {n}: {p}")
        else:
            baris.append("Browser terdeteksi: (kosong - modul bot belum termuat?)")
        bot = self.bot
        if bot:
            profil = getattr(bot, "DEDICATED_PROFILE", "")
            baris.append(f"Profil khusus : {profil}  (ada={os.path.isdir(profil)})")
            try:
                peta = json.load(open(bot._LEVEL_MAP_FILE, encoding="utf-8"))
                npeta = len(peta)
            except Exception:
                npeta = 0
            baris.append(f"Peta level    : {bot._LEVEL_MAP_FILE} ({npeta} level tercatat)")
            port_dbg = getattr(bot, "DEBUG_PORT", 9222)
            baris.append(f"Port debug({port_dbg}) : "
                         + ("TERBUKA - browser debug sedang jalan"
                            if bot._cek_debug_port() else "kosong"))
            baris.append(f"Patroli login : PERLU_LOGIN={getattr(bot, 'PERLU_LOGIN', False)} "
                         f"sentinel_ok={getattr(bot, '_login_sentinel', {}).get('ok', '?')} "
                         f"alasan={getattr(bot, '_login_sentinel', {}).get('alasan', '') or '-'}")
        else:
            baris.append("Modul bot     : BELUM termuat")
        baris.append(f"ENV           : TYPINGBOT_BROWSER="
                     f"{os.environ.get('TYPINGBOT_BROWSER', '(tidak di-set)')}")
        return "\n".join(baris)


    def _dev_salin(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._log("Info developer disalin ke clipboard.")


    def _dev_uji_pilih(self):
        hasil = dialog_pilih_browser(self.root, self._detected,
                                     self.browser_var.get(), self._profile)
        self._log(f"[Dev] uji pilih browser: {hasil!r}")


    def _dev_uji_buka(self):
        det = dict(self._detected)
        pilih = self.browser_var.get()
        nm = pilih if pilih in det else (
            (self.bot._find_browser() or {}).get("name", "browser") if self.bot
            else "browser")
        ok = dialog_buka_browser(self.root, nm, det.get(nm), "bot")
        self._log(f"[Dev] uji buka browser ({nm}): dijawab "
                  f"{'Ya (buka)' if ok else 'Tidak'}")


    def _dev_reset(self):
        try:
            if os.path.exists(SETTINGS_FILE):
                os.remove(SETTINGS_FILE)
            self._first_run = True
            self.browser_var.set("Otomatis")
            self._log("Pengaturan dihapus - popup pilih browser aktif lagi. "
                      "(Lisensi tidak ikut terhapus.)")
        except Exception as ex:
            self._log(f"[Dev] gagal reset pengaturan: {ex}")


    def _dev_buka(self, path):
        try:
            os.startfile(path)   # file -> aplikasi default, folder -> explorer
        except Exception as ex:
            self._log(f"[Dev] gagal membuka {path}: {ex}")
