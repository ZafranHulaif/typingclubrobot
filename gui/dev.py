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

from .dialogs import dialog_open_browser, dialog_pick_browser
from .licensing import _machine_code, _load_online_token
from net import api as netapi
from net import license as netlic
from .theme import (APP_VERSION, BASE_DIR, BG, CARD, EDGE, FG, LICENSE_FILE, LOG_FILE, PANEL, CREATOR, PROGRAM_PATH, SETTINGS_FILE, _build_stamp)


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
        baris2.pack(fill="x", padx=8, pady=(2, 2))
        baris3 = tk.Frame(win, bg=PANEL)
        baris3.pack(fill="x", padx=8, pady=(2, 2))
        baris4 = tk.Frame(win, bg=PANEL)
        baris4.pack(fill="x", padx=8, pady=(2, 8))

        def button(induk, nama, cmd):
            b = tk.Label(induk, text=nama, font=("Segoe UI", 9, "bold"),
                         fg=FG, bg=CARD, padx=10, pady=4, cursor="hand2",
                         highlightthickness=1, highlightbackground=EDGE)
            b.pack(side="left", padx=(0, 6))
            b.bind("<Button-1>", lambda e: self._safe(cmd))

        button(baris1, "Salin info", lambda: self._dev_salin(info))
        button(baris1, "Uji: pilih browser", self._dev_uji_pilih)
        button(baris1, "Uji: buka browser", self._dev_uji_buka)
        button(baris2, "Kelola lisensi", self._request_license)
        button(baris2, "Reset pengaturan", self._dev_reset)
        button(baris2, "Buka bot.log", lambda: self._dev_buka(LOG_FILE))
        button(baris2, "Buka folder", lambda: self._dev_buka(BASE_DIR))
        # --- uji fitur online (v2.7): lisensi + pembaruan ---
        button(baris3, "Cek lisensi+update", self._dev_net_check)
        button(baris3, "Hapus lisensi (uji fresh)", self._dev_hapus_lisensi)
        button(baris3, "Cek pembaruan", self._dev_cek_update)
        button(baris4, "Versi 0.0.1: ON/OFF", self._dev_toggle_fake_version)
        button(baris4, "Buka halaman admin", self._dev_buka_admin)


    def _dev_info(self):
        try:
            isi = open(SETTINGS_FILE, encoding="utf-8").read().strip()
        except Exception:
            isi = None
        baris = [
            f"Versi         : TypingBot {APP_VERSION}",
            f"Build         : {_build_stamp()}  (waktu file program dibuat)",
            f"Pembuat       : {CREATOR}  (github.com/{CREATOR})",
            f"Mode          : "
            + ("EXE (PyInstaller)" if getattr(sys, "frozen", False)
               else "skrip Python"),
            f"Lokasi program: {PROGRAM_PATH}",
            f"Folder data   : {BASE_DIR}",
            "",
            f"Lisensi       : "
            + ("AKTIF" if self.lisensi_ok else "BELUM AKTIF")
            + f"  (kode mesin {_machine_code()})",
            f"Lisensi online: {self._dev_lic_info()}",
            f"Server        : {netapi.BASE_URL or '(tidak dikonfigurasi)'}",
            f"Nickname      : {self._load_nickname() or '-'}"
            + (f"  | versi lokal dikira {self._ver_override}"
               if getattr(self, "_ver_override", None) else ""),
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
                            if bot._check_debug_port() else "kosong"))
            baris.append(f"Patroli login : NEEDS_LOGIN={getattr(bot, 'NEEDS_LOGIN', False)} "
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
        hasil = dialog_pick_browser(self.root, self._detected,
                                     self.browser_var.get(), self._profile)
        self._log(f"[Dev] uji pilih browser: {hasil!r}")


    def _dev_uji_buka(self):
        det = dict(self._detected)
        pilih = self.browser_var.get()
        nm = pilih if pilih in det else (
            (self.bot._find_browser() or {}).get("name", "browser") if self.bot
            else "browser")
        ok = dialog_open_browser(self.root, nm, det.get(nm), "bot")
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


    # --------------------------------------------- uji fitur online (v2.7)

    def _dev_lic_info(self):
        tok = _load_online_token()
        if tok and netlic.verify_token(tok):
            return (f"token valid, sisa {netlic.days_left(tok)} hari "
                    f"(exp {time.strftime('%Y-%m-%d', time.localtime(int(tok['exp'])))})")
        if tok:
            return "token ADA tapi kedaluwarsa/tidak valid"
        if self.lisensi_ok:
            return "memakai kunci lama (HMAC manual)"
        return "tidak ada"

    def _dev_net_check(self):
        threading.Thread(target=self._net_worker, daemon=True).start()
        self._log("[Dev] cek lisensi + pembaruan dijalankan (lihat baris [net]).")

    def _dev_hapus_lisensi(self):
        try:
            if os.path.exists(LICENSE_FILE):
                os.remove(LICENSE_FILE)
                self.lisensi_ok = False
                self._title_bar()
                self._log("[Dev] file lisensi dihapus - mesin kini 'fresh'. "
                          "Tekan 'Cek lisensi+update' untuk alur persetujuan "
                          "penuh, atau restart aplikasi.")
            else:
                self._log("[Dev] file lisensi memang tidak ada.")
        except Exception as ex:
            self._log(f"[Dev] gagal hapus lisensi: {ex}")

    def _dev_cek_update(self):
        threading.Thread(target=self._net_update_check, daemon=True).start()
        self._log("[Dev] cek pembaruan dijalankan.")

    def _dev_toggle_fake_version(self):
        if getattr(self, "_ver_override", None):
            self._ver_override = None
            self._log("[Dev] versi lokal kembali normal - cek pembaruan "
                      "akan bilang sudah terbaru.")
        else:
            self._ver_override = "0.0.1"
            self._log("[Dev] versi lokal DIKIRA 0.0.1 - tombol pembaruan "
                      "akan muncul setelah cek. Tekan tombol hijau itu untuk "
                      "uji unduh+verifikasi hash (swap exe hanya di EXE).")
        threading.Thread(target=self._net_update_check, daemon=True).start()

    def _dev_buka_admin(self):
        import webbrowser
        if not netapi.BASE_URL:
            self._log("[Dev] server tidak dikonfigurasi.")
            return
        url = netapi.BASE_URL + "/admin"
        try:
            kunci = json.load(open(os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "server", "_admin.json"), encoding="utf-8"))["admin_key"]
            url += "?key=" + kunci
        except Exception:
            pass
        webbrowser.open(url)
        self._log("[Dev] halaman admin dibuka di browser.")
