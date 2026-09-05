"""Jendela utama (mixin activity/launch/dev) + entry point."""

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

from .licensing import _machine_code, _license_valid
from .theme import (APP_VERSION, BG, BTN_FG, CARD, CARD_HOVER, DIM, EDGE, FAINT, FG, GREEN, PANEL, CREATOR, RED, SETTINGS_FILE, YELLOW, _build_stamp)
from .widgets import Dropdown


from .activity import ActivityMixin
from .dev import DevMixin
from .launch import LaunchMixin


class App(ActivityMixin, LaunchMixin, DevMixin):
    """Jendela utama TypingBot."""

    def __init__(self, root):
        self.root = root
        self.bot = None
        self.bot_thread = None
        self.log_q = queue.Queue()
        self._ui_queue = queue.Queue()
        self.log_file = None
        self._detected = []          # [(nama, path)] browser terpasang
        self._first_run = not os.path.exists(SETTINGS_FILE)
        self._login_win = None       # popup 'login dulu' (aktif saat sesi mati)
        self._login_dismiss = False  # user menutup popup login manual
        self._tanya_win = None       # popup 'bot menunggu, lanjut/stop?'
        self._selesai_info = False   # popup 'rentang selesai' sudah tampil
        self._terkunci_win = None    # popup 'level start terkunci'
        self._tanya_rentang = True   # tanya rentang level saat Start berikutnya
        self._rentang_terbuka = False   # dialog rentang sedang tampil (state label)
        self._tunggu_pilih_halaman = False  # user memilih level awal di browser
        self._login_grace = 0        # jeda re-popup login setelah tombol buka login
        self._profile = "bot"        # 'bot' khusus | 'saya' profil browser user
        self._profile_dir = ""       # 'Default' / 'Profile 1' ... (mode saya)
        self._profile_label = ""     # nama tampilan profil (mis. 'Student')
        self._nick_q = queue.Queue()   # nickname dari dialog online -> thread net
        self._tok_cache = None         # token lisensi online terakhir (net)
        self._update_info = None       # info rilis baru (thread net)
        self._updating = False         # sedang mengunduh pembaruan
        self._online_cancel = False    # user menutup dialog aktivasi online
        self._online_dlg = None        # dialog aktivasi online aktif
        self._update_btn = None        # tombol perbarui (muncul bila ada rilis)
        self.lisensi_ok = _license_valid()

        root.title("TypingBot")
        # ukuran jendela mengikuti DPI layar (dipanggil setelah
        # SetProcessDpiAwareness di __main__; skrip/uji tanpa itu = 1.0)
        try:
            k = float(root.tk.call("tk", "scaling")) / (96.0 / 72.0)
        except Exception:
            k = 1.0
        k = max(1.0, min(k, 2.0))
        root.geometry(f"{int(780 * k)}x{int(460 * k)}")
        # tinggi minimum kecil: pengguna boleh mengecilkan jendela sampai
        # kecil - footer hotkey tetap tampak, hanya log yang menyusut
        root.minsize(int(700 * k), int(330 * k))
        root.configure(bg=BG)
        self._title_bar()

        try:
            root.attributes("-topmost", True)
            root.attributes("-topmost", False)
        except Exception:
            pass
        # ---------- zona atas: header status, baris tombol (+ kartu browser
        # ---------- persegi DI samping Stop), lalu baris kecepatan ----------
        self._last_browser_path = ""   # exe terakhir yang dipakai mode Otomatis
        # browser_var wajib dibuat sebelum chip (chip membacanya saat render)
        self.browser_var = tk.StringVar(value="Otomatis")
        self.browser_dd = type(
            "_NoDD", (), {"set_values": lambda self, v: None,
                          "configure": lambda self, **kw: None})()

        head = tk.Frame(root, bg=BG)
        head.pack(fill="x", padx=18, pady=(16, 2))
        self.state_lbl = tk.Label(head, text="⏻ Siap", font=("Segoe UI", 15, "bold"),
                                  fg=FG, bg=BG)
        self.state_lbl.pack(side="left")
        self.ver_lbl = tk.Label(head,
                                text=f"v{APP_VERSION}  •  oleh {CREATOR}  •  "
                                     f"build {_build_stamp()}",
                                font=("Segoe UI", 9), fg=FAINT, bg=BG)
        self.ver_lbl.pack(side="right", pady=(6, 0))
        # Akses jendela Dev (hanya untuk pemilik): klik teks versi 5x cepat
        # atau Ctrl+Shift+D. Tidak ada tombol terlihat.
        self._dev_klik = []
        self.ver_lbl.bind("<Button-1>", self._dev_gesture)
        root.bind("<Control-Shift-D>", lambda e: self._safe(self.on_dev))

        ctrl = tk.Frame(root, bg=BG)
        ctrl.pack(fill="x", padx=18, pady=(8, 2))
        self.btn_start = self._btn(ctrl, "▶  Start", GREEN, self.on_start, besar=True)
        self.btn_pause = self._btn(ctrl, "⏸  Pause", YELLOW, self.on_pause, besar=True)
        self.btn_pause["state"] = "disabled"
        self.btn_stop = self._btn(ctrl, "⏹  Stop", RED, self.on_stop, besar=True)
        self.btn_stop["state"] = "disabled"

        # --- kartu browser persegi, di samping Stop (klik = ganti) ---
        # ukuran dihitung dari isi + jadi persegi (auto, tahan DPI: ukuran
        # fix 132x96 px + font yang ikut scaling 125-150% = teks terpotong)
        self.chip = tk.Frame(ctrl, bg=CARD, highlightthickness=1,
                             highlightbackground=EDGE, cursor="hand2",
                             width=132, height=96)
        self.chip.pack(side="left", padx=(14, 0))
        self.chip.pack_propagate(False)
        self._update_browser_chip()

        self.kanan = tk.Frame(ctrl, bg=BG)
        self.kanan.pack(side="right")
        self._btn(self.kanan, "❓", CARD, self.on_tips, kecil=True)

        # ---------- baris pengaturan: kecepatan ----------
        # Dropdown Browser dihapus (permintaan user): pilihan browser lewat
        # kartu persegi kanan / popup kartu logo.
        setbar = tk.Frame(root, bg=BG)
        setbar.pack(fill="x", padx=18, pady=(6, 8))

        kotak2 = tk.Frame(setbar, bg=BG)
        kotak2.pack(side="left", expand=True, fill="x")
        tk.Label(kotak2, text="Kecepatan", font=("Segoe UI", 9), fg=FAINT,
                 bg=BG).pack(anchor="w", padx=2)
        self.speed_var = tk.StringVar(value="Normal (140)")
        self.speed_dd = Dropdown(kotak2, self.speed_var,
                                 ("Normal (140)", "Cepat (200)", "Santai (85)"),
                                 on_change=self.on_speed)
        self.speed_dd.pack(anchor="w", pady=(2, 0), fill="x")

        # Rentang level tidak lagi ada di jendela utama (diminta saat Start
        # atau otomatis dari lesson yang sedang terbuka).
        self._rentang_mulai, self._rentang_akhir = self._load_range()
        self._total_level = 685
        self._rentang_btn = type("_NoBtn", (), {"configure": lambda self, **kw: None})()

        # ---------- footer: tombol cepat + saklar aktif/nonaktif ----------
        # dipasang paling awal dengan side="bottom": widget yang di-pack
        # lebih awal mendapat jatah ukuran lebih dulu - saat jendela
        # dikecilkan vertikal, kartu aktivitas-lah yang menyusut, footer
        # selalu tampak (dulu footer di-pack terakhir -> teks terpotong
        # duluan;).
        self._hotkey = True
        self.hotkey_lbl = tk.Label(root, text="", font=("Segoe UI", 9),
                                   fg=FAINT, bg=BG, cursor="hand2",
                                   wraplength=640, justify="center")
        self.hotkey_lbl.pack(side="bottom", fill="x", pady=(0, 8))
        self.hotkey_lbl.bind("<Button-1>", lambda e: self._safe(self._toggle_hotkey))
        self._update_hotkey_label()

        # ---------- kartu aktivitas (mengisi sisa ruang tengah) ----------
        # Pengganti log lama (permintaan: user awam tidak perlu lihat log):
        # satu kalimat besar bahasa awam - apa yang bot kerjakan sekarang.
        # Rincian teknis tetap tersimpan di bot.log untuk pemilik (Dev).
        self._aktiv_sub_teks = ""
        self._aktiv_nama = ""
        aktiv = tk.Frame(root, bg=PANEL, highlightthickness=1,
                         highlightbackground=EDGE)
        aktiv.pack(fill="both", expand=True, padx=18, pady=(0, 6))
        tengah = tk.Frame(aktiv, bg=PANEL)
        tengah.place(relx=0.5, rely=0.5, anchor="center")
        self.aktiv_lbl = tk.Label(tengah, text="Siap",
                                  font=("Segoe UI", 16, "bold"), fg=FG,
                                  bg=PANEL, wraplength=560, justify="center")
        self.aktiv_lbl.pack()
        self.aktiv_sub = tk.Label(tengah, text="Klik Start untuk mulai.",
                                  font=("Segoe UI", 10), fg=DIM, bg=PANEL,
                                  wraplength=560, justify="center")
        self.aktiv_sub.pack(pady=(6, 0))

        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._log(f"TypingBot v{APP_VERSION}  •  build {_build_stamp()}")
        if self.lisensi_ok:
            self._log(f"Lisensi aktif (mesin {_machine_code()}).")
        else:
            self._log(f"Lisensi belum aktif - kode mesin: {_machine_code()}")
        threading.Thread(target=self._load_bot, daemon=True).start()
        threading.Thread(target=self._net_worker, daemon=True).start()
        self.root.after(150, self._poll)


    def _title_bar(self):
        ekstra = "" if self.lisensi_ok else "  •  PERLU AKTIVASI"
        self.root.title(f"TypingBot{ekstra}")


    # ------------------------------------------------------------------ UI util

    def _btn(self, parent, text, color, cmd, besar=False, kecil=False):
        if besar:
            font, padx, pady = ("Segoe UI", 11, "bold"), 24, 9
        elif kecil:
            font, padx, pady = ("Segoe UI", 12, "bold"), 13, 8
        else:
            font, padx, pady = ("Segoe UI", 10, "bold"), 16, 6
        b = tk.Label(parent, text=text, font=font, fg=BTN_FG, bg=color,
                     padx=padx, pady=pady, cursor="hand2")
        if kecil:
            b.configure(fg=FG, highlightthickness=1, highlightbackground=EDGE)
        b.pack(side="left", padx=(0, 8) if besar or not kecil else (6, 0))

        def on_enter(_):
            if str(b["state"]) != "disabled":
                b.configure(bg=CARD_HOVER if kecil else self._dim(color, 0.88))

        def on_leave(_):
            if str(b["state"]) != "disabled":
                b.configure(bg=color)

        b.bind("<Enter>", on_enter)
        b.bind("<Leave>", on_leave)
        b.bind("<Button-1>", lambda e: self._safe(cmd))
        b._base_color = color
        return b


    @staticmethod
    def _dim(hex_color, f):
        r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
        return f"#{int(r * f):02x}{int(g * f):02x}{int(b * f):02x}"


    def _set_state(self, text, color):
        self.state_lbl.configure(text=text, fg=color)


    def _set_activity(self, utama, sub):
        """Kartu aktivitas: kalimat besar bahasa awam + keterangan kecil."""
        try:
            self.aktiv_lbl.configure(text=utama)
            self.aktiv_sub.configure(text=sub)
        except Exception:
            pass


    def _safe(self, cmd):
        try:
            cmd()
        except Exception as ex:
            import traceback
            self._log(f"[GUI] error: {ex!r}")
            try:
                self.log_file.write(traceback.format_exc() + "\n")
                self.log_file.flush()
            except Exception:
                pass


    def _log(self, line):
        self.log_q.put(line)
        try:
            if self.log_file:
                self.log_file.write(line + "\n")
                self.log_file.flush()
        except Exception:
            pass


    # ------------------------------------------------------------------ start

    def _update_hotkey_label(self):
        """Footer = indikator + saklar hotkey global (permintaan user:
        F9/F10/F11 bisa tak sengaja mengetik bot saat dipakai app lain)."""
        try:
            if self._hotkey:
                self.hotkey_lbl.configure(
                    text="⌨  F9 jeda   •   F10 kecepatan   •   F11 stop   •   "
                         "AKTIF  (klik untuk matikan)",
                    fg=DIM)
            else:
                self.hotkey_lbl.configure(
                    text="⌨  Hotkey F9/F10/F11 NONAKTIF  (klik untuk nyalakan)",
                    fg=FAINT)
        except Exception:
            pass


    def _toggle_hotkey(self):
        self._hotkey = not self._hotkey
        self._save_settings()
        self._update_hotkey_label()
        if self.bot:
            self.bot.HOTKEYS_ON = self._hotkey
        self._log("Hotkey global F9/F10/F11 "
                  + ("diaktifkan." if self._hotkey else "DIMATIKAN."))


    def _save_settings(self):
        """Tulis typingbot_settings.json: browser pilihan + browser terakhir
        yang dipakai Otomatis (dipertahankan antar ganti pilihan)."""
        data = {}
        try:
            data = json.load(open(SETTINGS_FILE, encoding="utf-8"))
        except Exception:
            pass
        data["browser"] = self.browser_var.get()
        data["hotkey"] = bool(self._hotkey)
        data["profile"] = self._profile
        data["profile_dir"] = self._profile_dir
        data["profile_label"] = self._profile_label
        if self._last_browser_path:
            data["last_browser"] = self._last_browser_path
        try:
            json.dump(data, open(SETTINGS_FILE, "w", encoding="utf-8"))
        except Exception:
            pass


    def on_close(self):
        if self.bot:
            self.bot.STOP = True
            self.bot.PAUSED = False
        time.sleep(0.2)
        self.root.destroy()




if __name__ == "__main__":
    # DPI awareness wajib sebelum Tk dibuat: tanpa ini Windows merender app
    # di 96dpi lalu meregangnya bitmap-style -> GUI terlihat buram/low-res
    # di layar dengan scaling 125%/150% (laptop modern).
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PER_MONITOR_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    root = tk.Tk()
    try:
        from tkinter import font as tkfont
        default_font = tkfont.nametofont("TkDefaultFont")
        default_font.configure(family="Segoe UI", size=10)
    except Exception:
        pass
    App(root)
    root.mainloop()
