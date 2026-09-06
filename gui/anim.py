"""Animasi kanvas orisinal ala produk besar - TAJAM dan beresolusi
native: setiap frame dirender PIL pada ukuran pixel fisik kanvas
(aplikasi sudah DPI-aware, jadi otomatis 1:1 di layar 100%/125%/150%,
tanpa pensuspaan/peregangan), lalu supersample 2x supaya tepinya
bersih. Gerak dihitung dari jam dinding (perf_counter) - di layar
60/120/144 Hz kecepatannya persis sama.

Dua animasi, tema mengetik (khas aplikasi ini):
- WaveField : "gelombang ketikan" - deretan tombol yang diterangi
  berirama seperti jari mengetik, dengan kursor garis melangkah.
- PlayCheck : cincin tipis menyapu lalu centang menggambar sendiri.
"""

import math
import time
import tkinter as tk

from PIL import Image, ImageDraw

from .theme import ACCENT, CARD, EDGE, GREEN, PANEL


def _rgb(warna):
    return tuple(int(warna[i:i + 2], 16) for i in (1, 3, 5))


def _campur(a, b, k):
    """Warna a menuju b sebesar k (0..1)."""
    ka, kb = _rgb(a), _rgb(b)
    k = max(0.0, min(1.0, k))
    return tuple(int(ka[i] + (kb[i] - ka[i]) * k) for i in range(3))


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

    @property
    def hidup(self):
        return self._hidup

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


# ------------------------------------------------- gelombang ketikan

N_KUNCI = 7
KADENSI = 0.34          # detik antar ketikan
JEDA_AKHIR = 0.62       # jeda sebelum mengulang
NAIK = 0.10             # detik menyala penuh
LUNTUR = 0.30           # konstanta pelunturan cahaya
SUP = 2                 # supersample


def _durasi_loop():
    return N_KUNCI * KADENSI + JEDA_AKHIR


def _padam(k, t):
    """Terang kunci ke-k pada waktu t (0..1) - nyal cepat, luntur
    perlahan seperti tuts piano yang dilepas."""
    tk_ = k * KADENSI + 0.05 * math.sin(k * 7.3)
    u = (t - tk_) % _durasi_loop()
    naik = min(u / NAIK, 1.0)
    return naik * math.exp(-max(0.0, u - NAIK) / LUNTUR)


def _geometri(w, h):
    """Ukuran tuts + posisi awal, proporsional dan dipusatkan."""
    s = h * 0.50
    gap = h * 0.20
    total = N_KUNCI * s + (N_KUNCI - 1) * gap
    maks = w * 0.88
    if total > maks:
        k = maks / total
        s, gap, total = s * k, gap * k, maks
    x0 = (w - total) / 2
    y0 = (h - s) / 2 - h * 0.04
    return s, gap, x0, y0


def wave_sprite(w, h, t):
    """Satu frame gelombang ketikan pada waktu t, ukuran w x h pixel
    fisik. Semua elemen flat & tajam: tuts bersudut bulat, garis
    1-2px, kursor 2px - TANPA blur/glow. Tinggi desain dibatasi
    supaya di kanvas tinggi (pratinjau) tutsnya tetap proporsional."""
    W, H = w * SUP, h * SUP
    im = Image.new("RGB", (W, H), _rgb(PANEL))
    dr = ImageDraw.Draw(im)
    dh = min(h, 110)
    s, gap, x0, y0 = _geometri(w, dh)
    y0 += (h - dh) / 2
    s *= SUP
    gap *= SUP
    x0 *= SUP
    y0 *= SUP
    terang = []
    for k in range(N_KUNCI):
        terang.append(_padam(k, t))
    aktif = max(range(N_KUNCI), key=lambda k: terang[k])
    for k in range(N_KUNCI):
        b = terang[k]
        x = x0 + k * (s + gap)
        kotak = [x, y0, x + s, y0 + s]
        r = s * 0.20
        dr.rounded_rectangle(kotak, radius=r,
                             fill=_campur(CARD, ACCENT, 0.85 * b),
                             outline=_campur(EDGE, ACCENT, b),
                             width=max(1, int(SUP * max(1.0, h / 96))))
    # kursor garis di bawah tuts: melangkah ke tuts yang baru diketuk,
    # berkedip pelan saat semua diam (jeda akhir)
    dur = _durasi_loop()
    if t % dur > N_KUNCI * KADENSI + 0.05:
        # jeda akhir: kursor berkedip di tuts terakhir
        pos_k = N_KUNCI - 1
        nyala = (t % 0.8) < 0.5
    else:
        pos_k = aktif
        nyala = True
    cx = x0 + pos_k * (s + gap)
    cy = y0 + s + 0.10 * dh * SUP
    tebal = max(2, int(round(h * SUP / 48)))
    warna_kursor = _campur(EDGE, GREEN, 0.35 + 0.65 * terang[pos_k])
    if nyala:
        dr.rounded_rectangle([cx + s * 0.12, cy, cx + s * 0.88,
                              cy + tebal], radius=tebal / 2,
                             fill=warna_kursor)
    return _ke_photo(im, w, h)


def _ke_photo(im, w, h):
    import io
    im = im.resize((w, h), Image.LANCZOS)
    bio = io.BytesIO()
    im.save(bio, format="PNG")
    return bio.getvalue()


_cache_wave = {}


