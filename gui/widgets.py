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
        # sembunyikan sampai show() selesai memosisikan: tanpa ini dialog
        # sempat terlihat sekejap di posisi default WM, dan -topmost yang
        # dipasang saat jendela belum terpetakan MEMAKSA posisi (0,0)
        # (bug Windows: popup menumpuk di pojok kiri atas).
        self.withdraw()
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



# ------------------------------------------------------------ slider modern
def _blend(c1, c2, t):
    """Campur dua warna hex (#rrggbb), t=0 -> c1, t=1 -> c2."""
    r1, g1, b1 = (int(c1[i:i + 2], 16) for i in (1, 3, 5))
    r2, g2, b2 = (int(c2[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % (
        round(r1 + (r2 - r1) * t), round(g1 + (g2 - g1) * t),
        round(b1 + (b2 - b1) * t))


class SpeedSlider(tk.Canvas):
    """Slider kecepatan berbasis Canvas - halus, tebal, anti-pixel.

    Tampak & rasa (permintaan user: 'simple tapi detail terkecil
    diperhatikan'):
    - rail tebal dengan bayangan halus, isian accent, tick tier berlabel.
    - thumb bulat ANTIALIAS (lingkaran konsentris blended, bukan satu
      oval keras) + bayangan lembut + SQUASH & STRETCH mengikuti
      kecepatan gerak (rasa fisik: ditarik cepat memanjang, mantul
      saat mendarat).
    - drag = nilai halus mengalir (command per wpm berubah, engine ikut
      live). Lepas = spring menuju tick terdekat DENGAN overshoot kecil
      (bukan snap instan). set_wpm() dari luar juga menganimasi spring.
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
        # posisi thumb (px canvas), velocity, dan target utk spring
        self._x = 0.0
        self._v = 0.0
        self._target_x = 0.0
        self._drag = False
        self._hover = False
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
        self._x = float(e.x)
        self._target_x = self._x
        self._live()

    def _on_move(self, e):
        if self._drag:
            self._v = e.x - self._x       # kecepatan pointer utk squash
            self._x = float(e.x)
            self._target_x = self._x
            self._live()

    def _on_up(self, _e):
        self._drag = False
        # tick terdekat jadi target; spring mengantar dengan bounce kecil
        nearest = min(self._tiers,
                      key=lambda t: abs(self._x_for(t[1]) - self._x))
        self._wpm = nearest[1]
        self._target_x = self._x_for(self._wpm)
        self._start_tick()
        if self._released:
            self._released(self._wpm)

    def _live(self):
        """Saat drag: nilai halus mengalir + gambar real-time."""
        wpm = int(round(max(self._tiers[0][1],
                            min(self._tiers[-1][1], self._wpm_for(self._x)))))
        if wpm != self._wpm:
            self._wpm = wpm
            if self._command:
                self._command(wpm)
        self._draw()

    # -- spring physics ---------------------------------------------------
    def _snap_now(self):
        """Posisikan thumb langsung (awal/resize) tanpa animasi."""
        self._x = self._target_x = self._x_for(self._wpm)
        self._v = 0.0
        self._draw()

    def _start_tick(self):
        if self._tick_job is None:
            self._tick()

    def _tick(self):
        # spring teredam: masih ada overshoot kecil (bounce alami)
        k, c = 0.14, 0.74
        self._v += k * (self._target_x - self._x) - c * self._v
        self._x += self._v
        if abs(self._target_x - self._x) < 0.3 and abs(self._v) < 0.05:
            self._x = self._target_x
            self._v = 0.0
            self._tick_job = None
            self._draw()
            return
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
        rail_h = 10
        rail = _blend(self._bg, "#ffffff", 0.07)
        rail_hi = _blend(self._bg, "#ffffff", 0.13)
        # bayangan rail lembut di bawahnya
        sh = _blend(self._bg, "#000000", 0.30)
        self.create_rectangle(x0 + 2, y + rail_h // 2 + 1, x1 - 2,
                              y + rail_h // 2 + 4, fill=sh, width=0)
        # rail dasar (tebal) + ujung bulat + garis highlight atas utk depth
        self.create_rectangle(x0, y - rail_h // 2, x1, y + rail_h // 2,
                              fill=rail, width=0)
        self.create_oval(x0 - rail_h // 2, y - rail_h // 2,
                         x0 + rail_h // 2, y + rail_h // 2, fill=rail, width=0)
        self.create_oval(x1 - rail_h // 2, y - rail_h // 2,
                         x1 + rail_h // 2, y + rail_h // 2, fill=rail, width=0)
        self.create_rectangle(x0 + 3, y - rail_h // 2 + 1, x1 - 3,
                              y - rail_h // 2 + 3, fill=rail_hi, width=0)
        # isian accent sampai thumb (ujung bulat juga)
        xt = max(x0, min(self._x, x1))
        if xt > x0 + 6:
            self.create_rectangle(x0, y - rail_h // 2, xt, y + rail_h // 2,
                                  fill=ACCENT, width=0)
            self.create_oval(x0 - rail_h // 2, y - rail_h // 2,
                             x0 + rail_h // 2, y + rail_h // 2,
                             fill=ACCENT, width=0)
            self.create_rectangle(x0 + 3, y - rail_h // 2 + 1, xt - 1,
                                  y - rail_h // 2 + 3,
                                  fill=_blend(ACCENT, "#ffffff", 0.25),
                                  width=0)
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
            self.create_text(tx, y + rail_h // 2 + 10, text=str(wpm),
                             font=("Segoe UI", 8, "bold"),
                             fill=FG if wpm == self._wpm else FAINT)
        # thumb: bayangan lembut, lalu badan ANTIALIAS + squash & stretch
        kecepatan = abs(self._v) if not self._drag else min(abs(self._v), 40.0)
        sx = 1.0 + min(0.35, kecepatan * 0.012)
        sy = max(0.72, 1.0 / sx)
        r = 12 if (self._hover or self._drag) else 11
        b_shadow = _blend(self._bg, "#000000", 0.38)
        for extra, t in ((7, 0.14), (4, 0.26)):
            self._aa_oval(xt, y + 6 + extra * 0.4, r + extra,
                          (r + extra) * 0.5, _blend(self._bg, b_shadow, t),
                          steps=2)
        self._aa_oval(xt, y, r * sx, r * sy, "#f5f6f8", steps=4,
                      outline=ACCENT if (self._hover or self._drag) else rail)
        # titik pusat kecil: kesan presisi
        self.create_oval(xt - 2, y - 2, xt + 2, y + 2, fill=ACCENT, width=0)
