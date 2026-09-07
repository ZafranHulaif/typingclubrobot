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

from .theme import ACCENT, CARD, EDGE, FG, GREEN, ORANGE, PANEL, RED, YELLOW


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
        except Exception:
            # satu tick salah tidak boleh menjatuhkan pemanggil update()
            # (dulu TypeError dari tick lolos ke dialog yang sedang dibuka)
            return
        try:
            self._id = self._w.after(self._step, self._tik)
        except tk.TclError:
            pass


# ------------------------------------------------- gelombang ketikan

N_KUNCI = 7
# jeda antar ketukan SERAGAM: irama acak justru terlihat seperti
# aplikasi tersendat (keluhan live) - yang diminta mulus, jadi
# metronom halus yang konsisten
IRAMA = [0.24] * N_KUNCI
JEDA_AKHIR = 0.55       # jeda napas sebelum mengulang
NAIK = 0.08             # detik menyala penuh
LUNTUR = 0.26           # konstanta pelunturan cahaya
SUP = 2                 # supersample


def _mulaian():
    """Waktu mulai ketukan tiap tuts (kumulatif, tanpa goyangan -
    ketidakteraturan kecil membuat animasi terasa patah-patah)."""
    mula = []
    t = 0.0
    for jeda in IRAMA:
        mula.append(t)
        t += jeda
    return mula


_MULAI = _mulaian()


def _durasi_loop():
    return sum(IRAMA) + JEDA_AKHIR


def _padam(k, t):
    """Terang tuts ke-k pada waktu t (0..1) - nyal cepat, luntur
    perlahan seperti tuts piano yang dilepas."""
    u = (t - _MULAI[k]) % _durasi_loop()
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
    if t % dur > _MULAI[-1] + 0.06:
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


# ------------------------------------------------------- panggung status
#
# Satu kanvas = dua lapis gambar bertumpuk. Ganti status = animasi baru
# MEMUDAR di atas animasi lama (crossfade per-piksel lewat alpha ramp).
# Ganti lagi di tengah transisi tinggal menukar isi lapis atas - tanpa
# patah, tanpa restart. Semua sprite: latar PANEL, bentuk flat tajam,
# gerak seragam berbasis waktu (tanpa keacakan - irama acak terbaca
# sebagai tersendat).

STAGE_DURASI = 2.0      # durasi loop default sprite status
STAGE_FRAME = 40        # frame per loop (cukup halus, hemat memori)
RAMP = 0.38             # detik crossfade antar status


def _sprite_kunci_redam(w, h, t, warna=ACCENT):
    """Tiga tuts redam bernapas pelan - siap/menganggur."""
    W, H = w * SUP, h * SUP
    im = Image.new("RGB", (W, H), _rgb(PANEL))
    dr = ImageDraw.Draw(im)
    s, gap, x0, y0 = _geometri(w, min(h, 72))
    y0 += (h - min(h, 72)) / 2
    s *= SUP
    gap *= SUP
    x0 *= SUP
    y0 *= SUP
    napas = 0.14 + 0.32 * (0.5 + 0.5 * math.sin(t * 2 * math.pi / 2.4))
    for k in range(3):
        x = x0 + k * (s + gap)
        dr.rounded_rectangle([x, y0, x + s, y0 + s], radius=s * 0.20,
                             fill=_campur(PANEL, CARD, 0.9),
                             outline=_campur(EDGE, warna, napas),
                             width=max(1, SUP))
    return _ke_photo(im, w, h)


def _sprite_spinner(w, h, t, warna=ACCENT, busur=100, putaran=1.25):
    """Cincin tipis + busur berputar seragam - sedang membuka/memeriksa."""
    W, H = w * SUP, h * SUP
    im = Image.new("RGB", (W, H), _rgb(PANEL))
    dr = ImageDraw.Draw(im)
    kecil = min(w * 0.5, h)
    r = int(kecil * 0.30 * SUP)
    cx, cy = W // 2, H // 2
    tebal = max(2, int(round(2.5 * (kecil / 64.0) * SUP)))
    dr.ellipse([cx - r, cy - r, cx + r, cy + r],
               outline=_campur(PANEL, warna, 0.22), width=tebal)
    sudut = (t * putaran * 360.0) % 360
    dr.arc([cx - r, cy - r, cx + r, cy + r], sudut - 90, sudut - 90 + busur,
           fill=_rgb(warna), width=tebal)
    return _ke_photo(im, w, h)


