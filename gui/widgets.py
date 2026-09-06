"""Widget dasar: dropdown dan dialog."""

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

from .icons import _draw_vector_icon
from .theme import (ACCENT, BTN_FG, CARD, CARD_HOVER, DIM, EDGE, FG, PANEL)




# ------------------------------------------------------------ dialog visual
class Dropdown(tk.Frame):
    """Dropdown custom (tk.Menu) - klik di MANA SAJA pada kotak membuka
    daftar; pengganti ttk.Combobox yang panahnya sulit terlihat/klik."""

    def __init__(self, parent, variable, values, on_change=None, lebar=12):
        super().__init__(parent, bg=CARD, highlightthickness=1,
                         highlightbackground=EDGE, cursor="hand2")
        self._var = variable
        self._values = list(values)
        self._cb = on_change
        self._lbl = tk.Label(self, text=variable.get(), font=("Segoe UI", 10),
                             fg=FG, bg=CARD, anchor="w", width=lebar,
                             cursor="hand2")
        self._lbl.pack(side="left", padx=(10, 4), pady=6, fill="x")
        self._arrow = tk.Label(self, text="▾", font=("Segoe UI", 9), fg=DIM,
                               bg=CARD, cursor="hand2")
        self._arrow.pack(side="right", padx=(0, 10))
        # sinkron label kalau variabel di-set dari luar (bukan lewat _set)
        variable.trace_add("write", lambda *_: self._lbl.configure(
            text=self._var.get()))
        for w in (self, self._lbl, self._arrow):
            w.bind("<Button-1>", self._buka)
            w.bind("<Enter>", lambda e: self._warna(CARD_HOVER))
            w.bind("<Leave>", lambda e: self._warna(CARD))

    def _warna(self, bg):
        for w in (self, self._lbl, self._arrow):
            w.configure(bg=bg)
        self.configure(highlightbackground=ACCENT if bg == CARD_HOVER else EDGE)

    def set_values(self, values):
        self._values = list(values)

    def _menu(self):
        m = tk.Menu(self, tearoff=0, bg=CARD, fg=FG, activebackground=ACCENT,
                    activeforeground="#ffffff", bd=0, activeborderwidth=0,
                    relief="flat", font=("Segoe UI", 10))
        for v in self._values:
            tanda = "✓  " if v == self._var.get() else "     "
            m.add_command(label=tanda + v, command=lambda val=v: self._set(val))
        return m

    def _buka(self, e=None):
        m = self._menu()
        # posisikan menu DI titik klik (bukan sisi kiri kotak: kotak speed
        # melebar satu baris penuh - dulu menu muncul jauh di kiri padahal
        # user menekan kanan;). Clamp supaya tidak keluar layar.
        try:
            x = e.x_root if e is not None else self.winfo_rootx()
        except Exception:
            x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + 2
        try:
            lebar_layar = self.winfo_screenwidth()
            m.update_idletasks()
            mw = m.winfo_reqwidth()
            x = max(self.winfo_rootx(), min(x - 20, lebar_layar - mw - 8))
        except Exception:
            pass
        try:
            m.tk_popup(x, y)
        finally:
            m.grab_release()

    def _set(self, val):
        self._var.set(val)
        self._lbl.configure(text=val)
        if self._cb:
            try:
                self._cb()
            except Exception:
                pass




def _gelap_titlebar(jendela):
    """Title bar gelap ala Windows 11 untuk Toplevel apa pun (jendela
    utama, dialog, jendela dev). Dipanggil delayed - hwnd baru siap
    setelah jendela wujud."""
    try:
        u = ctypes.windll.user32
        dwm = ctypes.windll.dwmapi
        anak = jendela.winfo_id()
        hwnd = u.GetParent(anak) or anak
        n = ctypes.c_int(1)
        if dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(n), 4) != 0:
            dwm.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(n), 4)
        u.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                       0x0001 | 0x0002 | 0x0020 | 0x0040)
    except Exception:
        pass


def gelap_titlebar_berulang(jendela, jeda=(150, 600, 1500)):
    """Terapkan gelap title bar beberapa kali: penerapan tunggal di
    150ms kadang tidak melekat (jendela dev pernah tetap putih padahal
    hwnd sudah ada) - frame DWM baru siap setelah paint pertama."""
    def coba(i=0):
        _gelap_titlebar(jendela)
        if i + 1 < len(jeda):
            try:
                jendela.after(jeda[i + 1], lambda: coba(i + 1))
            except Exception:
                pass
    try:
        jendela.after(jeda[0], lambda: coba(0))
    except Exception:
        pass


