"""
bot_gui.py - Antarmuka grafis untuk TypingClub Autopilot.

Fitur:
- Tombol Start/Pause/Stop, pilihan browser + kecepatan, kartu aktivitas
  (kalimat besar bahasa awam; TANPA log di layar, TANPA istilah teknis).
- Dialog visual (bukan messagebox polos): kartu pilihan browser dengan logo
  asli dari file exe browser, konfirmasi buka browser / tutup aplikasi.
- Lisensi terikat mesin: aktivasi sekali per komputer (lihat _license_gen.py).
- Jendela Dev (tersembunyi, klik teks versi 5x): identitas build, bot.log.
"""

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

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
    PROGRAM_PATH = sys.executable
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    PROGRAM_PATH = os.path.abspath(__file__)

LOG_FILE = os.path.join(BASE_DIR, "bot.log")
SETTINGS_FILE = os.path.join(BASE_DIR, "typingbot_settings.json")
LICENSE_FILE = os.path.join(BASE_DIR, "license.dat")

APP_VERSION = "2.5"

# Secret penandatanganan lisensi. Digunakan juga oleh _license_gen.py.
LICENSE_SECRET = ("***REMOVED***"
                  "***REMOVED***")

# ---------------------------------------------------------------- palet warna
BG = "#141519"          # latar jendela
PANEL = "#1b1d23"       # panel / dialog
CARD = "#20232b"        # kartu / tombol sekunder
CARD_HOVER = "#272b35"
EDGE = "#2c303b"        # garis pemisah / border
FG = "#e9eaee"
DIM = "#9aa0ab"
FAINT = "#6a7080"
ACCENT = "#4f8cff"
GREEN = "#3ecf6e"
YELLOW = "#e8b339"
RED = "#e05555"
ORANGE = "#ff9f43"
BTN_FG = "#101116"

BROWSER_WARNA = {"Brave": "#fb542b", "Chrome": "#4285f4", "Edge": "#0f7eb6"}


def _build_stamp():
    """Identitas build = tanggal modifikasi file exe/skrip sendiri."""
    try:
        return time.strftime("%d %b %Y %H:%M",
                             time.localtime(os.path.getmtime(PROGRAM_PATH)))
    except Exception:
        return "?"


# ------------------------------------------------------------------ lisensi
def _norm(s):
    return "".join(ch for ch in str(s).upper() if ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")


def _data_mesin():
    """Sidik jari komputer: MAC + nama komputer + serial volume sistem."""
    bagian = []
    nic = uuid.getnode()
    if nic and not (nic & 0x010000000000):      # bit multicast = MAC acak
        bagian.append(f"mac={nic:012x}")
    bagian.append("host=" + (os.environ.get("COMPUTERNAME")
                             or socket.gethostname()).upper())
    try:
        vol = wintypes.DWORD()
        drive = os.environ.get("SystemDrive", "C:") + "\\"
        if ctypes.windll.kernel32.GetVolumeInformationW(
                drive, None, 0, ctypes.byref(vol), None, None, None, 0):
            bagian.append(f"vol={vol.value}")
    except Exception:
        pass
    return "|".join(bagian)


def _kode_mesin():
    dig = hashlib.sha256(_data_mesin().encode("utf-8")).digest()
    kode = base64.b32encode(dig).decode("ascii")[:10]
    return "-".join([kode[:5], kode[5:]])


def _buat_kunci(kode_mesin):
    dig = hmac.new(LICENSE_SECRET.encode("utf-8"),
                   _norm(kode_mesin).encode("utf-8"), hashlib.sha256).digest()
    b32 = base64.b32encode(dig).decode("ascii")[:20]
    return "-".join(b32[i:i + 5] for i in range(0, 20, 5))


def _lisensi_tersimpan():
    try:
        return open(LICENSE_FILE, encoding="utf-8").read().strip()
    except Exception:
        return ""


def _lisensi_valid():
    return _norm(_lisensi_tersimpan()) == _norm(_buat_kunci(_kode_mesin()))


def _simpan_lisensi(kunci):
    with open(LICENSE_FILE, "w", encoding="utf-8") as f:
        f.write(kunci.strip() + "\n")


# ------------------------------------------------------- ikon dari file .exe
user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)


class _ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD),
                ("yHotspot", wintypes.DWORD), ("hbmMask", wintypes.HBITMAP),
                ("hbmColor", wintypes.HBITMAP)]


class _BITMAP(ctypes.Structure):
    _fields_ = [("bmType", wintypes.LONG), ("bmWidth", wintypes.LONG),
                ("bmHeight", wintypes.LONG), ("bmWidthBytes", wintypes.LONG),
                ("bmPlanes", wintypes.WORD), ("bmBitsPixel", wintypes.WORD),
                ("bmBits", wintypes.LPVOID)]


class _BMIH(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


shell32.ExtractIconExW.argtypes = [wintypes.LPCWSTR, ctypes.c_int,
                                   ctypes.POINTER(wintypes.HICON),
                                   ctypes.POINTER(wintypes.HICON), wintypes.UINT]
user32.PrivateExtractIconsW = getattr(user32, "PrivateExtractIconsW")
user32.PrivateExtractIconsW.argtypes = [
    wintypes.LPCWSTR, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.POINTER(wintypes.HICON), ctypes.POINTER(wintypes.UINT),
    wintypes.UINT, wintypes.UINT]
user32.PrivateExtractIconsW.restype = wintypes.UINT
user32.GetIconInfo.argtypes = [wintypes.HICON, ctypes.POINTER(_ICONINFO)]
user32.GetDC.restype = wintypes.HDC
gdi32.GetObjectW.argtypes = [wintypes.HBITMAP, ctypes.c_int, ctypes.c_void_p]
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT,
                            wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p,
                            wintypes.UINT]
gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
user32.DestroyIcon.argtypes = [wintypes.HICON]