def _sprite_kunci_glyph(w, h, t, warna=YELLOW):
    """Glyph kunci bernapas - menunggu login / perlu aktivasi."""
    W, H = w * SUP, h * SUP
    im = Image.new("RGB", (W, H), _rgb(PANEL))
    dr = ImageDraw.Draw(im)
    puls = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(t * 2 * math.pi / 2.0))
    kecil = min(w * 0.5, h)
    skala = kecil * SUP
    cx, cy = W // 2, H // 2
    tebal = max(2, int(round(3.0 * (kecil / 64.0) * SUP)))
    r = int(skala * 0.16)
    # kepala kunci (cincin) + batang + dua gigi
    dr.ellipse([cx - r - int(skala * 0.16), cy - r,
                cx + r + int(skala * 0.16) - int(skala * 0.32),
                cy + r], outline=_campur(PANEL, warna, 0.30 + 0.70 * puls),
               width=tebal)
    px = cx - int(skala * 0.02)
    dr.line([px, cy, px, cy + int(skala * 0.22)],
            fill=_campur(PANEL, warna, 0.30 + 0.70 * puls), width=tebal)
    dr.line([px, cy + int(skala * 0.22), px + int(skala * 0.10),
             cy + int(skala * 0.22)],
            fill=_campur(PANEL, warna, 0.30 + 0.70 * puls), width=tebal)
    dr.line([px, cy + int(skala * 0.12), px + int(skala * 0.08),
             cy + int(skala * 0.12)],
            fill=_campur(PANEL, warna, 0.30 + 0.70 * puls), width=tebal)
    return _ke_photo(im, w, h)


def _sprite_baris(w, h, t, warna=ACCENT):
    """Daftar pelajaran: sorotan berjalan turun di antara 3 baris."""
    W, H = w * SUP, h * SUP
    im = Image.new("RGB", (W, H), _rgb(PANEL))
    dr = ImageDraw.Draw(im)
    bw = min(w * 0.46, 260) * SUP
    bh = max(5, h * 0.11) * SUP
    jeda_r = bh * 0.9
    total = 3 * bh + 2 * jeda_r
    x0 = (W - bw) / 2
    y0 = (H - total) / 2
    u = (t % 2.4) / 2.4
    pos = 2.0 * (1.0 - abs(2.0 * u - 1.0))   # 0 -> 2 -> 0 (ping-pong mulus)
    for k in range(3):
        nyala = max(0.0, 1.0 - abs(pos - (k + 0.5)))
        dr.rounded_rectangle([x0, y0 + k * (bh + jeda_r),
                              x0 + bw, y0 + k * (bh + jeda_r) + bh],
                             radius=bh / 2,
                             fill=_campur(CARD, warna, 0.75 * nyala),
                             outline=_campur(EDGE, warna, nyala),
                             width=max(1, SUP))
    return _ke_photo(im, w, h)


def _sprite_bar(w, h, t, warna=ACCENT):
    """Bar tak pasti: segmen menyapu dalam kapsul - menyiapkan level."""
    W, H = w * SUP, h * SUP
    im = Image.new("RGB", (W, H), _rgb(PANEL))
    dr = ImageDraw.Draw(im)
    bw = min(w * 0.52, 300) * SUP
    bh = max(7, h * 0.13) * SUP
    x0, y0 = (W - bw) / 2, (H - bh) / 2
    dr.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=bh / 2,
                         fill=_campur(PANEL, CARD, 0.9),
                         outline=_rgb(EDGE), width=max(1, SUP))
    seg = bw * 0.32
    pos = (t % 1.6) / 1.6 * (bw + seg) - seg
    kiri = max(x0, pos)
    kanan = min(x0 + bw, pos + seg)
    if kanan > kiri + SUP:
        dr.rounded_rectangle([kiri, y0, kanan, y0 + bh], radius=bh / 2,
                             fill=_rgb(warna))
    return _ke_photo(im, w, h)


