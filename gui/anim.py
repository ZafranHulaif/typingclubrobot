"""Animasi kanvas ringan ala produk besar: sprite PIL (glow lembut,
antialias via supersample + LANCZOS) digerakkan oleh loop berbasis
jam dinding.

Kecepatan gerak dihitung dari selisih waktu (perf_counter), BUKAN
jumlah frame, jadi di layar 60/120/144 Hz gerakannya sama cepat dan
sama mulus - timer Tk hanya memicu render, posisi selalu dihitung
ulang dari waktu sekarang.

Latar sprite sengaja DIBAKAR warna PANEL (bukan transparan): kanvas
tinggal menempelkan gambar, tidak bergantung dukungan alpha Tk.
"""

import io
import math
import time
import tkinter as tk

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .theme import ACCENT, GREEN, PANEL, YELLOW


def _rgb(warna):
    return tuple(int(warna[i:i + 2], 16) for i in (1, 3, 5))


def _cerah(warna, k):
    """Campur warna ke putih sebesar k (inti orb biar menyala)."""
    r, g, b = _rgb(warna)
    return (int(r + (255 - r) * k), int(g + (255 - g) * k),
            int(b + (255 - b) * k))


class TimedLoop:
    """Panggil fn(detik_sejak_mulai) tiap tik; gerak berbasis waktu.
    Berhenti sendiri saat widget hancur (after -> TclError), dan skip
    menggambar saat widget belum terlihat supaya hemat CPU."""

    def __init__(self, widget, step_ms=8):
        self._w = widget
        self._step = max(1, int(step_ms))
        self._fn = None
        self._t0 = time.perf_counter()
        self._id = None
        self._hidup = False

    def start(self, fn):
        self._fn = fn
        self._t0 = time.perf_counter()
        self._hidup = True
        self._tik()
        return self

    def stop(self):
        self._hidup = False
        if self._id is not None:
            try:
                self._w.after_cancel(self._id)
            except Exception:
                pass
            self._id = None

    def _tik(self):
        if not self._hidup:
            return
        try:
            if self._fn is not None and self._w.winfo_ismapped():
                self._fn(time.perf_counter() - self._t0)
        except tk.TclError:
            return
        try:
            self._id = self._w.after(self._step, self._tik)
        except tk.TclError:
            pass


# ------------------------------------------------------------ sprite: orb

_cache_orb = {}


def orb_sprite(warna, diameter=96, core=8, halo=2.6, sup=4):
    """Orb bercahaya: inti pekat + halo blur menyatu ke PANEL.
    Dirender sekali (cache) dengan supersample lalu diperkecil -
    tepinya halus, jauh lebih lembut dari oval kanvas mentah."""
    kunci = (warna, diameter, core, halo)
    if kunci in _cache_orb:
        return _cache_orb[kunci]
    S = diameter * sup
    R = S // 2
    im = Image.new("RGB", (S, S), _rgb(PANEL))
    dr = ImageDraw.Draw(im)
    h = core * sup * halo
    dr.ellipse([R - h, R - h, R + h, R + h], fill=_rgb(warna))
    c = core * sup
    dr.ellipse([R - c, R - c, R + c, R + c], fill=_cerah(warna, 0.35))
    im = im.filter(ImageFilter.GaussianBlur(core * sup * 1.5))
    im = im.resize((diameter, diameter), Image.LANCZOS)
    bio = io.BytesIO()
    im.save(bio, format="PNG")
    data = bio.getvalue()
    _cache_orb[kunci] = data
    return data


# ------------------------------------------------------- lapangan orb melayang

class OrbsField:
    """2-3 orb warna merekah pelan ala screensaver Google TV: gerak
    sinus ganda (tidak pernah memantul mendadak), amplitudo relatif
    ukuran kanvas - aman saat dialog diubah ukurannya."""

    DEF = [
        # (warna, diameter, inti, titik_x, titik_y, periode_x, periode_y, fase)
        (ACCENT, 96, 8, 0.30, 0.46, 19.0, 23.0, 0.0),
        (GREEN, 72, 6, 0.72, 0.34, 13.0, 17.0, 2.1),
        (YELLOW, 84, 7, 0.52, 0.70, 21.0, 15.0, 4.2),
    ]

    def __init__(self, kanvas, tinggi=None, daftar=None):
        self.kanvas = kanvas
        self._def = daftar or self.DEF
        self._img = []
        self._item = []
        for (warna, d, core, *_rest) in self._def:
            foto = tk.PhotoImage(data=orb_sprite(warna, d, core))
            self._img.append(foto)
            self._item.append(kanvas.create_image(0, 0, image=foto,
                                                  anchor="c"))
        # amplitudo relatif: orb boleh sedikit keluar tepi (dipotong
        # kanvas) supaya komposisinya lapang, bukan kotak kaku
        self._amp = [(0.30, 0.22), (0.22, 0.16), (0.26, 0.18)]
        self.loop = TimedLoop(kanvas)
        if tinggi:
            kanvas.configure(height=tinggi)

    def start(self):
        self.loop.start(self._frame)
        return self

    def _frame(self, t):
        w = max(self.kanvas.winfo_width(), 300)
        h = max(self.kanvas.winfo_height(), 60)
        for i, (warna, d, core, px, py, Tx, Ty, fase) in enumerate(self._def):
            ax, ay = self._amp[min(i, len(self._amp) - 1)]
            x = px * w + ax * w * math.sin(2 * math.pi * t / Tx + fase)
            y = py * h + ay * h * math.sin(2 * math.pi * t / Ty + fase * 1.7)
            self.kanvas.coords(self._item[i], x, y)

    def stop(self):
        self.loop.stop()


