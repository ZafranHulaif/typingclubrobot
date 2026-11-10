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
from .theme import (ACCENT, BG, BTN_FG, CARD, CARD_HOVER, DIM, EDGE, FAINT, FG,
                    PANEL)




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
        # NOZORDER+NOACTIVATE WAJIB (live: dulu HWND_TOP polos tiap 3
        # dtk = app terus naik menutupi app lain yang sedang dipakai
        # user tanpa merebut keyboard - keluhan 'overlay over the
        # focused app'). Cukup FRAMECHANGED utk segarkan warna bar.
        u.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                       0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020)
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




# Layer dialog dalam-app: diisi App dgn Wv2Host saat webview siap.
# Kalau terisi dan kontrol webview hidup, SEMUA _Dialog otomatis tampil
# DI DALAM jendela app (menempati area webview) - bukan jendela OS
# terpisah (keluhan user: "kenapa popup kita jendela sendiri?").
_DIALOG_LAYER = None


def set_dialog_layer(layer):
    global _DIALOG_LAYER
    _DIALOG_LAYER = layer


class _Dialog(tk.Toplevel):
    """Kerangka dialog gelap: ikon bulat + judul + subjudul, body, tombol.

    Dua mode (API sama persis, pemanggil tak perlu tahu):
    - jendela: Toplevel biasa (mode browser eksternal / test suite).
    - overlay (DIALOG_LAYER terisi + webview hidup): digambar DI DALAM
      jendela app, menempati area webview. WebView2 = HWND native, widget
      Tk tak bisa menembus ke atasnya -> kontrol webview disembunyikan
      sebentar (lepas_untuk_dialog), halaman & sesi tetap hidup."""

    def __init__(self, induk, judul, subjudul="", ikon="ℹ", warna=ACCENT):
        super().__init__(induk)
        self.hasil = None
        self._primer = None
        self._mode_overlay = False
        self._kartu = None
        layer = _DIALOG_LAYER
        if (layer is not None and getattr(layer, "webview_hidup", lambda: False)()
                and not getattr(layer, "_dialog_aktif", False)):
            self._mode_overlay = True
            self._layer = layer
        else:
            self._layer = None
        if self._mode_overlay:
            self._buat_overlay(judul, subjudul, ikon, warna)
            return
        self.configure(bg=PANEL)
        self.transient(induk)
        self.resizable(False, False)
        # sembunyikan sampai show() selesai memosisikan: tanpa ini dialog
        # sempat terlihat sekejap di posisi default WM, dan -topmost yang
        # dipasang saat jendela belum terpetakan MEMAKSA posisi (0,0)
        # (bug Windows: popup menumpuk di pojok kiri atas).
        self.withdraw()
        gelap_titlebar_berulang(self)
        # headerless (judul kosong): tanpa ikon/judul/subjudul & tanpa
        # garis pemisah - body langsung. Dipakai picker level yang harus
        # terasa 'seleksi di dalam app', bukan popup berbingkai.
        if not judul:
            self._judul_lbl = None
            self._sub_lbl = None
            self.body = tk.Frame(self, bg=PANEL)
            self.body.pack(fill="both", expand=True, padx=24, pady=(22, 10))
            self.foot = tk.Frame(self, bg=PANEL)
            self.foot.pack(fill="x", padx=24, pady=(0, 18))
            self.protocol("WM_DELETE_WINDOW", lambda: self.done(None))
            self.bind("<Escape>", lambda e: self.done(None))
            self.bind("<Return>", self._enter)
            return

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
        self._judul_lbl = tk.Label(jt, text=judul, font=("Segoe UI", 14, "bold"),
                                   fg=FG, bg=PANEL)
        self._judul_lbl.pack(anchor="w")
        self._sub_lbl = tk.Label(jt, text=subjudul or "",
                                 font=("Segoe UI", 9), fg=DIM, bg=PANEL,
                                 wraplength=380, justify="left")
        if subjudul:
            self._sub_lbl.pack(anchor="w", pady=(2, 0))

        tk.Frame(self, bg=EDGE, height=1).pack(fill="x", padx=24, pady=(14, 0))
        self.body = tk.Frame(self, bg=PANEL)
        self.body.pack(fill="both", expand=True, padx=24, pady=14)
        tk.Frame(self, bg=EDGE, height=1).pack(fill="x", padx=24)
        self.foot = tk.Frame(self, bg=PANEL)
        self.foot.pack(fill="x", padx=24, pady=(12, 20))

        self.protocol("WM_DELETE_WINDOW", lambda: self.done(None))
        self.bind("<Escape>", lambda e: self.done(None))
        self.bind("<Return>", self._enter)

    def _buat_overlay(self, judul, subjudul, ikon, warna):
        """Bangun kerangka dialog yang sama DI DALAM area webview (mode
        overlay). self tetap Toplevel tapi ditarik - UI aslinya kartu di
        overlay layer; body/foot menunjuk frame kartu supaya SEMUA kode
        pemanggil (d.body, d.button, ...) bekerja tanpa diubah."""
        self.withdraw()
        try:
            self.transient(self.master)
        except Exception:
            pass
        layer = self._layer
        self._layar = tk.Frame(layer, bg="#0c0d11")
        self._layar.place(relx=0, rely=0, relwidth=1, relheight=1)
        # headerless: kartu nyatu dgn layar (tanpa bingkai/outline) ->
        # tile pilihan terasa melayang langsung di app (permintaan user)
        if not judul:
            self._judul_lbl = None
            self._sub_lbl = None
            self._kartu = tk.Frame(self._layar, bg="#0c0d11",
                                   highlightthickness=0)
            self._kartu.place(relx=0.5, rely=0.5, anchor="center",
                              width=min(max(layer.winfo_width() - 96, 300),
                                        1560))
            self.body = tk.Frame(self._kartu, bg="#0c0d11")
            self.body.pack(fill="both", expand=True)
            self.foot = tk.Frame(self._kartu, bg="#0c0d11")
            self.foot.pack(fill="x")
            self._selesai = tk.BooleanVar(value=False)
            self.bind("<Escape>", lambda e: self.done(None))
            self.bind("<Return>", self._enter)
            layer.bind("<Escape>", lambda e: self.done(None))
            return
        # kartu di tengah, lebar mengikuti area (maks 560px)
        self._kartu = tk.Frame(self._layar, bg=PANEL, highlightthickness=1,
                               highlightbackground=EDGE)
        self._kartu.place(relx=0.5, rely=0.5, anchor="center",
                          width=min(max(layer.winfo_width() - 56, 300), 560))
        head = tk.Frame(self._kartu, bg=PANEL)
        head.pack(fill="x", padx=24, pady=(22, 4))
        box = tk.Canvas(head, width=46, height=46, bg=PANEL,
                        highlightthickness=0)
        box.pack(side="left")
        box.create_oval(2, 2, 44, 44, fill=warna, width=0)
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
        self._judul_lbl = tk.Label(jt, text=judul,
                                   font=("Segoe UI", 14, "bold"),
                                   fg=FG, bg=PANEL)
        self._judul_lbl.pack(anchor="w")
        self._sub_lbl = tk.Label(jt, text=subjudul or "",
                                 font=("Segoe UI", 9), fg=DIM, bg=PANEL,
                                 wraplength=380, justify="left")
        if subjudul:
            self._sub_lbl.pack(anchor="w", pady=(2, 0))
        tk.Frame(self._kartu, bg=EDGE, height=1).pack(
            fill="x", padx=24, pady=(14, 0))
        self.body = tk.Frame(self._kartu, bg=PANEL)
        self.body.pack(fill="both", expand=True, padx=24, pady=14)
        tk.Frame(self._kartu, bg=EDGE, height=1).pack(
            fill="x", padx=24)
        self.foot = tk.Frame(self._kartu, bg=PANEL)
        self.foot.pack(fill="x", padx=24, pady=(12, 20))
        # penanda selesai dibuat SEKARANG (bukan di show): kalau user sempat
        # mengklik tombol sebelum show() dieksekusi, done() tak boleh
        # meninggalkan show() menunggu variabel yang tak pernah di-set
        self._selesai = tk.BooleanVar(value=False)
        self.bind("<Escape>", lambda e: self.done(None))
        self.bind("<Return>", self._enter)
        layer.bind("<Escape>", lambda e: self.done(None))

    def set_header(self, judul=None, subjudul=None):
        """Ubah judul/subjudul header sesudah dialog tampil (dipakai
        dialog aktivasi: saat menunggu, header dipangkas minimal -
        tanpa subjudul, biar fokus ke animasi)."""
        try:
            if judul is not None:
                self._judul_lbl.configure(text=judul)
            if subjudul:                       # '' / None -> sembunyikan
                self._sub_lbl.configure(text=subjudul)
                self._sub_lbl.pack(anchor="w", pady=(2, 0))
            else:
                self._sub_lbl.pack_forget()
        except Exception:
            pass

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
        if self._mode_overlay:
            self._layer.pasang_setelah_dialog()
            try:
                if self._kartu is not None:
                    self._kartu.destroy()
                if getattr(self, "_layar", None) is not None:
                    self._layar.destroy()
            except Exception:
                pass
            try:
                self._selesai.set(True)   # lepaskan wait_variable di show()
            except Exception:
                pass
            self.destroy()
            return
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()

    def show(self):
        if self._mode_overlay:
            layer = self._layer
            layer.lepas_untuk_dialog()
            self._layar.lift()
            self._kartu.lift()
            if self._primer:
                self._primer.focus_set()
            self.wait_variable(self._selesai)
            return self.hasil
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        # tengah layar (dulu: tengah jendela induk - saat induk belum
        # terpetakan atau di posisi pojok, popup menumpuk di kiri atas)
        try:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
        except Exception:
            sw, sh = 1920, 1080
        # urutan PENTING di Windows: posisi diterapkan saat jendela masih
        # disembunyikan, baru deiconify - topmost/lift/focus SETELAH posisi
        # melekat (topmost pada jendela yang belum terpetakan menimpa
        # permintaan +x+y dan memindahkan dialog ke 0,0).
        self.geometry(f"+{max((sw - w) // 2, 8)}+{max((sh - h) // 3, 40)}")
        self.deiconify()
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