def _sprite_caret(w, h, t, warna=FG):
    """Kursor teks berkedip - bot menunggu kamu membuka pelajaran."""
    W, H = w * SUP, h * SUP
    im = Image.new("RGB", (W, H), _rgb(PANEL))
    dr = ImageDraw.Draw(im)
    ch = h * 0.34 * SUP
    cw = max(2, int(h * 0.055 * SUP))
    cx, cy = W // 2, H // 2
    nyala = (t % 1.1) < 0.62
    if nyala:
        dr.rounded_rectangle([cx - cw // 2, cy - ch / 2,
                              cx + cw // 2, cy + ch / 2], radius=cw / 2,
                             fill=_campur(PANEL, warna, 0.85))
    dr.line([cx - int(w * 0.05) * SUP // 2, cy + ch / 2 + 4 * SUP,
             cx + int(w * 0.05) * SUP // 2, cy + ch / 2 + 4 * SUP],
            fill=_rgb(EDGE), width=max(1, SUP))
    return _ke_photo(im, w, h)


def _sprite_jeda(w, h, t, warna=YELLOW):
    """Dua bar pause bernapas - bot dijeda."""
    W, H = w * SUP, h * SUP
    im = Image.new("RGB", (W, H), _rgb(PANEL))
    dr = ImageDraw.Draw(im)
    puls = 0.55 + 0.35 * (0.5 + 0.5 * math.sin(t * 2 * math.pi / 2.2))
    bh = h * 0.34 * SUP
    bw = max(3, int(h * 0.10) * SUP)
    jarak = bw * 1.6
    cx, cy = W // 2, H // 2
    warna_n = _campur(PANEL, warna, puls)
    dr.rounded_rectangle([cx - jarak - bw / 2, cy - bh / 2,
                          cx - jarak + bw / 2, cy + bh / 2], radius=bw / 2,
                         fill=warna_n)
    dr.rounded_rectangle([cx + jarak - bw / 2, cy - bh / 2,
                          cx + jarak + bw / 2, cy + bh / 2], radius=bw / 2,
                         fill=warna_n)
    return _ke_photo(im, w, h)


def _sprite_kotak(w, h, t, warna=RED):
    """Kotak merah bernapas pelan - berhenti."""
    W, H = w * SUP, h * SUP
    im = Image.new("RGB", (W, H), _rgb(PANEL))
    dr = ImageDraw.Draw(im)
    puls = 0.50 + 0.35 * (0.5 + 0.5 * math.sin(t * 2 * math.pi / 2.4))
    s = min(w * 0.5, h) * 0.34 * SUP
    cx, cy = W // 2, H // 2
    dr.rounded_rectangle([cx - s, cy - s, cx + s, cy + s], radius=s * 0.22,
                         fill=_campur(PANEL, warna, puls),
                         outline=_campur(PANEL, warna, min(1.0, puls + 0.3)),
                         width=max(1, SUP))
    return _ke_photo(im, w, h)


def _sprite_selesai(w, h, t, warna=GREEN):
    """Cincin hijau + ping mengembang berulang - rentang selesai."""
    W, H = w * SUP, h * SUP
    im = Image.new("RGB", (W, H), _rgb(PANEL))
    dr = ImageDraw.Draw(im)
    kecil = min(w * 0.5, h)
    r = int(kecil * 0.28 * SUP)
    cx, cy = W // 2, H // 2
    tebal = max(2, int(round(2.5 * (kecil / 64.0) * SUP)))
    dr.arc([cx - r, cy - r, cx + r, cy + r], 0, 360, fill=_rgb(warna),
           width=tebal)
    u = (t % 1.6) / 1.6
    rp = r * (1.05 + 0.30 * u)
    dr.arc([cx - rp, cy - rp, cx + rp, cy + rp], 0, 360,
           fill=_campur(PANEL, warna, 1.0 - u), width=max(1, tebal // 2))
    return _ke_photo(im, w, h)


def _sprite_silang(w, h, t, warna=RED):
    """X tergambar berulang - jendela browser ditutup."""
    W, H = w * SUP, h * SUP
    im = Image.new("RGB", (W, H), _rgb(PANEL))
    dr = ImageDraw.Draw(im)
    kecil = min(w * 0.5, h)
    r = int(kecil * 0.26 * SUP)
    cx, cy = W // 2, H // 2
    tebal = max(2, int(round(3.0 * (kecil / 64.0) * SUP)))
    # gambar 0-0.35, 0.35-0.7; tahan 0.7-0.8; pudar 0.8-1.0 = loop mulus
    siklus = (t % 2.0) / 2.0
    pudar = 1.0
    if siklus > 0.8:
        pudar = 1.0 - (siklus - 0.8) / 0.2
    kotak = _campur(PANEL, warna, 0.25 * pudar)
    garis = _campur(PANEL, warna, pudar)
    dr.rounded_rectangle([cx - r * 1.25, cy - r * 1.25,
                          cx + r * 1.25, cy + r * 1.25], radius=int(r * 0.5),
                         outline=kotak, width=max(1, SUP))
    A = (cx - r * 0.7, cy - r * 0.7)
    B = (cx + r * 0.7, cy + r * 0.7)
    C = (cx - r * 0.7, cy + r * 0.7)
    D = (cx + r * 0.7, cy - r * 0.7)
    if siklus < 0.35:
        k = siklus / 0.35
        ujung = (A[0] + (B[0] - A[0]) * k, A[1] + (B[1] - A[1]) * k)
        dr.line([A, ujung], fill=garis, width=tebal)
    elif siklus < 0.7:
        dr.line([A, B], fill=garis, width=tebal)
        k = (siklus - 0.35) / 0.35
        ujung = (C[0] + (D[0] - C[0]) * k, C[1] + (D[1] - C[1]) * k)
        dr.line([C, ujung], fill=garis, width=tebal)
    else:
        dr.line([A, B], fill=garis, width=tebal)
        dr.line([C, D], fill=garis, width=tebal)
    return _ke_photo(im, w, h)


# peta status -> (fungsi sprite, durasi loop)
STAGE_MAP = {
    "berjalan": (wave_sprite, _durasi_loop()),
    "siap": (_sprite_kunci_redam, 2.4),
    "membuka": (lambda w, h, t: _sprite_spinner(w, h, t, ACCENT, 100, 1.25), 1.0),
    "memeriksa": (lambda w, h, t: _sprite_spinner(w, h, t, YELLOW, 70, 0.9), 1.1),
    "login": (lambda w, h, t: _sprite_kunci_glyph(w, h, t, YELLOW), 2.0),
    "aktivasi": (lambda w, h, t: _sprite_kunci_glyph(w, h, t, ORANGE), 2.0),
    "memilih": (_sprite_baris, 1.8),
    "menyiapkan": (_sprite_bar, 1.6),
    "kamu": (_sprite_caret, 1.1),
    "jeda": (_sprite_jeda, 2.2),
    "berhenti": (_sprite_kotak, 2.4),
    "selesai": (_sprite_selesai, 1.6),
    "tutup": (_sprite_silang, 1.8),
}
class StateStage:
    """Panggung animasi status untuk kartu aktivitas. Dua lapis gambar:
    ganti status = animasi baru memudar penuh di atas yang lama (RAMP);
    ganti di tengah transisi tinggal menukar lapis atas - mulus, tanpa
    restart. Frame dirender segar tiap tik (tanpa cache) - nol aliasing,
    nol memori cache; biaya ~3-5ms per tik saat terlihat saja."""

    def __init__(self, kanvas):
        self.kanvas = kanvas
        self._bawah = kanvas.create_image(0, 0, anchor="nw")
        self._atas = kanvas.create_image(0, 0, anchor="nw")
        self.kanvas.itemconfigure(self._bawah, state="hidden")
        self._kunci = None
        self._kunci_lama = None
        self._t_kunci = 0.0
        self._t_lama = 0.0
        self._ramp0 = None
        self._ukuran = (0, 0)
        self._foto = None    # pegang PhotoImage tik terakhir (GC aman)
        self.loop = TimedLoop(kanvas, step_ms=30)

    def start(self):
        self.loop.start(self._frame)
        return self

    def stop(self):
        self.loop.stop()

    def set_state(self, kunci):
        if kunci == self._kunci or kunci not in STAGE_MAP:
            return
        self._kunci_lama = self._kunci
        self._t_lama = self._t_kunci
        self._kunci = kunci
        self._t_kunci = time.perf_counter()
        self._ramp0 = (self._t_kunci
                       if self._kunci_lama is not None else None)

    def _render(self, kunci, t):
        fn, _dur = STAGE_MAP[kunci]
        return tk.PhotoImage(data=fn(self._ukuran[0], self._ukuran[1], t))

    def _render_alpha(self, kunci, t, k):
        import io as _io
        from PIL import Image as _Im
        fn, _dur = STAGE_MAP[kunci]
        im = _Im.open(_io.BytesIO(
            fn(self._ukuran[0], self._ukuran[1], t))).convert("RGBA")
        im.putalpha(int(255 * k))
        bio = _io.BytesIO()
        im.save(bio, format="PNG")
        return tk.PhotoImage(data=bio.getvalue())

    def _frame(self, t):
        # jam absolut seragam (t dari TimedLoop relatif - jangan dicampur)
        now = time.perf_counter()
        if self._kunci is None:
            return
        w = max(self.kanvas.winfo_width(), 320)
        h = max(self.kanvas.winfo_height(), 48)
        if (w, h) != self._ukuran:
            self._ukuran = (w, h)
        if self._ramp0 is not None:
            u = (now - self._ramp0) / RAMP
            if u >= 1.0:
                self._ramp0 = None
                self._kunci_lama = None
                self.kanvas.itemconfigure(self._bawah, state="hidden")
            else:
                k = u * u * (3.0 - 2.0 * u)        # smoothstep
                fr_l = self._render(self._kunci_lama, now - self._t_lama)
                self.kanvas.itemconfigure(self._bawah, state="normal",
                                          image=fr_l)
                self._foto = self._render_alpha(self._kunci,
                                                now - self._t_kunci, k)
                self.kanvas.itemconfigure(self._atas, state="normal",
                                          image=self._foto)
                return
        self._foto = self._render(self._kunci, now - self._t_kunci)
        self.kanvas.itemconfigure(self._atas, state="normal",
                                  image=self._foto)