def attach_orbs(kanvas, tinggi=76):
    """Pasang lapangan orb pada kanvas; kembalikan pengendali.
    tinggi=None berarti jangan sentuh tinggi kanvas (pratinjau).
    Simpan referensinya (mis. d._orbs) agar tidak tersapu GC."""
    return OrbsField(kanvas, tinggi).start()


# ------------------------------------------------------------ sprite: centang

_cache_cek = {}


def check_sprite(warna, progres, ukuran=96, sup=3):
    """Satu frame centang progres 0..1: cincin menyapu lalu centang
    'menggambar' sendiri (efek tulis-tangan). Ukuran jari-jari/tebal
    relatif; render tajam + salinan blur sebagai glow di bawahnya."""
    S = ukuran * sup
    c = S // 2
    r = int(S * 0.34)
    tebal = max(3, int(S * 0.05))
    im = Image.new("RGB", (S, S), _rgb(PANEL))
    dr = ImageDraw.Draw(im)
    p = max(0.0, min(1.0, progres))
    e = 1 - (1 - p) ** 3                      # ease-out cubic
    sap = min(e / 0.7, 1.0)                   # fase cincin
    if sap > 0.02:
        dr.arc([c - r, c - r, c + r, c + r], -90, -90 + 359 * sap,
               fill=_rgb(warna), width=tebal)
    ck = max(0.0, (e - 0.55) / 0.45)          # fase centang
    if ck > 0.02:
        A = (c - r * 0.46, c + r * 0.06)
        B = (c - r * 0.08, c + r * 0.44)
        C = (c + r * 0.54, c - r * 0.34)
        total = math.dist(A, B) + math.dist(B, C)
        jalan = total * min(ck, 1.0)
        if jalan <= math.dist(A, B):
            k = jalan / math.dist(A, B)
            ujung = (A[0] + (B[0] - A[0]) * k, A[1] + (B[1] - A[1]) * k)
            dr.line([A, ujung], fill=_rgb(warna), width=tebal)
        else:
            k = (jalan - math.dist(A, B)) / math.dist(B, C)
            ujung = (B[0] + (C[0] - B[0]) * k, B[1] + (C[1] - B[1]) * k)
            dr.line([A, B, ujung], fill=_rgb(warna), width=tebal)
    # glow: blur versi tajam, tempel tajam di atasnya
    glow = im.filter(ImageFilter.GaussianBlur(int(S * 0.028)))
    maska = ImageChops.difference(im, Image.new("RGB", (S, S), _rgb(PANEL)))
    maska = maska.convert("L").point(lambda v: 255 if v > 12 else 0)
    glow.paste(im, (0, 0), maska)
    im = glow.resize((ukuran, ukuran), Image.LANCZOS)
    bio = io.BytesIO()
    im.save(bio, format="PNG")
    return bio.getvalue()


def check_frames(warna=GREEN, ukuran=96, jumlah=26):
    kunci = (warna, ukuran, jumlah)
    if kunci in _cache_cek:
        return _cache_cek[kunci]
    foto = [tk.PhotoImage(data=check_sprite(warna, i / (jumlah - 1), ukuran))
            for i in range(jumlah)]
    _cache_cek[kunci] = foto
    return foto


class PlayCheck:
    """Putar animasi centang di tengah kanvas lalu panggil done().
    Indeks frame dihitung dari jam (bukan hitungan tik) sehingga
    durasinya presisi di refresh rate apa pun."""

    def __init__(self, kanvas, warna=GREEN, ukuran=96, durasi=1.0,
                 done=None):
        self.kanvas = kanvas
        self._frames = check_frames(warna, ukuran)
        self._durasi = durasi
        self._done = done
        self._item = None
        self.loop = TimedLoop(kanvas)

    def start(self):
        self._item = self.kanvas.create_image(0, 0,
                                              image=self._frames[0],
                                              anchor="c")
        self.loop.start(self._frame)
        return self

    def _frame(self, t):
        # pusat dihitung tiap frame: kanvas melebar setelah di-pack
        # (fill="x") - kalau sekali di awal, centang berakhir di kiri
        try:
            self.kanvas.coords(
                self._item,
                max(self.kanvas.winfo_width(), 200) // 2,
                max(self.kanvas.winfo_height(), 120) // 2)
        except tk.TclError:
            self.loop.stop()
            return
        if t >= self._durasi:
            self.kanvas.itemconfigure(self._item, image=self._frames[-1])
            self.loop.stop()
            if self._done is not None:
                try:
                    self._done()
                except Exception:
                    pass
            return
        idx = int(len(self._frames) * t / self._durasi)
        self.kanvas.itemconfigure(self._item, image=self._frames[idx])

    def stop(self):
        self.loop.stop()