# ------------------------------------------------------- slider liquid glass
def _blend(c1, c2, t):
    """Campur dua warna hex (#rrggbb), t=0 -> c1, t=1 -> c2."""
    r1, g1, b1 = (int(c1[i:i + 2], 16) for i in (1, 3, 5))
    r2, g2, b2 = (int(c2[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % (
        round(r1 + (r2 - r1) * t), round(g1 + (g2 - g1) * t),
        round(b1 + (b2 - b1) * t))


class SpeedSlider(tk.Canvas):
    """Slider kecepatan 'liquid glass' - tebal, kaca, ber fisika.

    Rasa yang diminta user (ref: kontrol pill 'lost & found' OSIS):
    - RAIL TEBAL dengan bayangan; thumb kaca (rim terang, sheen atas,
      bayangan dalam bawah, specular kecil) yang terasa seperti tetesan.
    - Thumb TIDAK menempel kaku ke pointer: mengalir tertinggal sedikit
      (spring ikut saat drag) - rasa cair.
    - LEPAS = recoil: spring lebih lunak dengan 1-2 goyangan balik +
      denyut squash saat mendarat - bukan snap instan.
    - Drag mengalirkan nilai wpm live ke engine (command per frame saat
      nilai berubah). set_wpm() dari luar ikut dianimasikan.
    """

    H = 64          # ruang bayangan + rail tebal + label tick bawah

    def __init__(self, parent, tiers, value, command=None, released=None,
                 width=430, bg=PANEL, **kw):
        super().__init__(parent, width=width, height=self.H, bg=bg,
                         highlightthickness=0, bd=0)
        self._tiers = sorted(list(tiers), key=lambda t: t[1])
        self._command = command      # dipanggil saat nilai halus berubah
        self._released = released    # dipanggil dengan tick target saat lepas
        self._bg = bg
        self._x = 0.0                # posisi thumb aktual (px)
        self._v = 0.0                # kecepatan thumb
        self._target_x = 0.0         # tujuan spring
        self._drag_x = 0.0           # posisi pointer saat drag
        self._drag = False
        self._hover = False
        self._pulse = 0.0            # denyut mendarat (recoil squash)
        self._wpm = value
        self._tick_job = None
        self.bind("<Button-1>", self._on_down)
        self.bind("<B1-Motion>", self._on_move)
        self.bind("<ButtonRelease-1>", self._on_up)
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<Configure>", lambda e: self._snap_now())
        self._snap_now()

    # -- geometri ---------------------------------------------------------
    @property
    def _rail_y(self):
        return 26

    def _x_for(self, wpm):
        lo, hi = self._tiers[0][1], self._tiers[-1][1]
        w = max(60, self.winfo_width() or 430)
        f = (wpm - lo) / max(1, hi - lo)
        return 16 + f * (w - 32)

    def _wpm_for(self, x):
        lo, hi = self._tiers[0][1], self._tiers[-1][1]
        w = max(60, self.winfo_width() or 430)
        f = max(0.0, min(1.0, (x - 16) / max(1, w - 32)))
        return lo + f * (hi - lo)

    # -- api --------------------------------------------------------------
    def set_wpm(self, wpm):
        """Sinkron dari luar (settings/hotkey): animasi spring ke sana."""
        wpm = int(wpm)
        if wpm == self._wpm and self._tick_job is None:
            return
        if self._drag:
            return   # jangan ganggu drag berjalan
        self._wpm = wpm
        self._target_x = self._x_for(self._wpm)
        self._start_tick()

    def get_wpm(self):
        return self._wpm

    def _set_hover(self, on):
        self._hover = on
        self._draw()

    # -- interaksi --------------------------------------------------------
    def _on_down(self, e):
        self._drag = True
        self._v = 0.0
        self._drag_x = float(e.x)
        self._target_x = self._drag_x
        self._start_tick()

    def _on_move(self, e):
        if self._drag:
            self._drag_x = float(e.x)

    def _on_up(self, _e):
        self._drag = False
        # tick terdekat jadi target; spring lunak mengantar + recoil
        nearest = min(self._tiers,
                      key=lambda t: abs(self._x_for(t[1]) - self._drag_x))
        self._wpm = nearest[1]
        self._target_x = self._x_for(self._wpm)
        self._start_tick()
        if self._released:
            self._released(self._wpm)

    # -- spring physics ---------------------------------------------------
    def _snap_now(self):
        """Posisikan thumb langsung (awal/resize) tanpa animasi."""
        self._x = self._target_x = self._drag_x = self._x_for(self._wpm)
        self._v = 0.0
        self._pulse = 0.0
        self._tick_job = None
        self._draw()

    def _start_tick(self):
        if self._tick_job is None:
            self._tick_job = True
            self._tick()

    def _tick(self):
        if self._drag:
            # ikut pointer dengan keterlambatan cair (bukan tempel kaku)
            k, c = 0.45, 0.42
            self._target_x = self._drag_x
        else:
            # spring lunak: 1-2 goyangan balik (recoil) sebelum tenang
            k, c = 0.13, 0.60
        self._v += k * (self._target_x - self._x) - c * self._v
        self._x += self._v
        # denyut mendarat meluruh tiap frame
        self._pulse *= 0.82
        if self._pulse < 0.01:
            self._pulse = 0.0
        if abs(self._target_x - self._x) < 0.3 and abs(self._v) < 0.05:
            self._x = self._target_x
            self._v = 0.0
            # mendarat -> denyut squash (rasa tetesan jatuh)
            self._pulse = 1.0
            if not self._drag:
                self._tick_job = None
                self._draw()
                return
        # drag: nilai halus mengalir mengikuti posisi thumb aktual
        if self._drag:
            wpm = int(round(max(self._tiers[0][1],
                                min(self._tiers[-1][1],
                                    self._wpm_for(self._x)))))
            if wpm != self._wpm:
                self._wpm = wpm
                if self._command:
                    self._command(wpm)
        self._draw()
        self._tick_job = self.after(16, self._tick)

    # -- gambar -----------------------------------------------------------
    def _aa_oval(self, cx, cy, rx, ry, fill, steps=4, outline=None):
        """Lingkaran ANTIALIAS: cincin konsentris dari tepi blended menuju
        warna penuh - tepi halus, bukan gigi pixel keras."""
        for i in range(steps, 0, -1):
            t = i / (steps + 1)
            warna = _blend(self._bg, fill, 1.0 - t)
            self.create_oval(cx - rx * (1 + t * 0.9), cy - ry * (1 + t * 0.9),
                             cx + rx * (1 + t * 0.9), cy + ry * (1 + t * 0.9),
                             fill=warna, width=0)
        self.create_oval(cx - rx, cy - ry, cx + rx, cy + ry,
                         fill=fill, width=0, outline=outline or fill)

    def _draw(self):
        self.delete("all")
        w = max(60, self.winfo_width() or 430)
        x0, x1 = 16, w - 16
        y = self._rail_y
        rail_h = 16          # tebal: terasa 'glass channel', bukan garis
        rail = _blend(self._bg, "#ffffff", 0.07)
        rail_hi = _blend(self._bg, "#ffffff", 0.13)
        # bayangan rail lembut di bawahnya
        sh = _blend(self._bg, "#000000", 0.30)
        self.create_rectangle(x0 + 2, y + rail_h // 2 + 1, x1 - 2,
                              y + rail_h // 2 + 5, fill=sh, width=0)
        # rail dasar (tebal) + ujung bulat + garis highlight atas utk depth
        self.create_rectangle(x0, y - rail_h // 2, x1, y + rail_h // 2,
                              fill=rail, width=0)
        self.create_oval(x0 - rail_h // 2, y - rail_h // 2,
                         x0 + rail_h // 2, y + rail_h // 2, fill=rail, width=0)
        self.create_oval(x1 - rail_h // 2, y - rail_h // 2,
                         x1 + rail_h // 2, y + rail_h // 2, fill=rail, width=0)
        self.create_rectangle(x0 + 3, y - rail_h // 2 + 1, x1 - 3,
                              y - rail_h // 2 + 4, fill=rail_hi, width=0)
        # isian accent sampai thumb (ujung bulat juga) + pendar di ujung
        xt = max(x0, min(self._x, x1))
        if xt > x0 + 6:
            self.create_rectangle(x0, y - rail_h // 2, xt, y + rail_h // 2,
                                  fill=ACCENT, width=0)
            self.create_oval(x0 - rail_h // 2, y - rail_h // 2,
                             x0 + rail_h // 2, y + rail_h // 2,
                             fill=ACCENT, width=0)
            self.create_rectangle(x0 + 3, y - rail_h // 2 + 1, xt - 1,
                                  y - rail_h // 2 + 4,
                                  fill=_blend(ACCENT, "#ffffff", 0.25),
                                  width=0)
            self.create_oval(xt - 10, y - rail_h // 2, xt + 2,
                             y + rail_h // 2, fill=_blend(ACCENT, "#ffffff",
                                                          0.35),
                             width=0, stipple="gray50")
        # tick tier + label (angka disembunyikan bila tertutup thumb -
        # nilainya sudah tampil di readout kanan atas)
        for _nama, wpm in self._tiers:
            tx = self._x_for(wpm)
            lewat = wpm <= self._wpm
            self.create_rectangle(tx - 1, y - rail_h // 2 - 6,
                                  tx + 1, y - rail_h // 2 - 2,
                                  fill=ACCENT if lewat else FAINT, width=0)
            if abs(tx - xt) < 26:
                continue
            self.create_text(tx, y + rail_h // 2 + 12, text=str(wpm),
                             font=("Segoe UI", 8, "bold"),
                             fill=FG if wpm == self._wpm else FAINT)
        # ---- thumb kaca: bayangan, badan frosted, rim, sheen, specular --
        kecepatan = abs(self._v) if not self._drag else min(abs(self._v), 40.0)
        squash = min(0.30, self._pulse * 0.16)          # denyut mendarat
        sx = 1.0 + min(0.35, kecepatan * 0.012) + squash * 0.6
        sy = max(0.70, 1.0 / sx) - squash * 0.4
        r = 14 if (self._hover or self._drag) else 13
        b_shadow = _blend(self._bg, "#000000", 0.38)
        for extra, t in ((7, 0.14), (4, 0.26)):
            self._aa_oval(xt, y + 6 + extra * 0.4, (r + extra) * sx,
                          (r + extra) * 0.5, _blend(self._bg, b_shadow, t),
                          steps=2)
        # badan: frosted glass = campuran terang transparan di atas gelap
        kaca = _blend(self._bg, "#dfe4ec", 0.58)
        self._aa_oval(xt, y, r * sx, r * sy, kaca, steps=4)
        # bayangan dalam bawah (kesan ketebalan kaca)
        self.create_oval(xt - r * sx * 0.8, y - r * sy * 0.75,
                         xt + r * sx * 0.8, y + r * sy * 1.05,
                         fill=_blend(kaca, "#000000", 0.22), width=0,
                         stipple="gray25")
        # sheen atas: half-oval lebih terang (pantulan cahaya langit-langit)
        self.create_oval(xt - r * sx * 0.82, y - r * sy * 1.02,
                         xt + r * sx * 0.82, y + r * sy * 0.1,
                         fill=_blend(kaca, "#ffffff", 0.5), width=0,
                         stipple="gray50")
        # rim terang: tepi kaca memantulkan cahaya
        self.create_oval(xt - r * sx, y - r * sy, xt + r * sx, y + r * sy,
                         outline=_blend(self._bg, "#ffffff", 0.62), width=2)
        # specular kecil kiri-atas: titik kilau
        self.create_oval(xt - r * sx * 0.62, y - r * sy * 0.72,
                         xt - r * sx * 0.22, y - r * sy * 0.32,
                         fill="#ffffff", width=0, stipple="gray25")
        # titik pusat accent: kesan presisi di tengah tetesan
        self.create_oval(xt - 2, y - 2, xt + 2, y + 2,
                         fill=_blend(ACCENT, "#ffffff", 0.15), width=0)
# ------------------------------------------------------------- dial kecepatan
import math as _math

try:
    from PIL import Image as _PImage, ImageDraw as _PDraw, ImageTk as _PImageTk
    _PIL_OK = True
except Exception:
    _PIL_OK = False

_ARC_1 = "#7db4ff"      # arc: ujung awal (biru terang)
_ARC_2 = "#1d3fb8"      # arc: mendekati thumb (biru gelap pekat)
_ARC_W = 15             # tebal arc (px tampilan)
_DIAL_MAGIC = "#010203"  # warna ajaib utk sudut kartu benar2 transparan


def _rgb(hexs, a=255):
    return (int(hexs[1:3], 16), int(hexs[3:5], 16), int(hexs[5:7], 16), a)


def _blend_rgb(h1, h2, t):
    r1, g1, b1 = (int(h1[i:i + 2], 16) for i in (1, 3, 5))
    r2, g2, b2 = (int(h2[i:i + 2], 16) for i in (1, 3, 5))
    return (round(r1 + (r2 - r1) * t), round(g1 + (g2 - g1) * t),
            round(b1 + (b2 - b1) * t), 255)


class SpeedDial(tk.Toplevel):
    """Popup dial kecepatan ala kontrol 'pod'.

    PERILAKU POPUP (keluhan live: kotak hitam ngambang di atas app lain
    & tak bisa diklik): ini popup MILIK app - muncul di atas jendela app,
    tapi begitu app kehilangan fokus (user pindah ke app lain / minimi-
    mize / klik halaman web) dia LANGSUNG menutup. Tanpa grab global
    (dulu semua klik di layar diculik popup -> terasa 'uninteractable').

    Dirender dengan PIL SUPER-SAMPLE lalu di-downsample -> halus; kartu
    membulat di atas _DIAL_MAGIC + attributes('-transparentcolor') ->
    sudut benar2 tembus pandang (bukan kotak lagi). Tk hanya menggambar
    teks (angka + wpm) supaya tetap tajam.

    - lingkaran tengah putih: ANGKA wpm sekarang + label 'wpm'
    - cincin titik tier; titik yang dilewati menyala biru
    - arc biru gradasi + thumb putih glow; seret = thumb IKUT kursor
      1:1 (tanpa spring/fisika - keluhan user: kadang terlalu sensitif,
      kadang diam lalu melompat), nilai live ke engine; lepas = langsung
      nempel tier terdekat, TANPA pantulan
    """

    def __init__(self, master, tiers, value, command=None, released=None):
        super().__init__(master, bg=_DIAL_MAGIC)
        self.overrideredirect(True)
        self.transient(master.winfo_toplevel())
        try:
            self.attributes("-transparentcolor", _DIAL_MAGIC)
        except Exception:
            pass
        self._tiers = sorted(list(tiers), key=lambda t: t[1])
        self._command = command
        self._released = released
        self._wpm = int(value)
        self._ang = self._a_for(self._wpm)
        self._target_ang = self._ang
        self._drag = False
        self._last_pointer = None
        self._pernah_fokus = False   # app pernah pegang fokus OS?
        self._lahir = _time_monotonic()
        S = self._S = 300
        self._SS = 2                       # super-sample utk PIL
        kan = self._kan = tk.Canvas(self, width=S, height=S,
                                    bg=_DIAL_MAGIC, highlightthickness=0)
        kan.pack()
        self.bind("<Escape>", lambda e: self.tutup())
        kan.bind("<Button-1>", self._on_down)
        kan.bind("<B1-Motion>", self._on_move)
        kan.bind("<ButtonRelease-1>", self._on_up)
        # app kehilangan fokus -> popup nutup (jangan menghantui app lain)
        root = master.winfo_toplevel()
        self._fo_id = root.bind("<FocusOut>", self._root_keluar, add="+")
        self._fi_id = root.bind("<FocusIn>", self._root_fokus, add="+")
        # PENGAWAS FOREGROUND DETERMINISTIK: event FocusOut kadang tidak
        # sampai (keluhan live: dial menggantung di atas app lain) - poling
        # GetForegroundWindow tiap 300ms lebih bisa diandalkan. Sah: root
        # app, dial sendiri, atau jendela milik app (owner chain).
        self._root_hwnd = 0
        self._fg_ever = False
        self._fokus_job = self.after(400, self._jaga_fg)

        if _PIL_OK:
            self._base_big = self._render_base()
            self._img_base = self._to_photo(self._base_big)
            kan.create_image(0, 0, image=self._img_base, anchor="nw")
            self._img_dyn = None
            self._dyn_item = kan.create_image(0, 0, anchor="nw")
        self._t_num = kan.create_text(0, 0, text=str(self._wpm),
                                      font=("Segoe UI", 44, "bold"),
                                      fill="#161821", state="hidden")
        self._t_unit = kan.create_text(0, 0, text="wpm",
                                       font=("Segoe UI", 12, "bold"),
                                       fill="#9a9eaa", state="hidden")
        self._pos_text()

        # posisi: tepat di bawah chip pemanggil, dijepit dalam layar
        try:
            x = master.winfo_rootx() + master.winfo_width() // 2 - S // 2
            y = master.winfo_rooty() + master.winfo_height() + 10
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            x = max(8, min(x, sw - S - 8))
            y = max(8, min(y, sh - S - 60))
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass
        # popup milik app harus tetap di atas app (quirk overrideredirect:
        # kadang muncul DI BELAKANG owner) - aman karena FocusOut menutup
        try:
            self.attributes("-topmost", True)
            self.lift()
        except Exception:
            pass
        self._gambar()

    # -- api --------------------------------------------------------------
    def tutup(self):
        try:
            self.after_cancel(self._fokus_job)
        except Exception:
            pass
        try:
            root = self.master.winfo_toplevel()
            root.unbind("<FocusOut>", self._fo_id)
            root.unbind("<FocusIn>", self._fi_id)
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass

    def set_wpm(self, wpm):
        self._wpm = int(wpm)
        self._ang = self._target_ang = self._a_for(self._wpm)
        self._gambar()

    def _root_fokus(self, _e):
        self._pernah_fokus = True

    def _jaga_fg(self):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        try:
            import ctypes
            u32 = ctypes.windll.user32
            if not self._root_hwnd:
                self._root_hwnd = u32.GetAncestor(
                    self.master.winfo_toplevel().winfo_id(), 2)  # GA_ROOT
            # klik BARU (bit 0x0001 GetAsyncKeyState = ditekan sejak
            # panggilan terakhir) & kursor di luar kartu = user klik
            # halaman/app di luar dial -> tutup. CARA INI TAK TERGANTUNG
            # FOKUS: klik webview ternyata TIDAK selalu memindahkan fokus
            # keyboard Win32 (Chromium menunda) - cek GetGUIThreadInfo
            # gagal bekerja (keluhan user: dial tetap terbuka). Polling
            # 120ms supaya klik pendek tidak terlewat. PANGGIL SELALU
            # (menghabiskan bit tepi) tapi baru BERTINDAK setelah grace
            # 0.6 dtk - klik pembuka chip menyisakan bit tepi yang belum
            # habis dipakai saat poll pertama; kalau poll melewatkannya
            # (grace lama), bit itu hidup sampai poll pasca-grace dan
            # dial bunuh diri seusir lahir (live!).
            pt = wintypes.POINT()
            lahir_lama = _time_monotonic() - self._lahir >= 0.6
            for vk in (0x01, 0x02):   # VK_LBUTTON, VK_RBUTTON
                if u32.GetAsyncKeyState(vk) & 0x0001:
                    if not lahir_lama:
                        continue
                    u32.GetCursorPos(ctypes.byref(pt))
                    x0 = self.winfo_rootx() - 6
                    y0 = self.winfo_rooty() - 6
                    x1 = x0 + self.winfo_width() + 12
                    y1 = y0 + self.winfo_height() + 12
                    if not (x0 <= pt.x <= x1 and y0 <= pt.y <= y1):
                        self.tutup()
                        return
            fg = u32.GetForegroundWindow()
            if fg:
                if fg in (self._root_hwnd, self.winfo_id()):
                    self._fg_ever = True
                elif self._fg_ever and u32.GetWindow(fg, 4) != self._root_hwnd:
                    self.tutup()      # app lain pegang foreground
                    return
        except Exception:
            pass
        self._fokus_job = self.after(120, self._jaga_fg)

    def _root_keluar(self, _e):
        # tunda sedikit: fokus bisa 'berkedip' saat popup baru lahir;
        # klik ke halaman web / app lain = FocusOut -> tutup rapih.
        # TANPA pernah fokus (mis. jendela di latar) jangan tutup -
        # dulu dial langsung mati sendiri saat di-probe dari latar.
        if not self._pernah_fokus:
            return
        if _time_monotonic() - self._lahir < 0.25:
            return
        try:
            self.after(120, lambda: (self.winfo_exists()
                                     and self._keluar_benar()))
        except Exception:
            pass

    def _keluar_benar(self):
        try:
            fokus = self.master.winfo_toplevel().focus_get()
        except Exception:
            fokus = None
        if fokus is None or not str(fokus).startswith(str(self)):
            self.tutup()

    # -- geometri ---------------------------------------------------------
    @property
    def _cx(self):
        return self._S / 2

    @property
    def _cy(self):
        return self._S / 2

    @property
    def _r_ring(self):
        return 112

    @property
    def _r_plate(self):
        return 78

    def _a_for(self, wpm):
        lo, hi = self._tiers[0][1], self._tiers[-1][1]
        f = (wpm - lo) / max(1, hi - lo)
        return 135 + f * 270.0        # 135deg (kiri-bawah) -> 405deg

    def _wpm_for(self, ang):
        lo, hi = self._tiers[0][1], self._tiers[-1][1]
        f = max(0.0, min(1.0, (ang - 135) / 270.0))
        return lo + f * (hi - lo)

    def _xy(self, ang, r):
        rad = _math.radians(ang)
        return self._cx + r * _math.cos(rad), self._cx + r * _math.sin(rad)

    def _pos_text(self):
        cx = self._cx
        self._kan.coords(self._t_num, cx, cx - 12)
        self._kan.coords(self._t_unit, cx, cx + 36)
        self._kan.itemconfigure(self._t_num, state="normal")
        self._kan.itemconfigure(self._t_unit, state="normal")

    # -- interaksi --------------------------------------------------------
    def _pointer_raw(self, x, y):
        """Sudut pointer mentah 0..360 (tanpa koreksi gap)."""
        return _math.degrees(_math.atan2(y - self._cy, x - self._cx)) % 360.0

    def _angle_of(self, x, y):
        """Sudut pointer -> sweep [135,405]; celah bawah dijepit ke ujung
        TERDEKAT (dulu arahnya kebalik: klik di bawah thumb yang dekat
        ujung malah mendarat di ujung lawan -> '85 bam teleport 300').
        Dipakai saat TEKAN/balik ke jalur: nilai pindah ke titik kursor."""
        a = self._pointer_raw(x, y)
        if 45.0 < a < 135.0:                 # di celah: ujung terdekat
            return 405.0 if a <= 90.0 else 135.0
        if a < 45.0:
            a += 360.0                       # segmen atas = ekor sweep
        return min(405.0, max(135.0, a))

    def _dalam_jalur(self, e):
        """Kursor di jalur cincin (donut di sekitar arc)?"""
        r = _math.hypot(e.x - self._cx, e.y - self._cy)
        return self._r_ring - 32 <= r <= self._r_ring + 34

    def _on_down(self, e):
        r = _math.hypot(e.x - self._cx, e.y - self._cy)
        if r > self._r_ring + 40:
            self.tutup()          # klik jauh di luar dial = tutup
            return
        if not self._dalam_jalur(e):
            return                # piringan/badan kartu: bukan area drag
        self._drag = True
        self._last_pointer = self._pointer_raw(e.x, e.y)
        # tekan DI jalur: nilai langsung pindah persis ke titik kursor
        # (keluhan user: dulu nilai tidak sesuai posisi kursor)
        self._ke(self._angle_of(e.x, e.y))

    def _on_move(self, e):
        if not self._drag:
            return
        if not self._dalam_jalur(e):
            # keluar jalur: TANGGU saja, JANGAN matikan drag (keluhan
            # user: harus lepas-tahan lagi). Nilai beku sampai kursor
            # balik ke jalur - motion di luar tak berefek apa-apa.
            self._last_pointer = None
            return
        raw = self._pointer_raw(e.x, e.y)
        if self._last_pointer is None:
            # BALIK ke jalur saat masih menahan: nilai langsung nempel
            # kursor (jangan lanjut delta lama - posisi lama tak relevan)
            self._last_pointer = raw
            self._ke(self._angle_of(e.x, e.y))
            return
        # dial ROTARY SEJATI: akumulasi DELTA sudut kecil, bukan sudut
        # absolut. Dulu pemetaan absolut + celah bawah bikin nilai melompat
        # 296->85 / 85->300 saat kursor nyabrang celah. Dengan delta
        # (+normalisasi wrap 180) tidak ada teleport; ujung dijepit.
        delta = raw - self._last_pointer
        if delta > 180.0:
            delta -= 360.0
        elif delta < -180.0:
            delta += 360.0
        self._last_pointer = raw
        self._ke(min(405.0, max(135.0, self._ang + delta)))

    def _ke(self, ang):
        """Langsung 1:1: thumb persis di sudut kursor, tanpa animasi."""
        self._ang = self._target_ang = ang
        wpm = int(round(self._wpm_for(ang)))
        if wpm != self._wpm:
            self._wpm = wpm
            if self._command:
                self._command(wpm)
        self._gambar()

    def _on_up(self, _e):
        self._lepas()

    def _lepas(self):
        """Akhiri seretan: nempel tier terdekat SEKALI, tanpa pantulan."""
        if not self._drag:
            return
        self._drag = False
        self._last_pointer = None
        terdekat = min(self._tiers, key=lambda t: abs(t[1] - self._wpm))
        self._wpm = terdekat[1]
        self._ang = self._target_ang = self._a_for(self._wpm)
        if self._released:
            self._released(self._wpm)
        self._gambar()

    # -- render PIL ---------------------------------------------------------
    def _to_photo(self, img_big):
        img = img_big.resize((self._S, self._S), _PImage.LANCZOS)
        # komposit di atas warna ajaib -> piksel sudut PERSIS magic maka
        # '-transparentcolor' membuatnya tembus pandang (kartu membulat)
        latar = _PImage.new("RGB", img.size, _rgb(_DIAL_MAGIC)[:3])
        latar.paste(img, (0, 0), img)
        return _PImageTk.PhotoImage(latar, master=self)

    def _render_base(self):
        """Lapisan statis: kartu membulat + piringan + titik tier (sekali)."""
        ss = self._SS
        img = _PImage.new("RGBA", (self._S * ss, self._S * ss), (0, 0, 0, 0))
        d = _PDraw.Draw(img)
        S = self._S * ss
        # kartu popup membulat (bukan kotak; sudut dibereskan transparentcolor)
        d.rounded_rectangle([ss, ss, S - ss, S - ss], radius=26 * ss,
                            fill=(23, 25, 33, 255),
                            outline=(56, 61, 78, 255), width=ss)
        c = self._cx * ss

        def ell(r, fill):
            d.ellipse([c - r * ss, c - r * ss, c + r * ss, c + r * ss],
                      fill=fill)

        ell(130, (35, 37, 46, 255))          # piringan
        ell(122, (42, 45, 56, 255))          # bibir dalam
        ell(80, (255, 255, 255, 255))        # pelat nilai putih
        d.ellipse([c - 78 * ss, c - 78 * ss, c + 78 * ss, c + 78 * ss],
                  outline=(228, 230, 238, 255), width=ss)
        for _n, wpm in self._tiers:
            a = self._a_for(wpm)
            rad = _math.radians(a)
            x = c + self._r_ring * ss * _math.cos(rad)
            y = c + self._r_ring * ss * _math.sin(rad)
            d.ellipse([x - 2 * ss, y - 2 * ss, x + 2 * ss, y + 2 * ss],
                      fill=(96, 100, 114, 255))
        return img

    def _render_dyn(self):
        """Lapisan dinamis (RGBA transparan): arc + titik menyala + glow
        + thumb. Digambar di resolusi super-sample lalu ditekan halus."""
        ss = self._SS
        img = _PImage.new("RGBA", (self._S * ss, self._S * ss), (0, 0, 0, 0))
        d = _PDraw.Draw(img)
        c = self._cx * ss
        a0, a1 = 135.0, self._ang
        w = _ARC_W * ss
        bbox = [c - self._r_ring * ss - w / 2, c - self._r_ring * ss - w / 2,
                c + self._r_ring * ss + w / 2, c + self._r_ring * ss + w / 2]
        if a1 > a0 + 1:
            n = max(2, int((a1 - a0) / 9))
            for i in range(n):
                s0 = a0 + (a1 - a0) * i / n
                s1 = a0 + (a1 - a0) * (i + 1) / n + 0.6   # tumpang utk mulus
                t = (s0 - 135) / 270.0
                col = _blend_rgb(_ARC_1, _ARC_2, min(1.0, t * 1.12))
                d.arc(bbox, s0, s1, fill=col, width=int(w))
        # titik tier menyala (yang sudah dilewati / aktif)
        for _n, wpm in self._tiers:
            a = self._a_for(wpm)
            if a > a1 + 0.5:
                continue
            rad = _math.radians(a)
            x = c + self._r_ring * ss * _math.cos(rad)
            y = c + self._r_ring * ss * _math.sin(rad)
            aktif = wpm == self._wpm
            r = (4.5 if aktif else 3) * ss
            col = _rgb(_ARC_2 if wpm == self._tiers[-1][1] else _ARC_1)
            d.ellipse([x - r, y - r, x + r, y + r], fill=col)
        # thumb: glow konsentris + butir putih (tanpa squash pantulan)
        rad = _math.radians(a1)
        xt = c + self._r_ring * ss * _math.cos(rad)
        yt = c + self._r_ring * ss * _math.sin(rad)
        r_th = 17 * ss
        for i in range(6, 0, -1):
            gr = (r_th + 3 + i * 2.2 * ss)
            alpha = int(70 * (1 - i / 7))
            d.ellipse([xt - gr, yt - gr, xt + gr, yt + gr],
                      fill=(29, 63, 184, alpha))
        d.ellipse([xt - r_th - 2 * ss, yt - r_th - 2 * ss,
                   xt + r_th + 2 * ss, yt + r_th + 2 * ss],
                  fill=(125, 180, 255, 255))
        d.ellipse([xt - r_th, yt - r_th, xt + r_th, yt + r_th],
                  fill=(255, 255, 255, 255))
        out = self._base_big.copy()
        out.alpha_composite(img)
        return out

    def _gambar(self):
        if not _PIL_OK:
            return
        try:
            self._img_dyn = self._to_photo(self._render_dyn())
            self._kan.itemconfigure(self._dyn_item, image=self._img_dyn)
            self._kan.itemconfigure(self._t_num, text=str(self._wpm))
        except Exception:
            pass


def _time_monotonic():
    import time
    return time.monotonic()
