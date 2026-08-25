"""Ikon browser dari file .exe + gambar vektor fallback."""

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

from .theme import ACCENT




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
    glyph-nya suka miring dalam kotak em-nya)."""
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
        # glyph-nya duduk miring di kotak em -)
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
    tampak miring/off-center."""
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
        # logo tampak geser;)
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