def _png_rgb(w, h, rgb):
    import struct
    raw = b"".join(b"\x00" + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _bilinear_rgb(src, w0, h0, w1, h1):
    """Resample RGB bytearray w0xh0 -> w1xh1 (bilinear, pure python).
    Dipakai untuk mengecilkan ikon 256px -> ukuran tampilan dengan halus;
    zoom/subsample tk (nearest-neighbor) membuat logo tampak kotak-kotak."""
    dst = bytearray(w1 * h1 * 3)
    sx = (w0 - 1) / max(w1 - 1, 1)
    sy = (h0 - 1) / max(h1 - 1, 1)
    for y in range(h1):
        fy = y * sy
        y0 = int(fy)
        y1 = min(y0 + 1, h0 - 1)
        ty = fy - y0
        for x in range(w1):
            fx = x * sx
            x0 = int(fx)
            x1 = min(x0 + 1, w0 - 1)
            tx = fx - x0
            i00 = (y0 * w0 + x0) * 3
            i10 = (y0 * w0 + x1) * 3
            i01 = (y1 * w0 + x0) * 3
            i11 = (y1 * w0 + x1) * 3
            o = (y * w1 + x) * 3
            for c in range(3):
                a = src[i00 + c] + (src[i10 + c] - src[i00 + c]) * tx
                b = src[i01 + c] + (src[i11 + c] - src[i01 + c]) * tx
                dst[o + c] = int(a + (b - a) * ty + 0.5)
    return bytes(dst)


def _ikon_png(path, ukuran=44, bg=(32, 35, 43)):
    """Logo asli aplikasi dari file exe-nya -> bytes PNG RGB berukuran
    PERSIS `ukuran` px. Ekstraksi resolusi tinggi (256px dulu, via
    PrivateExtractIconsW) lalu bilinear mengecil - ekstraksi 32px lalu
    zoom tk (nearest) membuat logo tampak pecah/kotak-kotak (keluhan
    user). Handle GDI di-mask 32-bit (handle 64-bit besar pernah membuat
    konversi gagal 'int too long' -> semua logo jadi fallback).
    Return (png, alasan_gagal)."""
    alasan = ""
    for idx in range(6):
        for size in (256, 64, 48, 32):
            hicon = wintypes.HICON()
            try:
                if not user32.PrivateExtractIconsW(
                        str(path), idx, size, size,
                        ctypes.byref(hicon), None, 1, 0) or not hicon.value:
                    continue
                try:
                    info = _ICONINFO()
                    if not user32.GetIconInfo(hicon, ctypes.byref(info)) \
                            or not info.hbmColor:
                        continue
                    try:
                        gdi32.DeleteObject(
                            ctypes.c_void_p(int(info.hbmMask or 0) & 0xFFFFFFFF))
                    except Exception:
                        pass
                    bm = _BITMAP()
                    hbm = ctypes.c_void_p(int(info.hbmColor or 0) & 0xFFFFFFFF)
                    if not gdi32.GetObjectW(hbm, ctypes.sizeof(_BITMAP),
                                            ctypes.byref(bm)) or bm.bmWidth <= 0:
                        gdi32.DeleteObject(hbm)
                        continue
                    w, h = bm.bmWidth, abs(bm.bmHeight)
                    if w > 512 or h > 512:
                        gdi32.DeleteObject(hbm)
                        continue
                    bmi = _BMIH(biSize=ctypes.sizeof(_BMIH), biWidth=w,
                                biHeight=-h, biPlanes=1, biBitCount=32,
                                biCompression=0)
                    buf = ctypes.create_string_buffer(w * h * 4)
                    hdc = user32.GetDC(None)
                    ok = gdi32.GetDIBits(hdc, hbm, 0, h, buf,
                                         ctypes.byref(bmi), 0)
                    user32.ReleaseDC(None, hdc)
                    gdi32.DeleteObject(hbm)
                    if not ok:
                        continue
                    px = buf.raw
                    full = bytearray(w * h * 3)
                    ada_alpha, n_warna = False, set()
                    for i in range(w * h):
                        b, g, r, a = (px[i * 4], px[i * 4 + 1],
                                      px[i * 4 + 2], px[i * 4 + 3])
                        n_warna.add((r, g, b))
                        if a:
                            ada_alpha = True
                            al = a / 255.0
                            full[i * 3] = int(r * al + bg[0] * (1 - al))
                            full[i * 3 + 1] = int(g * al + bg[1] * (1 - al))
                            full[i * 3 + 2] = int(b * al + bg[2] * (1 - al))
                        else:
                            full[i * 3:i * 3 + 3] = bytes(bg)
                    if not ada_alpha or len(n_warna) < 4:
                        alasan = f"indeks {idx}/{size}px: datar"
                        continue
                    if w != ukuran or h != ukuran:
                        rgb = _bilinear_rgb(full, w, h, ukuran, ukuran)
                    else:
                        rgb = bytes(full)
                    return _png_rgb(ukuran, ukuran, rgb), ""
                finally:
                    try:
                        user32.DestroyIcon(hicon)
                    except Exception:
                        pass
            except Exception as e:
                alasan = f"indeks {idx}: {e}"
    return None, alasan or "tidak diketahui"


def _gambar_vektor_ikon(c, nama, cx, cy, r, warna="white"):
    """Gambar ikon VEKTOR di dalam lingkaran (pusat presisi, bukan emoji
    yang glyph-nya bisa saja miring dalam kotak em-nya - keluhan user
    'petir & bola dunia off center')."""
    if nama == "petir":
        pts = [(0.05, -0.52), (-0.26, 0.10), (-0.04, 0.10),
               (-0.05, 0.52), (0.26, -0.10), (0.04, -0.10)]
        flat = [v for dx, dy in pts for v in (cx + dx * r, cy + dy * r)]
        c.create_polygon(flat, fill=warna, width=0)
    elif nama == "bola":
        d = r * 0.62
        tebal = max(2, int(r * 0.09))
        c.create_oval(cx - d, cy - d, cx + d, cy + d,
                      outline=warna, width=tebal)
        c.create_line(cx - d, cy, cx + d, cy, fill=warna, width=tebal)
        c.create_oval(cx - d * 0.45, cy - d, cx + d * 0.45, cy + d,
                      outline=warna, width=tebal)
    elif nama == "warning":
        # segitiga + tanda seru, semua dipusatkan matematis (emoji ⚠
        # glyph-nya duduk miring di kotak em - keluhan user)
        tebal = max(2, int(r * 0.11))
        c.create_polygon(cx, cy - r * 0.74,
                         cx - r * 0.82, cy + r * 0.60,
                         cx + r * 0.82, cy + r * 0.60,
                         fill="", outline=warna, width=tebal,
                         joinstyle="round")
        c.create_line(cx, cy - r * 0.30, cx, cy + r * 0.10,
                      fill=warna, width=tebal, capstyle="round")
        dt = max(2, int(r * 0.10))
        c.create_oval(cx - dt, cy + r * 0.30 - dt,
                      cx + dt, cy + r * 0.30 + dt,
                      fill=warna, outline=warna)


def _skala_tkimg(img, target):
    """Skala tk.PhotoImage agar PAS di dalam kotak `target`x`target` px
    (aspek dipertahankan, sisi TERPANJANG = target; zoom+subsample
    rasional). Dulu hanya lebar yang disamakan -> ikon persegi panjang
    tampak miring/off-center (keluhan user)."""
    w, h = img.width(), img.height()
    sisi = max(w, h)
    if sisi <= 0 or abs(sisi - target) < 0.5:
        return img
    best = None
    for q in range(1, 49):
        p = max(1, round(target * q / sisi))
        err = abs(sisi * p / q - target)
        if best is None or err < best[0]:
            best = (err, p, q)
        if err < 0.5:
            break
    _err, p, q = best
    try:
        if p > 1:
            img = img.zoom(p)
        if q > 1:
            img = img.subsample(q, q)
    except Exception:
        pass
    return img


def _ikon_widget(parent, path=None, nama="?", warna=ACCENT, ukuran=40, char=None):
    """Slot ikon: logo asli bila exe ketemu, kalau tidak lingkaran warna
    merek + ikon vektor/awalan nama. Ikon vektor digambar dengan pusat
    presisi (emoji ⚡ pernah tampak miring dalam kotak em-nya)."""
    latar = parent["bg"]
    c = tk.Canvas(parent, width=ukuran, height=ukuran, bg=latar,
                  highlightthickness=0)
    img = None
    if path:
        try:
            png, alasan = _ikon_png(path, ukuran)
            if png:
                img = tk.PhotoImage(master=c, data=base64.b64encode(png).decode())
                img = _skala_tkimg(img, ukuran)
                c._img = img
            else:
                print(f"[GUI] ikon {nama}: pakai fallback ({alasan})")
        except Exception as e:
            print(f"[GUI] ikon {nama}: pakai fallback ({e})")
            img = None
    if img:
        # pusat presisi: anchor center + titik tengah eksak (dulu +1 px ->
        # logo tampak geser; keluhan user 'off center')
        c.create_image(ukuran / 2, ukuran / 2, image=img, anchor="center")
    else:
        c.create_oval(1, 1, ukuran - 1, ukuran - 1, fill=warna, width=0)
        r = (ukuran - 1) / 2 - 1
        cx = cy = ukuran / 2
        if char == "⚡":
            _gambar_vektor_ikon(c, "petir", cx, cy, r)
        else:
            c.create_text(cx, cy, text=char if char else nama[0].upper(),
                          font=("Segoe UI", int(ukuran * 0.42), "bold"),
                          fill="white", anchor="center")
    return c


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
        # sinkron label bila variabel di-set dari luar (bukan lewat _set)
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
        # posisikan menu DI TITIK KLIK (bukan sisi kiri kotak: kotak speed
        # melebar satu baris penuh - dulu menu muncul jauh di kiri padahal
        # user menekan kanan; keluhan user). Clamp supaya tidak keluar layar.
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


class _Dialog(tk.Toplevel):
    """Kerangka dialog gelap: ikon bulat + judul + subjudul, body, tombol."""

    def __init__(self, induk, judul, subjudul="", ikon="ℹ", warna=ACCENT):
        super().__init__(induk)
        self.hasil = None
        self._primer = None
        self.configure(bg=PANEL)
        self.transient(induk)
        self.resizable(False, False)

        head = tk.Frame(self, bg=PANEL)
        head.pack(fill="x", padx=24, pady=(22, 4))
        box = tk.Canvas(head, width=46, height=46, bg=PANEL, highlightthickness=0)
        box.pack(side="left")
        box.create_oval(2, 2, 44, 44, fill=warna, width=0)
        # ikon header: pusat lingkaran eksak (23,23); 🌐/⚠ digambar vektor
        # (emoji glyph-nya tidak persis di tengah kotak em - keluhan user)
        if ikon == "🌐":
            _gambar_vektor_ikon(box, "bola", 23, 23, 21)
        elif ikon == "⚠":
            _gambar_vektor_ikon(box, "warning", 23, 23, 20)
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

        self.protocol("WM_DELETE_WINDOW", lambda: self.selesai(None))
        self.bind("<Escape>", lambda e: self.selesai(None))
        self.bind("<Return>", self._enter)

    def _enter(self, _e):
        if self._primer:
            self._primer._klik()

    def tombol(self, teks, nilai=None, warna_btn=ACCENT, primer=True, cmd=None):
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
          self.selesai(nilai if nilai is not None else teks)

        b._klik = klik
        b.bind("<Button-1>", klik)
        return b

    def selesai(self, nilai):
        self.hasil = nilai
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()

    def tampilkan(self):
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        ix, iy = self.master.winfo_rootx(), self.master.winfo_rooty()
        iw, ih = self.master.winfo_width(), self.master.winfo_height()
        self.geometry(f"+{max(ix + (iw - w) // 2, 40)}+{max(iy + (ih - h) // 2, 40)}")
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


def _fokus_jendela_browser():
    """Bawa jendela browser bot ke depan (Windows, via win32). Dipanggil
    GUI sesaat SETELAH user menekan tombol login - GUI baru saja menerima
    klik jadi punya izin SetForegroundWindow; bring_to_front CDP saja
    sering tidak menaikkan jendela saat bot berjalan di belakang.
    Prioritas: jendela yang judulnya menyebut edclub (jendela milik bot),
    supaya tidak mengambil jendela browser pribadi user."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        kandidat = {"brave.exe", "chrome.exe", "msedge.exe"}
        temuan = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum_cb(hwnd, _l):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                h = kernel32.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED
                if not h:
                    return True
                buf = ctypes.create_unicode_buffer(512)
                n = wintypes.DWORD(512)
                ok = kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n))
                kernel32.CloseHandle(h)
                if not ok:
                    return True
                exe = buf.value.replace("\\", "/").split("/")[-1].lower()
                if exe in kandidat:
                    judul = ctypes.create_unicode_buffer(256)
                    user32.GetWindowTextW(hwnd, judul, 256)
                    if judul.value:
                        temuan.append(("edclub" in judul.value.lower(), hwnd))
            except Exception:
                pass
            return True

        user32.EnumWindows(enum_cb, 0)
        temuan.sort(key=lambda x: not x[0])  # jendela edclub dulu
        for _pilih_edclub, hwnd in temuan[:3]:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE (kalau diminimalkan)
            user32.SetForegroundWindow(hwnd)
            if user32.GetForegroundWindow() == hwnd:
                return True
    except Exception:
        pass
    return False


# ------------------------------------------------- pesan ramah (kartu aktivitas)
# Terjemahan baris log engine -> kalimat awam untuk kartu aktivitas.
# Baris yang TIDAK cocok aturan mana pun tetap masuk bot.log tapi TIDAK
# ditampilkan: layar pengguna harus bebas istilah teknis (port, debug,
# proses, dsb.); pemilik tetap bisa membuka bot.log lewat jendela Dev.
_AKTIV_MAP = [
    (re.compile(r"Menyambungkan .* ke browser \((\w+)\)"), "Menyambung ke %s..."),
    (re.compile(r"[Mm]embuka (\w+) otomatis"), "Membuka jendela %s..."),
    (re.compile(r"Membuka (\w+) dengan profil khusus"), "Menyiapkan jendela %s..."),
    (re.compile(r"\[OTOMATIS\] (\w+) sudah jalan"), "Memakai jendela %s yang sudah terbuka"),
    (re.compile(r"Terhubung! Tab aktif"), "Tersambung. Bot mulai bekerja."),
    (re.compile(r"\[SETUP\] Browser baru sedang set-up"),
     "Selesaikan setelan awal di jendela browser, lalu tutup halamannya"),
    (re.compile(r"\[SETUP\] Set-up browser selesai"), "Browser siap"),
    (re.compile(r"\[LOGIN\] Menunggu login edclub"),
     "Menunggu kamu login di jendela browser"),
    (re.compile(r"\[LOGIN\] Halaman login terdeteksi"),
     "Selesaikan login di jendela browser"),
    (re.compile(r"\[LOGIN\] Sesi edclub aktif kembali"), "Login aktif. Bot lanjut bekerja."),
    (re.compile(r"\[USER\] kamu sedang memakai browser bot"),
     "Kamu sedang memakai browser bot - bot menunggu"),
    (re.compile(r"\[USER\] halaman tenang"), "Bot lanjut bekerja."),
    (re.compile(r"\[RENTANG\] menuju level awal (\d+)"), "Menuju level %s"),
    (re.compile(r"\[RENTANG\] sudah ada lesson terbuka"),
     "Mengerjakan pelajaran yang terbuka"),
    (re.compile(r"\[PETA\] membangun peta"), "Membaca daftar level..."),
    (re.compile(r"\[PETA\] (\d+)/(\d+) level terpetakan"),
     "Membaca daftar level... %s dari %s"),
    (re.compile(r"\[PETA\] selesai"), "Daftar level selesai dibaca."),
    (re.compile(r"\[Standard\] banner Start Typing diklik"), "Mulai mengetik..."),
    (re.compile(r"\[Standard\] Sisa \d+ karakter"), "Sedang mengetik..."),
    (re.compile(r"\[Tutorial\] ketik"), "Sedang mengetik..."),
    (re.compile(r"\[Minigame/[^\]]*\] Mengetik"), "Sedang mengetik..."),
    (re.compile(r"\[Keyboard-layar\] klik"), "Sedang mengetik..."),
    (re.compile(r"lesson selesai"), "Pelajaran selesai"),
    (re.compile(r"\[Skor\]"), "Melanjutkan..."),
    (re.compile(r"\[Video\].*dilompat"), "Melewati video"),
    (re.compile(r"\[SKIP\]"), "Melewati level ini"),
    (re.compile(r"terkunci premium - lewati"), "Melewati level premium"),
    (re.compile(r"game beku"), "Permainan tidak merespons - dilewati"),
    (re.compile(r"\[PEMULIHAN\] Browser .* hidup kembali"), "Browser kembali siap."),
    (re.compile(r"\[RECOVERY\]|\[PEMULIHAN\]"), "Memuat ulang..."),
    (re.compile(r"\[Pop-up\] badge streak"), "Menutup popup hadiah"),
    (re.compile(r"Membuka edclub.com otomatis"), "Membuka edclub.com..."),
    (re.compile(r"Gagal membuka edclub"), "Buka edclub.com di jendela browser"),
    (re.compile(r"Gagal menyambung ke browser"), "Tidak bisa menyambung ke browser"),
    (re.compile(r"Tutup semua jendela browser, lalu klik Start lagi"),
     "Tutup semua jendela browser, lalu klik Start lagi"),
    (re.compile(r"\[PROFIL\] (\w+) sedang jalan"),
     "Menutup %s dulu supaya bot bisa memakai profil kamu"),
    (re.compile(r"\[PROFIL\] tidak ditutup"),
     "Browser tidak ditutup - bot memakai profil khusus bot"),
    (re.compile(r"\[PROFIL\] Chrome/Edge versi baru"),
     "Chrome/Edge baru tidak mengizinkan bot di profil utama - "
     "tetap memakai profil khusus bot"),
    (re.compile(r"\[PROFIL\] Brave versi ini"),
     "Brave ini tidak mengizinkan bot di profil utama - "
     "bot memakai profil khusus"),
    (re.compile(r"^Bot dihentikan"), "Bot berhenti."),
    (re.compile(r"Bot sedang berhenti"), "Berhenti..."),
    (re.compile(r"^Selesai\. Total"), "Selesai."),
]

_NAMA_BAIK = {"brave": "Brave", "chrome": "Google Chrome",
              "msedge": "Microsoft Edge"}


def _teks_ramah(line):
    """Baris log -> kalimat awam, atau None bila tidak perlu ditampilkan."""
    for rx, tmpl in _AKTIV_MAP:
        m = rx.search(line)
        if m:
            try:
                return tmpl % m.groups() if m.groups() else tmpl
            except TypeError:
                return tmpl
    return None


def _nama_tampil(nama):
    """'brave'/'msedge' dari sistem -> nama produk yang dikenal pengguna."""
    kunci = (nama or "").strip().lower().replace("  (webview)", "")
    if kunci in _NAMA_BAIK:
        return _NAMA_BAIK[kunci]
    return kunci[:1].upper() + kunci[1:] if kunci else "Aplikasi"


def dialog_pilih_browser(induk, detected, dipilih="Otomatis", profil="bot"):
    """Kartu pilihan browser (logo asli + nama + keterangan singkat)
    + pilihan profil (khusus bot / profil sendiri).
    Return: (nama pilihan, mode profil 'bot'/'saya') atau None bila dibatalkan."""
    d = _Dialog(induk, "Pilih browser untuk bot",
                "Bot memakai satu browser khusus - pilih yang jarang kamu pakai.",
                ikon="🌐")
    d.pilihan = dipilih if dipilih in ["Otomatis"] + [n for n, _ in detected] else "Otomatis"
    baris = tk.Frame(d.body, bg=PANEL)
    baris.pack(fill="x")

    kartu_state = []

    def pilih(nama):
        d.pilihan = nama
        for st, render in kartu_state:
            st["on"] = st["nama"] == nama
            render()

    def buat_kartu(nama, path):
        # scope per-kartu supaya closure render() tidak tertukar antar kartu.
        # Dimensi KARTU SERAGAM (fixed + propagate off): dulu lebar mengikuti
        # isi -> tiap kartu beda ukuran (keluhan user).
        wrap = tk.Frame(baris, bg=CARD, highlightthickness=1,
                        highlightbackground=EDGE, cursor="hand2",
                        width=128, height=118)
        wrap.pack(side="left", padx=5)
        wrap.pack_propagate(False)
        dalam = tk.Frame(wrap, bg=CARD)
        dalam.pack(expand=True, fill="both", padx=8, pady=(10, 8))
        _ikon_widget(dalam, path, nama, BROWSER_WARNA.get(nama, "#7c5cff"),
                     40, char="⚡" if nama == "Otomatis" else None).pack()
        nmlbl = tk.Label(dalam, text=nama, font=("Segoe UI", 10, "bold"),
                         fg=FG, bg=CARD)
        nmlbl.pack(pady=(10, 0))
        semua = [wrap, dalam, nmlbl]
        st = {"nama": nama, "on": False}

        def render():
            for wdgt in semua:
                wdgt.configure(bg=CARD_HOVER if st["on"] else CARD)
            wrap.configure(highlightbackground=ACCENT if st["on"] else EDGE)

        def klik(_e=None):
            pilih(nama)

        def hover(_e):
            if not st["on"]:
                for wdgt in semua:
                    wdgt.configure(bg=CARD_HOVER)
            wrap.configure(highlightbackground=ACCENT)

        def leave(_e):
            render()

        for wdgt in semua:
            wdgt.bind("<Button-1>", klik)
            wdgt.bind("<Enter>", hover)
            wdgt.bind("<Leave>", leave)
        kartu_state.append((st, render))
        render()

    daftar = [("Otomatis", None)] + list(detected)
    for nama, path in daftar:
        buat_kartu(nama, path)
    pilih(d.pilihan)

    # ----- pilihan profil: khusus bot (disarankan) / profil sendiri -----
    # 'Profil sendiri' hanya efektif di Brave: Chrome/Edge versi baru
    # (keamanan Chromium 136+) menolak bot di profil utama, jadi pilihan
    # itu dikunci dengan penjelasan singkat kalau Chrome/Edge terpilih.
    d.profil = profil if profil in ("bot", "saya") else "bot"
    tk.Frame(d.body, bg=EDGE, height=1).pack(fill="x", pady=(12, 0))
    tk.Label(d.body, text="Profil yang dipakai bot:",
             font=("Segoe UI", 9, "bold"), fg=DIM, bg=PANEL,
             anchor="w").pack(anchor="w", pady=(10, 0))
    pbaris = tk.Frame(d.body, bg=PANEL)
    pbaris.pack(fill="x")
    profil_state = []

    def profil_bisa(nama_browser):
        return nama_browser in ("Otomatis", "Brave")

    def pilih_profil(mode):
        d.profil = mode
        for st, render in profil_state:
            st["on"] = st["mode"] == mode and st["aktif"]
            render()

    def buat_chip_profil(mode, judul, keterangan):
        st = {"mode": mode, "on": False, "aktif": True}
        wrap = tk.Frame(pbaris, bg=CARD, highlightthickness=1,
                        highlightbackground=EDGE, cursor="hand2")
        wrap.pack(side="left", padx=(0, 8), fill="x", expand=True)
        dalam = tk.Frame(wrap, bg=CARD)
        dalam.pack(fill="both", padx=10, pady=8)
        judul_lbl = tk.Label(dalam, text=judul, font=("Segoe UI", 10, "bold"),
                             fg=FG, bg=CARD, anchor="w")
        judul_lbl.pack(anchor="w")
        ket_lbl = tk.Label(dalam, text=keterangan, font=("Segoe UI", 8),
                           fg=DIM, bg=CARD, anchor="w", wraplength=190,
                           justify="left")
        ket_lbl.pack(anchor="w")
        semua = [wrap, dalam, judul_lbl, ket_lbl]

        def render():
            bg_ = (CARD_HOVER if st["on"] else CARD) if st["aktif"] else PANEL
            fg_ = FG if st["aktif"] else FAINT
            for wdgt in semua:
                wdgt.configure(bg=bg_)
            judul_lbl.configure(fg=fg_)
            wrap.configure(highlightbackground=ACCENT if st["on"] else EDGE)

        def klik(_e=None):
            if st["aktif"]:
                pilih_profil(mode)

        def hover(_e):
            if st["aktif"] and not st["on"]:
                for wdgt in semua:
                    wdgt.configure(bg=CARD_HOVER)

        def leave(_e):
            render()

        for wdgt in semua:
            wdgt.bind("<Button-1>", klik)
            wdgt.bind("<Enter>", hover)
            wdgt.bind("<Leave>", leave)
        profil_state.append((st, render))
        render()

    buat_chip_profil("bot", "Profil khusus bot  ✓ disarankan",
                     "Jendela terpisah khusus bot. Login edclub "
                     "cukup sekali, data kamu tidak tersentuh.")
    buat_chip_profil("saya", "Profil saya sendiri",
                     "Bot memakai profil browser kamu (login & data "
                     "ikut terpakai). Hanya untuk Brave.")
    profil_hint = tk.Label(d.body, text="", font=("Segoe UI", 8),
                           fg=FAINT, bg=PANEL, wraplength=460,
                           justify="left")
    profil_hint.pack(anchor="w", pady=(6, 0))

    def sinkron_profil():
        bisa = profil_bisa(d.pilihan)
        for st, render in profil_state:
            st["aktif"] = bisa if st["mode"] == "saya" else True
            if not st["aktif"]:
                st["on"] = False
        pilih_profil(d.profil if bisa else "bot")
        profil_hint.configure(
            text="" if bisa else
            "Chrome dan Edge versi baru tidak mengizinkan bot memakai "
            "profil utama (aturan keamanan dari pembuatnya). Pilih Brave "
            "untuk memakai profil sendiri, atau tetap gunakan profil "
            "khusus bot.")

    _pilih_asli = pilih

    def pilih_dan_sinkron(nama):
        _pilih_asli(nama)
        sinkron_profil()

    pilih = pilih_dan_sinkron           # kartu browser -> sinkron chip profil
    pilih(d.pilihan)

    tk.Label(d.body, text="Kapan pun bisa diganti lewat kartu browser di jendela utama.\n"
                          "Kalau tidak yakin, pilih Otomatis.",
             font=("Segoe UI", 8), fg=FAINT, bg=PANEL,
             wraplength=470, justify="left").pack(anchor="w", pady=(10, 0))
    d.tombol("Batal", None, primer=False)
    d.tombol("Pilih", None, cmd=lambda: d.selesai((d.pilihan, d.profil)))
    return d.tampilkan()


def dialog_buka_browser(induk, nama, path, profil="bot"):
    """Konfirmasi visual sebelum bot membuka jendela browser sendiri."""
    d = _Dialog(induk, f"Buka {nama} untuk bot?",
                "TypingBot akan membuka jendela browser khusus.", ikon="🚀")
    atas = tk.Frame(d.body, bg=PANEL)
    atas.pack(fill="x")
    _ikon_widget(atas, path, nama, BROWSER_WARNA.get(nama, ACCENT), 44).pack(side="left")
    tx = tk.Frame(atas, bg=PANEL)
    tx.pack(side="left", padx=(14, 0))

    if profil == "saya" and nama == "Brave":
        daftar_teks = (
            "•  Bot memakai profil Brave kamu - semua login & data ikut terpakai",
            "•  Kalau Brave sedang jalan, TypingBot akan minta izin menutupnya dulu",
            "•  Bot mengendalikan jendela itu sendiri (klik & ketik otomatis)",
        )
    else:
        daftar_teks = (
            "•  Terpisah dari browser yang sedang kamu pakai, kerja kamu tidak terganggu",
            "•  Login edclub cukup sekali di jendela itu, tersimpan untuk selanjutnya",
            "•  Bot mengendalikan jendela itu sendiri (klik & ketik otomatis)",
        )
    for baris_teks in daftar_teks:
        tk.Label(tx, text=baris_teks, font=("Segoe UI", 10), fg=FG, bg=PANEL,
                 anchor="w").pack(anchor="w", pady=1)
    tk.Label(d.body, text="Jendela boleh diminimize, bot tetap jalan di belakang.",
             font=("Segoe UI", 9), fg=FAINT, bg=PANEL).pack(anchor="w", pady=(10, 0))
    d.tombol("Batal", False, primer=False)
    d.tombol(f"Buka {nama}", True)
    return d.tampilkan()


def dialog_tutup_paksa(induk, nama, pid, exe=None):
    """Konfirmasi sebelum menutup aplikasi lain yang menghalangi bot.
    Bahasa awam total ('Brave sedang jalan, tutup dulu ya') - tanpa kata
    port/PID/proses. Menampilkan LOGO aplikasi yang akan ditutup
    (diekstrak dari exe-nya, mis. logo Adobe kalau yang jalan
    komponennya Adobe)."""
    nama = _nama_tampil(nama)
    d = _Dialog(induk, f"Tutup {nama} dulu, ya",
                "TypingBot baru bisa jalan setelah aplikasi ini ditutup.",
                ikon="⚠", warna=RED)
    atas = tk.Frame(d.body, bg=PANEL)
    atas.pack(fill="x", pady=(2, 0))
    _ikon_widget(atas, exe, nama, ACCENT, 44).pack(side="left")
    tx = tk.Frame(atas, bg=PANEL)
    tx.pack(side="left", padx=(14, 0))
    tk.Label(tx, text=nama, font=("Segoe UI", 13, "bold"), fg=FG,
             bg=PANEL).pack(anchor="w")
    tk.Label(tx, text="sedang berjalan sekarang", font=("Segoe UI", 9), fg=DIM,
             bg=PANEL).pack(anchor="w")
    nl = nama.lower()
    ekstra = (f"\nSetelah ini TypingBot membuka jendela {nama} versinya sendiri."
              if ("brave" in nl or "chrome" in nl or "edge" in nl) else "")
    tk.Label(d.body, text=f"Bot akan menutup semua jendela {nama} sekarang.\n"
                          "Kalau ada pekerjaan yang belum disimpan, "
                          "simpan dulu." + ekstra,
             font=("Segoe UI", 10), fg=FG, bg=PANEL, wraplength=430,
             justify="left").pack(anchor="w", pady=(10, 0))
    d.tombol("Batal", False, primer=False)
    d.tombol(f"Tutup {nama}", True, warna_btn=RED)
    return d.tampilkan()


def dialog_tips(induk, terdeteksi):
    d = _Dialog(induk, "Cara pakai TypingBot", ikon="💡")

    def bagian(judul, isi):
        f = tk.Frame(d.body, bg=PANEL)
        f.pack(fill="x", pady=(0, 8))
        tk.Label(f, text=judul, font=("Segoe UI", 10, "bold"), fg=ACCENT,
                 bg=PANEL).pack(anchor="w")
        for t in isi:
            tk.Label(f, text=t, font=("Segoe UI", 9), fg=FG, bg=PANEL,
                     anchor="w", justify="left", wraplength=450).pack(anchor="w")

    bagian("MULAI", (
        "1.  Klik Start, lalu login edclub sekali di jendela browser bot",
        "2.  Buka halaman pelajaran mana pun - bot langsung bekerja",
        "3.  Bot berhenti sendiri setelah level akhir yang kamu pilih",
    ))
    bagian("TOMBOL CEPAT (jalan dari mana saja)", (
        "F9 jeda/lanjut    •    F10 ganti kecepatan    •    F11 stop",
    ))
    bagian("CATATAN", (
        "Kecepatan bisa diganti kapan saja, bahkan saat bot sedang mengetik.",
        "Jendela browser boleh diminimize, bot tetap jalan di belakang.",
        "Pakai Brave dan penawaran premium tidak muncul? Klik ikon perisai "
        "di sebelah alamat, matikan Shields sebentar, lalu muat ulang halaman.",
        "Browser yang terdeteksi di komputer ini: " + terdeteksi + ".",
    ))
    d.tombol("Mengerti")
    return d.tampilkan()


def dialog_rentang(induk, mulai, akhir, jumlah_peta, total_level, on_bangun):
    """Pilih rentang level (dari/sampai) + status & tombol bangun peta."""
    hasil = {"mulai": mulai, "akhir": akhir}
    d = _Dialog(induk, "Rentang level", "Bot hanya mengerjakan level dalam "
                "rentang ini.", ikon="🎯")
    baris = tk.Frame(d.body, bg=PANEL)
    baris.pack(fill="x", pady=(0, 6))

    def kotak(induk2, label, nilai):
        f = tk.Frame(induk2, bg=PANEL)
        f.pack(side="left", padx=(0, 14))
        tk.Label(f, text=label, font=("Segoe UI", 9), fg=DIM, bg=PANEL).pack(anchor="w")
        var = tk.StringVar(value=str(nilai))
        ent = tk.Entry(f, textvariable=var, font=("Segoe UI", 12), width=7,
                       bg=CARD, fg=FG, insertbackground=FG, relief="flat",
                       highlightthickness=1, highlightbackground=EDGE,
                       highlightcolor=ACCENT, justify="center")
        ent.pack(ipady=5)
        return var

    var_a = kotak(baris, "Dari level", mulai)
    var_b = kotak(baris, "Sampai level", akhir or total_level)

    info = tk.Label(d.body, font=("Segoe UI", 9), fg=DIM, bg=PANEL,
                    wraplength=440, justify="left")

    def info_teks():
        info.configure(text=f"Peta level: {jumlah_peta['n']}/{total_level} "
                            f"terpetakan" + ("" if jumlah_peta["n"] >= total_level
                            else "  -  lompat ke level awal butuh peta; "
                            "klik Bangun Peta di bawah (sekali saja, ~15 menit)")
                            + "\nCatatan: level mengikuti progres akunmu - "
                            "level yang masih terkunci akan diminta konfirmasi "
                            "saat Start.")
    info_teks()
    info.pack(anchor="w")

    galat = tk.Label(d.body, text="", font=("Segoe UI", 9), fg=RED, bg=PANEL)
    galat.pack(anchor="w")

    def bangun():
        on_bangun()
        return False   # jangan tutup dialog; status terlihat di log

    d.tombol("Bangun Peta", None, primer=False, cmd=bangun)

    def simpan():
        try:
            a = int(var_a.get())
            b = int(var_b.get())
        except ValueError:
            galat.configure(text="Isi angka level (mis. 1 dan 685).")
            return False
        if not (1 <= a <= total_level and 1 <= b <= total_level and a <= b):
            galat.configure(text=f"Harus 1-{total_level}, dan Dari <= Sampai.")
            return False
        hasil["mulai"], hasil["akhir"] = a, b
        d.selesai(True)

    d.tombol("Simpan", None, cmd=simpan)
    return d.tampilkan() and hasil


def dialog_aktivasi(induk):
    """Aktivasi lisensi terikat mesin. Return True bila baru berhasil."""
    d = _Dialog(induk, "Aktivasi TypingBot",
                "Satu lisensi berlaku untuk satu komputer.", ikon="🔑",
                warna=ORANGE)
    kode = _kode_mesin()
    harapan = _norm(_buat_kunci(kode))

    kotak = tk.Frame(d.body, bg=CARD, highlightthickness=1,
                     highlightbackground=EDGE)
    kotak.pack(fill="x")
    kiri = tk.Frame(kotak, bg=CARD)
    kiri.pack(side="left", fill="both", expand=True, padx=12, pady=10)
    tk.Label(kiri, text="Kode mesin komputer ini:", font=("Segoe UI", 9),
             fg=DIM, bg=CARD).pack(anchor="w")
    tk.Label(kiri, text=kode, font=("Consolas", 15, "bold"), fg=FG,
             bg=CARD).pack(anchor="w", pady=(2, 0))
    salin = tk.Label(kotak, text="📋\nSalin", font=("Segoe UI", 9, "bold"),
                     fg=FG, bg=CARD_HOVER, padx=12, pady=12, cursor="hand2")
    salin.pack(side="right", padx=10, pady=10)

    def salin_klik(_e=None):
        induk.clipboard_clear()
        induk.clipboard_append(kode)
        salin.configure(text="✔\nTersalin")

    salin.bind("<Button-1>", salin_klik)

    tk.Label(d.body, text="Kirim kode mesin di atas ke pemberi aplikasi untuk "
                          "dapatkan kunci lisensi, lalu tempel di sini:",
             font=("Segoe UI", 9), fg=DIM, bg=PANEL,
             wraplength=440, justify="left").pack(anchor="w", pady=(12, 4))
    var = tk.StringVar()
    ent = tk.Entry(d.body, textvariable=var, font=("Consolas", 12),
                   bg=CARD, fg=FG, insertbackground=FG, relief="flat",
                   highlightthickness=1, highlightbackground=EDGE,
                   highlightcolor=ACCENT)
    ent.pack(fill="x", ipady=8, padx=1)
    galat = tk.Label(d.body, text="", font=("Segoe UI", 9), fg=RED, bg=PANEL)
    galat.pack(anchor="w", pady=(6, 0))

    def coba():
        if _norm(var.get()) == harapan:
            _simpan_lisensi(var.get())
            d.selesai(True)
            return
        galat.configure(text="Kunci tidak cocok untuk komputer ini. "
                             "Periksa lagi, atau minta kunci baru.")
        return False

    d.tombol("Nanti Saja", None, primer=False)
    d.tombol("Aktivasi", True, cmd=coba)
    ent.bind("<Return>", lambda e: coba())
    return d.tampilkan()


def dialog_selesai(induk, akhir):
    """Popup rentang level selesai (visual, senada tema gelap - bukan
    messagebox polos Windows)."""
    d = _Dialog(induk, "Semua level selesai!", ikon="🏁", warna=GREEN)
    tk.Label(d.body, text=f"Bot sudah menyelesaikan semua level sampai "
                          f"level {akhir}.\n\nKlik Start kapan saja untuk "
                          f"melanjutkan ke level berikutnya.",
             font=("Segoe UI", 10), fg=FG, bg=PANEL, wraplength=420,
             justify="left").pack(anchor="w")
    d.tombol("Oke")
    return d.tampilkan()


# ------------------------------------------------------------------- app
class App:
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
        self._login_grace = 0        # jeda re-popup login setelah tombol buka login
        self._profile = "bot"        # 'bot' khusus | 'saya' profil browser user
        self.lisensi_ok = _lisensi_valid()

        root.title("TypingBot")
        # ukuran jendela mengikuti DPI layar (dipanggil setelah
        # SetProcessDpiAwareness di __main__; skrip/uji tanpa itu = 1.0)
        try:
            k = float(root.tk.call("tk", "scaling")) / (96.0 / 72.0)
        except Exception:
            k = 1.0
        k = max(1.0, min(k, 2.0))
        root.geometry(f"{int(780 * k)}x{int(460 * k)}")
        # tinggi minimum KECIL: pengguna boleh mengecilkan jendela sampai
        # kecil - footer hotkey tetap tampak, hanya log yang menyusut
        root.minsize(int(700 * k), int(330 * k))
        root.configure(bg=BG)
        self._judul()

        try:
            root.attributes("-topmost", True)
            root.attributes("-topmost", False)
        except Exception:
            pass
        # ---------- zona atas: header status, baris tombol (+ kartu browser
        # ---------- persegi DI SAMPING Stop), lalu baris kecepatan ----------
        self._last_browser_path = ""   # exe terakhir yang dipakai mode Otomatis
        # browser_var WAJIB dibuat sebelum chip (chip membacanya saat render)
        self.browser_var = tk.StringVar(value="Otomatis")
        self.browser_dd = type(
            "_NoDD", (), {"set_values": lambda self, v: None,
                          "configure": lambda self, **kw: None})()

        head = tk.Frame(root, bg=BG)
        head.pack(fill="x", padx=18, pady=(16, 2))
        self.state_lbl = tk.Label(head, text="⏻ Siap", font=("Segoe UI", 15, "bold"),
                                  fg=FG, bg=BG)
        self.state_lbl.pack(side="left")
        self.ver_lbl = tk.Label(head, text=f"v{APP_VERSION}  •  build {_build_stamp()}",
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
        # ukuran dihitung dari ISI + jadi PERSEGI (auto, tahan DPI: ukuran
        # fix 132x96 px + font yang ikut scaling 125-150% = teks terpotong)
        self.chip = tk.Frame(ctrl, bg=CARD, highlightthickness=1,
                             highlightbackground=EDGE, cursor="hand2",
                             width=132, height=96)
        self.chip.pack(side="left", padx=(14, 0))
        self.chip.pack_propagate(False)
        self._perbarui_chip_browser()

        kanan = tk.Frame(ctrl, bg=BG)
        kanan.pack(side="right")
        self._btn(kanan, "❓", CARD, self.on_tips, kecil=True)

        # ---------- baris pengaturan: kecepatan ----------
        # Dropdown Browser DIHAPUS (permintaan user): pilihan browser lewat
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
        self._rentang_mulai, self._rentang_akhir = self._muat_rentang()
        self._total_level = 685
        self._rentang_btn = type("_NoBtn", (), {"configure": lambda self, **kw: None})()

        # ---------- footer: tombol cepat + saklar aktif/nonaktif ----------
        # DIPASANG PALING AWAL dengan side="bottom": widget yang di-pack
        # lebih awal mendapat jatah ukuran lebih dulu - saat jendela
        # dikecilkan vertikal, kartu aktivitas-lah yang menyusut, footer
        # selalu tampak (dulu footer di-pack terakhir -> teks terpotong
        # duluan; keluhan user).
        self._hotkey = True
        self.hotkey_lbl = tk.Label(root, text="", font=("Segoe UI", 9),
                                   fg=FAINT, bg=BG, cursor="hand2",
                                   wraplength=640, justify="center")
        self.hotkey_lbl.pack(side="bottom", fill="x", pady=(0, 8))
        self.hotkey_lbl.bind("<Button-1>", lambda e: self._safe(self._toggle_hotkey))
        self._perbarui_hotkey_lbl()

        # ---------- kartu aktivitas (mengisi sisa ruang tengah) ----------
        # Pengganti log lama (permintaan: user awam tidak perlu lihat log):
        # SATU kalimat besar bahasa awam - apa yang bot kerjakan sekarang.
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
            self._log(f"Lisensi aktif (mesin {_kode_mesin()}).")
        else:
            self._log(f"Lisensi belum aktif - kode mesin: {_kode_mesin()}")
            root.after(500, self._minta_lisensi)
        threading.Thread(target=self._load_bot, daemon=True).start()
        self.root.after(150, self._poll)

    def _judul(self):
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

    def _set_aktivitas(self, utama, sub):
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

    # ------------------------------------------------------------------ logging

    class _Writer:
        def __init__(self, app):
            self.app = app

        def write(self, s):
            if s and s.strip():
                self.app.log_q.put(s.rstrip("\n"))
            f = self.app.log_file
            if f:
                try:
                    f.write(s)
                    f.flush()
                except Exception:
                    pass
            return len(s)

        def flush(self):
            pass

    def _log(self, line):
        self.log_q.put(line)
        try:
            if self.log_file:
                self.log_file.write(line + "\n")
                self.log_file.flush()
        except Exception:
            pass

    def _poll(self):
        try:
            while True:
                fn = self._ui_queue.get_nowait()
                self._safe(fn)
        except queue.Empty:
            pass
        try:
            while True:
                line = self.log_q.get_nowait()
                ramah = _teks_ramah(line)
                if ramah:
                    self._aktiv_sub_teks = ramah
        except queue.Empty:
            pass

        bot = self.bot
        bot_thread_hidup = bool(self.bot_thread and self.bot_thread.is_alive())
        nama_level = ""
        if bot:
            url = getattr(bot, "STATUS_URL", "")
            # Indikator level: label ASLI dari teks halaman ("Lesson 87:").
            # Rumus URL lama (URL-115) salah untuk banyak akun - hanya
            # dipakai sebagai cadangan kalau label belum terbaca.
            label = getattr(bot, "STATUS_LABEL", "")
            if label.startswith("L"):
                nama_level = f"Level {label[1:]}"
            elif ".game" in url:
                nama_level = "Daftar pelajaran"
            else:
                # cadangan: peta terbalik id URL -> level (instan, pasti)
                lvl = None
                try:
                    lvl = bot.url_ke_level(url)
                except Exception:
                    pass
                if lvl:
                    nama_level = f"Level {lvl}"
                else:
                    m = re.search(r"/program-\d+/(\d+)\.play", url)
                    nama_level = f"Level ? (URL {m.group(1)})" if m else ""
            self._aktiv_nama = nama_level

            # popup 'login dulu': muncul saat sesi edclub mati, tertutup
            # sendiri saat sesi kembali aktif. TIDAK muncul lagi selama
            # user masih berada di halaman login (dia sedang mengerjakannya;
            # dulu popup muncul lagi di tengah user mengetik sandi).
            url_now = (getattr(bot, "STATUS_URL", "") or "").lower()
            di_halaman_login = any(k in url_now
                                   for k in ("signin", "login", "signup"))
            if getattr(bot, "PERLU_LOGIN", False):
                if (self._login_win is None and not self._login_dismiss
                        and not di_halaman_login
                        and time.time() > self._login_grace):
                    self._login_popup()
            elif self._login_win is not None:
                self._login_win.destroy()
                self._login_win = None
                self._login_grace = 0
                self._log("Login edclub aktif - bot lanjut bekerja.")
            elif self._login_dismiss:
                self._login_dismiss = False

            # >2 menit tanpa lesson karena user memakai browser bot
            if getattr(bot, "MINTA_TANYA_LANJUT", False) and self._tanya_win is None:
                bot.MINTA_TANYA_LANJUT = False
                self._tanya_dialog()

            # tanya rentang SETELAH tersambung + login dicek + tidak sedang
            # butuh login. Kalau user sudah berada dalam lesson -> pakai level
            # itu sebagai awal otomatis (tanpa popup). Kalau tidak -> dialog.
            if (self._tanya_rentang and bot_thread_hidup
                    and getattr(bot, "LOGIN_DICEK", False)
                    and not getattr(bot, "PERLU_LOGIN", False)
                    and getattr(bot, "STATUS_URL", "")):
                self._tanya_rentang = False
                lvl = 0
                try:
                    lvl = bot.url_ke_level(bot.STATUS_URL) or 0
                except Exception:
                    pass
                if lvl:
                    self._rentang_mulai = lvl
                    bot.LEVEL_START = lvl
                    bot._rentang_jump_done = True
                    bot.RENTANG_SIAP = True
                    self._rentang_btn.configure(
                        text=f"🎯  {lvl} - "
                             f"{self._rentang_akhir or self._total_level}")
                    self._log(f"[RENTANG] kamu sudah di level {lvl} - "
                              "mulai dari situ, lanjut otomatis.")
                else:
                    # tahan bot diam selama popup rentang terbuka (dulu:
                    # recovery malah membuka level terdepan akun)
                    bot.TUNGGU_RENTANG = True
                    try:
                        if self._buka_rentang():
                            bot.LEVEL_START = self._rentang_mulai
                            bot.LEVEL_END = self._rentang_akhir
                            bot.RENTANG_SELESAI = False
                            bot._rentang_jump_done = False
                            bot.RENTANG_SIAP = True
                        else:
                            # dilewati = jalan dari posisi sekarang; rentang
                            # lama TIDAK boleh dipakai (live: bot pernah
                            # melompat ke level 662 persis setelah login,
                            # sebelum user menjawab apapun)
                            bot.LEVEL_START = 1
                            bot.LEVEL_END = 0
                            bot.RENTANG_SELESAI = False
                            bot._rentang_jump_done = True
                            bot.RENTANG_SIAP = True
                            self._log("Rentang dilewati - bot jalan otomatis "
                                      "dari posisi sekarang.")
                    finally:
                        bot.TUNGGU_RENTANG = False

            # bot menanyakan level start yang terkunci
            tanya = getattr(bot, "LEVEL_TANYA", None)
            if tanya and tanya.get("aktif") and self._terkunci_win is None \
                    and not getattr(bot, "PERLU_LOGIN", False):
                self._terkunci_dialog(tanya)
            # login dibutuhkan -> dialog terkunci tidak relevan, tutup
            if getattr(bot, "PERLU_LOGIN", False) and self._terkunci_win is not None:
                try:
                    self._terkunci_win._tb_tutup() if hasattr(
                        self._terkunci_win, "_tb_tutup") else None
                except Exception:
                    pass
                self._terkunci_win.destroy()
                self._terkunci_win = None
                tanya2 = getattr(bot, "LEVEL_TANYA", None)
                if tanya2 and tanya2.get("aktif"):
                    tanya2["jawab"] = "mulai"
                    if tanya2.get("event") is not None:
                        tanya2["event"].set()
                self._log("[RENTANG] cek level terkunci ditunda sampai login.")

            # bot mencapai level akhir rentang -> popup sekali.
            # try: error di sini pernah membunuh _poll seluruhnya
            # (reschedule after(150) tak jalan -> status beku 'Berjalan').
            if getattr(bot, "RENTANG_SELESAI", False) and not self._selesai_info:
                self._selesai_info = True
                self._log("Rentang level selesai - bot berhenti sendiri.")
                try:
                    dialog_selesai(self.root, self._rentang_akhir
                                   or self._total_level)
                except Exception as ex:
                    self._log(f"[GUI] popup selesai gagal: {ex!r}")

            if not self.lisensi_ok:
                self._set_state("⚠ Perlu aktivasi", ORANGE)
            elif getattr(bot, "RENTANG_SELESAI", False):
                self._set_state("🏁 Selesai (rentang)", GREEN)
            elif not bot_thread_hidup:
                # TIDAK ada sesi bot berjalan: jangan tampilkan 'Berjalan'
                # (dulu: aplikasi baru dibuka langsung bilang Berjalan).
                if bot.STOP:
                    self._set_state("⏹ Berhenti", RED)
                else:
                    self._set_state("⏻ Siap", FAINT)
            elif getattr(bot, "MENUNGGU_SETUP", False):
                self._set_state("🧭 Menunggu set-up browser", YELLOW)
            elif getattr(bot, "PERLU_LOGIN", False):
                self._set_state("⚠ Menunggu login", YELLOW)
            elif bot.STOP:
                self._set_state("⏹ Berhenti", RED)
            elif bot.PAUSED:
                self._set_state("⏸ Jeda", YELLOW)
            else:
                self._set_state("● Berjalan", GREEN)

            # kartu aktivitas: kalimat besar mengikuti keadaan bot
            if not self.lisensi_ok:
                self._set_aktivitas("Perlu aktivasi",
                                    "Masukkan kunci aktivasi untuk memakai "
                                    "TypingBot.")
            elif getattr(bot, "RENTANG_SELESAI", False):
                self._set_aktivitas(
                    "Selesai!",
                    f"Semua level sampai level {self._rentang_akhir or self._total_level} "
                    "sudah dikerjakan. Klik Start untuk lanjut.")
            elif bot.PAUSED:
                self._set_aktivitas("Jeda",
                                    "Klik Lanjut atau tekan F9 untuk melanjutkan.")
            elif getattr(bot, "MENUNGGU_SETUP", False):
                self._set_aktivitas(
                    "Menyiapkan browser...",
                    "Selesaikan setelan awal di jendela browser, lalu tutup "
                    "halamannya.")
            elif getattr(bot, "PERLU_LOGIN", False):
                self._set_aktivitas("Menunggu login",
                                    "Selesaikan login edclub di jendela browser.")
            elif bot.STOP:
                self._set_aktivitas("Berhenti", "Klik Start untuk mulai lagi.")
            elif not bot_thread_hidup:
                self._set_aktivitas("Siap", "Klik Start untuk mulai.")
            elif nama_level:
                self._set_aktivitas(nama_level,
                                    self._aktiv_sub_teks
                                    or "Sedang dikerjakan otomatis.")
            else:
                self._set_aktivitas("Bot sedang bekerja",
                                    self._aktiv_sub_teks
                                    or "Buka pelajaran mana pun di jendela browser.")

            self.btn_pause.configure(
                text="⏸  Pause" if not bot.PAUSED else "▶  Lanjut")
            self.btn_pause["state"] = "normal" if self.bot_thread else "disabled"
            self.btn_stop["state"] = "normal" if self.bot_thread else "disabled"
            self.btn_start["state"] = "disabled" if self.bot_thread else "normal"
        else:
            self._set_aktivitas("Siap", "Klik Start untuk mulai.")

        self.root.after(150, self._poll)

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

    # ------------------------------------------------------ popup login edclub

    def _muat_rentang(self):
        try:
            s = json.load(open(SETTINGS_FILE, encoding="utf-8"))
            return int(s.get("start", 1)), int(s.get("end", 0))
        except Exception:
            return 1, 0

    def on_rentang(self):
        """Buka dialog rentang (dipakai alur Start; tidak ada tombol GUI)."""
        self._buka_rentang()

    def _buka_rentang(self):
        """Dialog rentang level. Return False bila user membatalkan (dipakai
        alur Start: batal = jangan mulai bot)."""
        bot = self.bot
        jumlah = {"n": 0}
        if bot:
            try:
                jumlah["n"] = len(bot._level_map)
            except Exception:
                pass

        def on_bangun():
            if not bot:
                self._log("Klik Start dulu, lalu bangun peta.")
                return
            if not self.bot_thread or not self.bot_thread.is_alive():
                self._log("Bot belum berjalan - klik Start dulu, "
                          "lalu Bangun Peta.")
                return
            bot.MINTA_BANGUN_PETA = True
            self._log("Membangun peta level di latar belakang "
                      "(lihat progres [PETA] di log / jangan Stop).")

        hasil = dialog_rentang(self.root, self._rentang_mulai,
                               self._rentang_akhir, jumlah,
                               self._total_level, on_bangun)
        if hasil is None:
            return False
        self._rentang_mulai = hasil["mulai"]
        self._rentang_akhir = hasil["akhir"]
        self._rentang_btn.configure(
            text=f"🎯  {self._rentang_mulai} - "
                 f"{self._rentang_akhir or self._total_level}")
        try:
            s = json.load(open(SETTINGS_FILE, encoding="utf-8"))
        except Exception:
            s = {}
        s["start"] = self._rentang_mulai
        s["end"] = self._rentang_akhir
        try:
            json.dump(s, open(SETTINGS_FILE, "w", encoding="utf-8"))
        except Exception:
            pass
        self._log(f"Rentang level: {self._rentang_mulai} - "
                  f"{self._rentang_akhir or 'akhir kursus'}.")
        return True

    def _terkunci_dialog(self, tanya):
        """Popup 'level start terkunci' - jawaban dikirim balik ke bot."""
        if self._terkunci_win is not None:
            return
        bot = self.bot
        win = tk.Toplevel(self.root)
        self._terkunci_win = win
        win.title("Level terkunci")
        win.configure(bg=PANEL)
        win.resizable(False, False)
        try:
            win.attributes("-topmost", True)
        except Exception:
            pass

        def jawab(pilihan):
            tanya["jawab"] = pilihan
            if tanya.get("event") is not None:
                tanya["event"].set()
            self._terkunci_win = None
            try:
                win.destroy()
            except Exception:
                pass

        head = tk.Frame(win, bg=PANEL)
        head.pack(fill="x", padx=24, pady=(20, 4))
        box = tk.Canvas(head, width=46, height=46, bg=PANEL, highlightthickness=0)
        box.pack(side="left")
        box.create_oval(2, 2, 44, 44, fill=ORANGE, width=0)
        box.create_text(23, 25, text="🔒", font=("Segoe UI Emoji", 15, "bold"),
                        fill="white")
        jt = tk.Frame(head, bg=PANEL)
        jt.pack(side="left", padx=(14, 0))
        tk.Label(jt, text=f"Level {tanya['start']} masih terkunci",
                 font=("Segoe UI", 14, "bold"), fg=FG, bg=PANEL).pack(anchor="w")
        tk.Label(jt, text="Akunmu baru terbuka sampai level "
                          f"{tanya['fallback']} - level terkunci memuat "
                          "halaman kosong.",
                 font=("Segoe UI", 9), fg=DIM, bg=PANEL, wraplength=360,
                 justify="left").pack(anchor="w", pady=(2, 0))
        body = tk.Frame(win, bg=PANEL)
        body.pack(fill="x", padx=24, pady=12)
        tk.Label(body, text=f"Mulai dari level {tanya['fallback']} "
                            "(posisi terdepan akunmu) sekarang?",
                 font=("Segoe UI", 10), fg=FG, bg=PANEL,
                 wraplength=420, justify="left").pack(anchor="w")
        foot = tk.Frame(win, bg=PANEL)
        foot.pack(fill="x", padx=24, pady=(4, 18))
        b1 = tk.Label(foot, text=f"Mulai dari {tanya['fallback']}",
                      font=("Segoe UI", 10, "bold"), fg=BTN_FG, bg=ACCENT,
                      padx=18, pady=7, cursor="hand2")
        b1.pack(side="right")
        b1.bind("<Button-1>", lambda e: jawab("mulai"))
        b1._tb_klik = lambda: jawab("mulai")
        b2 = tk.Label(foot, text="Stop", font=("Segoe UI", 10, "bold"),
                      fg=FG, bg=CARD, padx=16, pady=7, cursor="hand2",
                      highlightthickness=1, highlightbackground=EDGE)
        b2.pack(side="right", padx=(0, 8))
        b2.bind("<Button-1>", lambda e: jawab("stop"))
        b2._tb_klik = lambda: jawab("stop")
        win.protocol("WM_DELETE_WINDOW", lambda: jawab("mulai"))
        win.update_idletasks()
        ix, iy = self.root.winfo_rootx(), self.root.winfo_rooty()
        iw, ih = self.root.winfo_width(), self.root.winfo_height()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        win.geometry(f"+{max(ix + (iw - w) // 2, 40)}+{max(iy + (ih - h) // 2, 40)}")

    def _tanya_dialog(self):
        """Popup 'bot menunggu >2 menit' - dibangun di thread UI (Tkinter
        tidak boleh dari thread lain), pola sama dengan _login_popup."""
        bot = self.bot
        win = tk.Toplevel(self.root)
        self._tanya_win = win
        win.title("Bot menunggu")
        win.configure(bg=PANEL)
        win.resizable(False, False)
        try:
            win.attributes("-topmost", True)
        except Exception:
            pass

        def selesai(stop=False):
            self._tanya_win = None
            try:
                win.destroy()
            except Exception:
                pass
            if stop and bot:
                bot.STOP = True
                bot.PAUSED = False
                self._log("Bot dihentikan dari popup 'menunggu'.")

        head = tk.Frame(win, bg=PANEL)
        head.pack(fill="x", padx=24, pady=(20, 4))
        box = tk.Canvas(head, width=46, height=46, bg=PANEL, highlightthickness=0)
        box.pack(side="left")
        box.create_oval(2, 2, 44, 44, fill=YELLOW, width=0)
        box.create_text(23, 25, text="⏳", font=("Segoe UI Emoji", 16, "bold"),
                        fill="white")
        jt = tk.Frame(head, bg=PANEL)
        jt.pack(side="left", padx=(14, 0))
        tk.Label(jt, text="Bot menunggu", font=("Segoe UI", 14, "bold"),
                 fg=FG, bg=PANEL).pack(anchor="w")
        tk.Label(jt, text="Lebih dari 2 menit tidak ada lesson terbuka.",
                 font=("Segoe UI", 9), fg=DIM, bg=PANEL,
                 wraplength=360, justify="left").pack(anchor="w", pady=(2, 0))

        body = tk.Frame(win, bg=PANEL)
        body.pack(fill="x", padx=24, pady=12)
        for t in ("•  Sepertinya kamu sedang memakai jendela browser bot",
                  "•  Bot jalan lagi otomatis begitu kamu membuka lesson "
                  "atau berhenti memakai browser itu"):
            tk.Label(body, text=t, font=("Segoe UI", 10), fg=FG, bg=PANEL,
                     anchor="w", wraplength=420,
                     justify="left").pack(anchor="w", pady=1)

        foot = tk.Frame(win, bg=PANEL)
        foot.pack(fill="x", padx=24, pady=(4, 18))
        b1 = tk.Label(foot, text="Stop Bot", font=("Segoe UI", 10, "bold"),
                      fg=BTN_FG, bg=RED, padx=18, pady=7, cursor="hand2")
        b1.pack(side="right")
        b1.bind("<Button-1>", lambda e: selesai(stop=True))
        b2 = tk.Label(foot, text="Lanjut Menunggu", font=("Segoe UI", 10, "bold"),
                      fg=FG, bg=CARD, padx=16, pady=7, cursor="hand2",
                      highlightthickness=1, highlightbackground=EDGE)
        b2.pack(side="right", padx=(0, 8))
        b2.bind("<Button-1>", lambda e: selesai(stop=False))

        win.protocol("WM_DELETE_WINDOW", lambda: selesai(stop=False))
        win.update_idletasks()
        ix, iy = self.root.winfo_rootx(), self.root.winfo_rooty()
        iw, ih = self.root.winfo_width(), self.root.winfo_height()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        win.geometry(f"+{max(ix + (iw - w) // 2, 40)}+{max(iy + (ih - h) // 2, 40)}")

    def _login_popup(self):
        """Jendela 'login dulu': muncul saat bot mendeteksi sesi edclub mati.
        Tertutup otomatis begitu sesi aktif kembali (dicek tiap poll)."""
        bot = self.bot
        win = tk.Toplevel(self.root)
        self._login_win = win
        win.title("Login edclub diperlukan")
        win.configure(bg=PANEL)
        win.resizable(False, False)
        try:
            win.attributes("-topmost", True)
            win.lift()
            win.focus_force()
        except Exception:
            pass

        head = tk.Frame(win, bg=PANEL)
        head.pack(fill="x", padx=24, pady=(20, 4))
        box = tk.Canvas(head, width=46, height=46, bg=PANEL, highlightthickness=0)
        box.pack(side="left")
        box.create_oval(2, 2, 44, 44, fill=YELLOW, width=0)
        box.create_text(23, 25, text="🔑", font=("Segoe UI Emoji", 16, "bold"),
                        fill="white")
        jt = tk.Frame(head, bg=PANEL)
        jt.pack(side="left", padx=(14, 0))
        tk.Label(jt, text="Login edclub dulu", font=("Segoe UI", 14, "bold"),
                 fg=FG, bg=PANEL).pack(anchor="w")
        tk.Label(jt, text="Sesi login mati atau belum login - kemajuan level "
                          "tidak tersimpan.",
                 font=("Segoe UI", 9), fg=DIM, bg=PANEL,
                 wraplength=360, justify="left").pack(anchor="w", pady=(2, 0))

        body = tk.Frame(win, bg=PANEL)
        body.pack(fill="x", padx=24, pady=12)
        langkah = (
            ("1", "Klik tombol kuning \"Buka Halaman Login\" di bawah"),
            ("2", "Login seperti biasa di jendela browser bot "
                  "(akun sekolah / Google / Microsoft)"),
            ("3", "Selesai - jendela ini tertutup otomatis, bot lanjut"),
        )
        for nomor, teks in langkah:
            baris = tk.Frame(body, bg=PANEL)
            baris.pack(anchor="w", pady=3)
            c = tk.Canvas(baris, width=22, height=22, bg=PANEL,
                          highlightthickness=0)
            c.pack(side="left")
            c.create_oval(1, 1, 21, 21, fill=ACCENT, width=0)
            c.create_text(11, 12, text=nomor, font=("Segoe UI", 9, "bold"),
                          fill="white")
            tk.Label(baris, text=teks, font=("Segoe UI", 10), fg=FG, bg=PANEL,
                     anchor="w", wraplength=380, justify="left").pack(
                side="left", padx=(10, 0))
        tk.Label(body, text="Klik kuning = login Individual Edition (email & "
                            "sandi); \"Akun Sekolah\" = portal sekolah "
                            "(login Google/Clever).",
                 font=("Segoe UI", 8), fg=FAINT, bg=PANEL, wraplength=420,
                 justify="left").pack(anchor="w", pady=(8, 0))
        tk.Label(body, text="Sekali login cukup - profil bot mengingatnya. "
                            "Jendela ini hanya muncul kalau sesi benar-benar mati.",
                 font=("Segoe UI", 8), fg=FAINT, bg=PANEL, wraplength=420,
                 justify="left").pack(anchor="w", pady=(8, 0))

        foot = tk.Frame(win, bg=PANEL)
        foot.pack(fill="x", padx=24, pady=(4, 18))

        def buka_login(url):
            if bot:
                bot.MINTA_LOGIN_URL = url
                bot.MINTA_LOGIN_NAV = True
                self._log(f"Membuka halaman login di jendela browser bot: {url}")
                # angkat jendela browser ke depan SETELAH navigasi bot
                # dimulai (delay pendek); GUI baru menerima klik = punya
                # izin foreground di Windows.
                self.root.after(1200, _fokus_jendela_browser)
            # Popup ditutup: user sudah memilih pergi ke halaman login.
            # Kalau login tidak dilakukan, popup muncul lagi setelah 3
            # menit (selama user masih di halaman login, tidak muncul).
            self._login_grace = time.time() + 180
            self._login_win = None
            try:
                win.destroy()
            except Exception:
                pass

        b1 = tk.Label(foot, text="Buka Halaman Login", font=("Segoe UI", 10, "bold"),
                      fg=BTN_FG, bg=YELLOW, padx=18, pady=7, cursor="hand2")
        b1.pack(side="right")
        b1.bind("<Button-1>", lambda e: self._safe(
            lambda: buka_login(bot.LOGIN_URL_INDIVIDU if bot else "")))
        b1._tb_klik = lambda: buka_login(bot.LOGIN_URL_INDIVIDU if bot else "")

        b15 = tk.Label(foot, text="Akun Sekolah", font=("Segoe UI", 9, "bold"),
                       fg=FG, bg=CARD, padx=12, pady=7, cursor="hand2",
                       highlightthickness=1, highlightbackground=EDGE)
        b15.pack(side="right", padx=(0, 8))
        b15.bind("<Button-1>", lambda e: self._safe(
            lambda: buka_login(bot.LOGIN_URL_SEKOLAH if bot else "")))
        b15._tb_klik = lambda: buka_login(bot.LOGIN_URL_SEKOLAH if bot else "")

        def tutup():
            self._login_dismiss = True
            win.destroy()
            self._login_win = None

        b2 = tk.Label(foot, text="Tutup", font=("Segoe UI", 10, "bold"),
                      fg=FG, bg=CARD, padx=16, pady=7, cursor="hand2",
                      highlightthickness=1, highlightbackground=EDGE)
        b2.pack(side="right", padx=(0, 8))
        b2.bind("<Button-1>", lambda e: tutup())

        win.update_idletasks()
        ix, iy = self.root.winfo_rootx(), self.root.winfo_rooty()
        iw, ih = self.root.winfo_width(), self.root.winfo_height()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        win.geometry(f"+{max(ix + (iw - w) // 2, 40)}+{max(iy + (ih - h) // 2, 40)}")

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
        except Exception:
            pass
        try:
            self.root.after(0, self._perbarui_chip_browser)
        except Exception:
            pass
        self._first_run = not os.path.exists(SETTINGS_FILE)
        self._log("Browser terdeteksi: "
                  + (", ".join(n for n, _ in det) or "tidak ada"))

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
            baris.append(f"Port 9222     : "
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
        ok = dialog_buka_browser(self.root, nm, det.get(nm))
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

    # ------------------------------------------------------------------ start

    def _perbarui_hotkey_lbl(self):
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
        self._simpan_pengaturan()
        self._perbarui_hotkey_lbl()
        if self.bot:
            self.bot.HOTKEY_AKTIF = self._hotkey
        self._log("Hotkey global F9/F10/F11 "
                  + ("diaktifkan." if self._hotkey else "DIMATIKAN."))

    def _simpan_pengaturan(self):
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
        if self._last_browser_path:
            data["last_browser"] = self._last_browser_path
        try:
            json.dump(data, open(SETTINGS_FILE, "w", encoding="utf-8"))
        except Exception:
            pass

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
        # keterangan profil: hanya relevan untuk Brave (satu2nya browser
        # yang bisa memakai profil user) - singkat supaya muat di kartu
        if self._profile == "saya" and label in ("Otomatis", "Brave"):
            sub = "pakai profilmu" if sub == "klik untuk ganti" \
                else sub + " • profilmu"
        isi = tk.Frame(self.chip, bg=CARD)
        isi.pack(expand=True, fill="both")
        # ukuran ikon & wrap disesuaikan kartu 132x96 (teks TIDAK boleh
        # terpotong - keluhan user; label pendek + wraplength)
        ikon = _ikon_widget(isi, path, pilih, BROWSER_WARNA.get(pilih, "#7c5cff"),
                            42, char="⚡" if pilih == "Otomatis" else None)
        ikon.pack(pady=(5, 0))
        tk.Label(isi, text=label, font=("Segoe UI", 10, "bold"),
                 fg=FG, bg=CARD, wraplength=118).pack()
        tk.Label(isi, text=sub, font=("Segoe UI", 8), fg=DIM,
                 bg=CARD, wraplength=118).pack(pady=(0, 3))
        # ukuran kartu DARI ISI -> persegi (auto, tahan DPI). Ukuran fix px
        # + font 125-150% = teks terpotong (keluhan user 2x).
        try:
            isi.update_idletasks()
            wj = max(isi.winfo_reqwidth(), ikon.winfo_reqwidth()) + 18
            hj = isi.winfo_reqheight() + 14
            sisi = max(wj, hj, 96)
            self.chip.configure(width=sisi, height=sisi)
        except Exception:
            pass
        # bind klik + hover ke frame dan SEMUA anak (anak menelan event kalau
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

    def _ganti_browser(self):
        """Klik chip browser: buka popup kartu logo untuk mengganti."""
        hasil = dialog_pilih_browser(self.root, self._detected,
                                     self.browser_var.get(), self._profile)
        if hasil is None:
            return
        nama, profil = hasil
        self.browser_var.set(nama)
        self._profile = profil
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
        # Rentang level ditanyakan SETELAH tersambung & login diketahui
        # (bukan sebelum Start) - lihat _poll.
        self._tanya_rentang = True
        # Popup pilih browser hanya PERTAMA kali (belum ada pengaturan).
        # Setelah itu pilihan tersimpan; ganti lewat chip di tengah atas.
        if self._first_run:
            hasil = dialog_pilih_browser(self.root, self._detected,
                                         self.browser_var.get(), self._profile)
            if hasil is None:
                return
            self.browser_var.set(hasil[0])
            self._profile = hasil[1]
            self._first_run = False
        pilih = self.browser_var.get()
        # mode profil: berlaku ke engine sebelum koneksi dibuat
        if hasattr(bot, "PROFILE_MODE"):
            bot.PROFILE_MODE = self._profile
        deteksi = bot._find_browser() or {}
        # Otomatis: beri tahu engine browser terakhir yang dipakai
        bot.LAST_BROWSER = self._last_browser_path if pilih == "Otomatis" else ""
        bot.FORCE_BROWSER = next((p for n, p in self._detected if n == pilih), "")
        self._simpan_pengaturan()
        self._perbarui_chip_browser()
        # Konfirmasi 'buka browser?' TEPAT saat bot akan MELUNCURKAN jendela
        # browser: port mati (bot membuka baru), ATAU port dipegang browser/
        # aplikasi LAIN (ditutup dulu, lalu bot membuka pilihan user - dulu
        # kasus ini tidak dikonfirmasi, keluhan user). Kalau port sudah
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
                                       self._profile):
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
            self._log("Bot sedang berhenti... kalau masih menyambung, "
              "tunggu beberapa detik.")

    def on_speed(self, _=None):
        if not self.bot:
            return
        idx = {"Normal (140)": 0, "Cepat (200)": 1, "Santai (85)": 2}.get(self.speed_var.get(), 0)
        self.bot.SPEED_IDX = idx

    def on_close(self):
        if self.bot:
            self.bot.STOP = True
            self.bot.PAUSED = False
        time.sleep(0.2)
        self.root.destroy()


if __name__ == "__main__":
    # DPI awareness WAJIB sebelum Tk dibuat: tanpa ini Windows merender app
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