def wave_photos(w, h, jumlah=56):
    """Deretan frame satu loop penuh, di-cache per ukuran kanvas."""
    kunci = (w, h, jumlah)
    if kunci in _cache_wave:
        return _cache_wave[kunci]
    dur = _durasi_loop()
    foto = [tk.PhotoImage(data=wave_sprite(w, h, i * dur / jumlah))
            for i in range(jumlah)]
    _cache_wave[kunci] = foto
    return foto


class WaveField:
    """Satu item gambar selebar kanvas; frame dipilih dari jam sehingga
    ritmenya presisi. Jika ukuran kanvas berubah (jendela pratinjau
    di-resize), frame dirender ulang pada resolusi baru - selalu tajam."""

    def __init__(self, kanvas):
        self.kanvas = kanvas
        self._foto = None
        self._ukuran = (0, 0)
        self.item = kanvas.create_image(0, 0, anchor="nw")
        self.loop = TimedLoop(kanvas)

    def start(self):
        self.loop.start(self._frame)
        return self

    def _siapkan(self):
        w = max(self.kanvas.winfo_width(), 220)
        h = max(self.kanvas.winfo_height(), 48)
        if (w, h) != self._ukuran or self._foto is None:
            self._foto = wave_photos(w, h)
            self._ukuran = (w, h)
            self.kanvas.itemconfigure(self.item, image=self._foto[0])
        return w, h

    def _frame(self, t):
        w, h = self._siapkan()
        self.kanvas.coords(self.item, (w - self._ukuran[0]) // 2,
                           (h - self._ukuran[1]) // 2)
        dur = _durasi_loop()
        idx = int(len(self._foto) * (t % dur) / dur) % len(self._foto)
        self.kanvas.itemconfigure(self.item, image=self._foto[idx])

    def stop(self):
        self.loop.stop()


def attach_wave(kanvas):
    """Pasang gelombang ketikan; kembalikan pengendali (simpan
    referensinya, mis. d._anim_tunggu, agar tidak tersapu GC)."""
    return WaveField(kanvas).start()


# ------------------------------------------------------ centang persetujuan

def check_sprite(w, h, progres):
    """Frame centang progres 0..1 - GARIS TIPIS TAJAM (tanpa glow):
    cincin menyapu, centang menggambar, lalu satu 'ping' cincin tipis
    mengembang sebagai penutup."""
    kecil = min(w, h)
    skala = kecil / 96.0
    W, H = w * SUP, h * SUP
    im = Image.new("RGB", (W, H), _rgb(PANEL))
    dr = ImageDraw.Draw(im)
    c, r = W // 2, int(kecil * SUP * 0.30)
    tebal = max(2, int(round(2.5 * skala * SUP)))
    p = max(0.0, min(1.0, progres))
    e = 1 - (1 - p) ** 3                      # ease-out cubic
    sap = min(e / 0.62, 1.0)
    if sap > 0.02:
        dr.arc([c - r, H // 2 - r, c + r, H // 2 + r], -90,
               -90 + 359 * sap, fill=_rgb(GREEN), width=tebal)
    ck = max(0.0, (e - 0.48) / 0.40)
    if ck > 0.02:
        A = (c - r * 0.46, H / 2 + r * 0.06)
        B = (c - r * 0.08, H / 2 + r * 0.44)
        C = (c + r * 0.54, H / 2 - r * 0.34)
        total = math.dist(A, B) + math.dist(B, C)
        jalan = total * min(ck, 1.0)
        if jalan <= math.dist(A, B):
            k = jalan / math.dist(A, B)
            ujung = (A[0] + (B[0] - A[0]) * k, A[1] + (B[1] - A[1]) * k)
            dr.line([A, ujung], fill=_rgb(GREEN), width=tebal)
        else:
            k = (jalan - math.dist(A, B)) / math.dist(B, C)
            ujung = (B[0] + (C[0] - B[0]) * k, B[1] + (C[1] - B[1]) * k)
            dr.line([A, B, ujung], fill=_rgb(GREEN), width=tebal)
    ping = max(0.0, (e - 0.80) / 0.20)
    if 0.02 < ping < 1.0:
        rp = r * (1.0 + 0.22 * ping)
        pudar = 1.0 - ping
        dr.arc([c - rp, H // 2 - rp, c + rp, H // 2 + rp], -90,
               -90 + 359, fill=_campur(PANEL, GREEN, pudar),
               width=max(1, tebal // 2))
    return _ke_photo(im, w, h)


_cache_cek = {}


def check_photos(w, h, jumlah=30):
    kunci = (w, h, jumlah)
    if kunci in _cache_cek:
        return _cache_cek[kunci]
    foto = [tk.PhotoImage(data=check_sprite(w, h, i / (jumlah - 1)))
            for i in range(jumlah)]
    _cache_cek[kunci] = foto
    return foto


class PlayCheck:
    """Putar animasi centang di tengah kanvas lalu panggil done().
    Dirender pada ukuran pixel kanvas saat mulai (resolusi native)."""

    def __init__(self, kanvas, durasi=1.05, done=None):
        self.kanvas = kanvas
        self._durasi = durasi
        self._done = done
        self._item = None
        self.loop = TimedLoop(kanvas)

    def start(self):
        w = max(self.kanvas.winfo_width(), 120)
        h = max(self.kanvas.winfo_height(), 120)
        self._frames = check_photos(w, h)
        self._item = self.kanvas.create_image(0, 0,
                                              image=self._frames[0],
                                              anchor="c")
        self.loop.start(self._frame)
        return self

    def _frame(self, t):
        # pusat dihitung tiap frame: kanvas melebar setelah di-pack
        try:
            self.kanvas.coords(
                self._item,
                max(self.kanvas.winfo_width(), 120) // 2,
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