class ScrollbarGelap(tk.Canvas):
    """Scrollbar gelap buatan sendiri - tk.Scrollbar bawaan selalu
    putih di Windows dan tidak bisa diwarnai.
    Pakai: sb = ScrollbarGelap(induk, kanvas.yview); lalu
    kanvas.configure(yscrollcommand=sb.set)."""

    def __init__(self, induk, perintah, lebar=12, **kw):
        super().__init__(induk, width=lebar, bg=PANEL,
                         highlightthickness=0, **kw)
        self._cmd = perintah
        self._lebar = lebar
        self._awal = 0.0
        self._akhir = 1.0
        self._pinned = None
        self._thumb = self.create_rectangle(2, 2, lebar - 2, 60,
                                            fill=CARD, width=0)
        self.bind("<Button-1>", self._klik)
        self.bind("<B1-Motion>", self._seret)
        self.bind("<Configure>", lambda e: self._posisi())

    def set(self, awal, akhir):
        try:
            self._awal, self._akhir = float(awal), float(akhir)
            self._posisi()
        except Exception:
            pass

    def _posisi(self):
        h = self.winfo_height()
        if h < 24:
            return
        rentang = self._akhir - self._awal
        if rentang <= 0.0001:      # seluruh konten terlihat: sembunyikan
            self.coords(self._thumb, 2, -10, self._lebar - 2, -2)
            return
        tinggi = max(28, rentang * h)
        y0 = self._awal / (1.0 - rentang) * (h - tinggi)
        self.coords(self._thumb, 2, y0, self._lebar - 2, y0 + tinggi)

    def _klik(self, e):
        self._pinned = e.y
        h = self.winfo_height()
        if h > 1:
            self._cmd(("moveto", str(max(
                0.0, e.y / h - (self._akhir - self._awal) / 2))))

    def _seret(self, e):
        h = self.winfo_height()
        if h <= 1 or self._pinned is None:
            return
        awal = self._awal + (e.y - self._pinned) / h * (
            1.0 - (self._akhir - self._awal))
        self._pinned = e.y
        self._cmd(("moveto", str(max(0.0, awal))))




class _Dialog(tk.Toplevel):
    """Kerangka dialog gelap: ikon bulat + judul + subjudul, body, tombol."""

    def __init__(self, induk, judul, subjudul="", ikon="ℹ", warna=ACCENT):
        super().__init__(induk)
        self.hasil = None
        self._primer = None
        self.configure(bg=PANEL)
        self.transient(induk)
        self.resizable(False, False)
        gelap_titlebar_berulang(self)

        head = tk.Frame(self, bg=PANEL)
        head.pack(fill="x", padx=24, pady=(22, 4))
        box = tk.Canvas(head, width=46, height=46, bg=PANEL, highlightthickness=0)
        box.pack(side="left")
        box.create_oval(2, 2, 44, 44, fill=warna, width=0)
        # ikon header: pusat lingkaran eksak (23,23); 🌐/⚠ digambar vektor
        # (emoji glyph-nya tidak persis di tengah kotak em -)
        if ikon == "🌐":
            _draw_vector_icon(box, "bola", 23, 23, 21)
        elif ikon == "⚠":
            _draw_vector_icon(box, "warning", 23, 23, 20)
        elif ikon == "⛔":
            _draw_vector_icon(box, "stop", 23, 23, 21)
        else:
            box.create_text(23, 23, text=ikon,
                            font=("Segoe UI Emoji", 16, "bold"),
                            fill="white", anchor="center")
        jt = tk.Frame(head, bg=PANEL)
        jt.pack(side="left", padx=(14, 0))
        tk.Label(jt, text=judul, font=("Segoe UI", 14, "bold"),
                 fg=FG, bg=PANEL).pack(anchor="w")
        if subjudul:
            tk.Label(jt, text=subjudul, font=("Segoe UI", 9), fg=DIM, bg=PANEL,
                     wraplength=380, justify="left").pack(anchor="w", pady=(2, 0))

        tk.Frame(self, bg=EDGE, height=1).pack(fill="x", padx=24, pady=(14, 0))
        self.body = tk.Frame(self, bg=PANEL)
        self.body.pack(fill="both", expand=True, padx=24, pady=14)
        tk.Frame(self, bg=EDGE, height=1).pack(fill="x", padx=24)
        self.foot = tk.Frame(self, bg=PANEL)
        self.foot.pack(fill="x", padx=24, pady=(12, 20))

        self.protocol("WM_DELETE_WINDOW", lambda: self.done(None))
        self.bind("<Escape>", lambda e: self.done(None))
        self.bind("<Return>", self._enter)

    def _enter(self, _e):
        if self._primer:
            self._primer._klik()

    def button(self, teks, nilai=None, warna_btn=ACCENT, primer=True, cmd=None):
        if primer:
            b = tk.Label(self.foot, text=teks, font=("Segoe UI", 10, "bold"),
                         fg=BTN_FG, bg=warna_btn, padx=20, pady=7, cursor="hand2")
        else:
            b = tk.Label(self.foot, text=teks, font=("Segoe UI", 10, "bold"),
                         fg=FG, bg=CARD, padx=18, pady=7, cursor="hand2",
                         highlightthickness=1, highlightbackground=EDGE)
        b.pack(side="right", padx=(8, 0))
        if primer and not self._primer:
            self._primer = b

        def klik(_e=None):
          if cmd:
            if cmd() is False:
              return
            return
          self.done(nilai if nilai is not None else teks)

        b._klik = klik
        b.bind("<Button-1>", klik)
        return b

    def done(self, nilai):
        self.hasil = nilai
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()

    def show(self):
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        # tengah layar (dulu: tengah jendela induk - saat induk belum
        # terpetakan atau di posisi pojok, popup menumpuk di kiri atas)
        try:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
        except Exception:
            sw, sh = 1920, 1080
        self.geometry(f"+{max((sw - w) // 2, 8)}+{max((sh - h) // 3, 40)}")
        # angkat dialog ke depan meski user sedang fokus di browser
        # (live: dialog rentang muncul tersembunyi di belakang jendela lain)
        try:
            self.attributes("-topmost", True)
            self.lift()
            self.focus_force()
        except Exception:
            pass
        self.grab_set()
        if self._primer:
            self._primer.focus_set()
        self.wait_window(self)
        return self.hasil
