"""Semua dialog: pilih browser/profil, rentang, aktivasi, dll."""

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

from .icons import _icon_widget, user32
from .licensing import (_make_key, _machine_code, _norm, _save_license)
from .theme import (ACCENT, BROWSER_COLORS, CARD, CARD_HOVER, DIM, EDGE, FAINT, FG, GREEN, ORANGE, PANEL, RED, YELLOW)
from .translator import _display_name
from .widgets import _Dialog




def _focus_browser_window():
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




def dialog_pick_browser(induk, detected, dipilih="Otomatis", profil="bot"):
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
        # Dimensi kartu seragam (fixed + propagate off): dulu lebar mengikuti
        # isi -> tiap kartu beda ukuran .
        wrap = tk.Frame(baris, bg=CARD, highlightthickness=1,
                        highlightbackground=EDGE, cursor="hand2",
                        width=128, height=118)
        wrap.pack(side="left", padx=5)
        wrap.pack_propagate(False)
        dalam = tk.Frame(wrap, bg=CARD)
        dalam.pack(expand=True, fill="both", padx=8, pady=(10, 8))
        _icon_widget(dalam, path, nama, BROWSER_COLORS.get(nama, "#7c5cff"),
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
                     "Bot memakai salah satu profil browser kamu "
                     "(login & data ikut terpakai). Pilih profilmu "
                     "setelah ini.")

    def sinkron_profil():
        # semua browser didukung (Chrome/Edge via pintasan folder,
        # Brave langsung) - tidak ada lagi yang perlu dikunci
        pilih_profil(d.profil)

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
    # Batal harus None eksplisit: tombol() tanpa nilai mengembalikan teks
    # tombol ("Batal", truthy) - dulu pemanggil menganggapnya pilihan sah.
    d.button("Batal", None, primer=False, cmd=lambda: d.done(None))
    d.button("Pilih", None, cmd=lambda: d.done((d.pilihan, d.profil)))
    return d.show()




def dialog_pick_profile(induk, nama_browser, daftar, dipilih_dir=""):
    """Pilih profil manusia milik browser (dibaca dari 'Local State'-nya:
    nama profil + email). Return dict {'dir','nama','email'} atau None.
    daftar kosong -> tampil pesan dan return None."""
    if not daftar:
        d = _Dialog(induk, f"Profil {nama_browser} tidak terbaca",
                    "Bot tidak menemukan daftar profilnya.", ikon="⚠",
                    warna=YELLOW)
        tk.Label(d.body, text=f"Pastikan {nama_browser} pernah dibuka "
                              "minimal sekali di komputer ini, lalu coba "
                              "lagi. Sementara bot memakai profil khusus "
                              "bot.",
                 font=("Segoe UI", 10), fg=FG, bg=PANEL, wraplength=420,
                 justify="left").pack(anchor="w")
        d.button("Oke")
        d.show()
        return None
    d = _Dialog(induk, f"Pilih profilmu di {nama_browser}",
                "Bot memakai profil ini - login edclub kamu di situ "
                "langsung terpakai.", ikon="👤")
    d.hasil_profil = next((p for p in daftar if p["dir"] == dipilih_dir),
                          daftar[0])
    baris_profil = []

    def pick_row(p):
        d.hasil_profil = p
        for st, render in baris_profil:
            st["on"] = st["p"] is p
            render()

    PALET = ("#4f8cff", "#3ecf6e", "#e8b339", "#e05555", "#a78bfa",
             "#2dd4bf", "#fb923c", "#f472b6")

    def make_row(p, ix):
        # scope per baris (fungsi terpisah): semua closure (klik/render/
        # hover) harus melihat p yang benar - dulu loop langsung di badan
        # dialog -> semua baris memanggil pick_row(profil terakhir),
        # jadi pilihan selalu loncat ke satu profil yang sama (keluhan
        # user: 'dipaksa zafran').
        wrap = tk.Frame(d.body, bg=CARD, highlightthickness=1,
                        highlightbackground=EDGE, cursor="hand2")
        wrap.pack(fill="x", pady=3)
        dalam = tk.Frame(wrap, bg=CARD)
        dalam.pack(fill="x", padx=10, pady=8)
        warna_avatar = PALET[ix % len(PALET)]
        huruf = (p["nama"][:1] or "?").upper()
        av = tk.Canvas(dalam, width=30, height=30, bg=CARD,
                       highlightthickness=0)
        av.pack(side="left")
        av.create_oval(1, 1, 29, 29, fill=warna_avatar, width=0)
        av.create_text(15, 16, text=huruf, font=("Segoe UI", 11, "bold"),
                       fill="white")
        tx = tk.Frame(dalam, bg=CARD)
        tx.pack(side="left", padx=(10, 0))
        judul = p["nama"] + ("   (profil utama)" if p.get("utama") else "")
        nm = tk.Label(tx, text=judul, font=("Segoe UI", 10, "bold"),
                      fg=FG, bg=CARD, anchor="w")
        nm.pack(anchor="w")
        if p.get("email"):
            tk.Label(tx, text=p["email"], font=("Segoe UI", 8), fg=DIM,
                     bg=CARD, anchor="w").pack(anchor="w")
        semua = [wrap, dalam, tx, nm] + tx.winfo_children() + [av]
        st = {"p": p, "on": False}

        def render():
            for wdgt in semua:
                try:
                    wdgt.configure(bg=CARD_HOVER if st["on"] else CARD)
                except Exception:
                    pass
            nm.configure(fg=FG)
            wrap.configure(highlightbackground=ACCENT if st["on"] else EDGE)

        def klik(_e=None):
            pick_row(p)

        def hover(_e):
            if not st["on"]:
                for wdgt in semua:
                    try:
                        wdgt.configure(bg=CARD_HOVER)
                    except Exception:
                        pass

        def leave(_e):
            render()

        for wdgt in semua:
            wdgt.bind("<Button-1>", klik)
            wdgt.bind("<Enter>", hover)
            wdgt.bind("<Leave>", leave)
        baris_profil.append((st, render))
        render()

    for ix, p in enumerate(daftar):
        make_row(p, ix)
    pick_row(d.hasil_profil)

    # Batal = None eksplisit (bukan teks tombol yang truthy - lihat
    # dialog_pick_browser); None = batal -> pemanggil pakai profil khusus.
    d.button("Batal", None, primer=False, cmd=lambda: d.done(None))
    d.button("Pilih Profil", None,
             cmd=lambda: d.done(dict(d.hasil_profil)))
    return d.show()




def dialog_open_browser(induk, nama, path, profil="bot", profil_label=""):
    """Konfirmasi visual sebelum bot membuka jendela browser sendiri."""
    d = _Dialog(induk, f"Buka {nama} untuk bot?",
                "TypingBot akan membuka jendela browser khusus.", ikon="🚀")
    atas = tk.Frame(d.body, bg=PANEL)
    atas.pack(fill="x")
    _icon_widget(atas, path, nama, BROWSER_COLORS.get(nama, ACCENT), 44).pack(side="left")
    tx = tk.Frame(atas, bg=PANEL)
    tx.pack(side="left", padx=(14, 0))

    if profil == "saya":
        daftar_teks = (
            f"•  Bot memakai profil '{profil_label or 'pilihanmu'}' - "
            "login & data kamu ikut terpakai",
            "•  Kalau browser ini sedang jalan, TypingBot minta izin "
            "menutupnya dulu",
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
    d.button("Batal", False, primer=False)
    d.button(f"Buka {nama}", True)
    return d.show()




def dialog_force_close(induk, nama, pid, exe=None):
    """Konfirmasi sebelum menutup aplikasi lain yang menghalangi bot.
    Bahasa awam total ('Brave sedang jalan, tutup dulu ya') - tanpa kata
    port/PID/proses. Menampilkan LOGO aplikasi yang akan ditutup
    (diekstrak dari exe-nya, mis. logo Adobe kalau yang jalan
    komponennya Adobe)."""
    nama = _display_name(nama)
    d = _Dialog(induk, f"Tutup {nama} dulu, ya",
                "TypingBot baru bisa jalan setelah aplikasi ini ditutup.",
                ikon="⚠", warna=RED)
    atas = tk.Frame(d.body, bg=PANEL)
    atas.pack(fill="x", pady=(2, 0))
    _icon_widget(atas, exe, nama, ACCENT, 44).pack(side="left")
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
    d.button("Batal", False, primer=False)
    d.button(f"Tutup {nama}", True, warna_btn=RED)
    return d.show()




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
    d.button("Mengerti")
    return d.show()




def dialog_range(induk, mulai, akhir, jumlah_peta, total_level, on_bangun):
    """Pilih rentang level (dari/sampai). Return: dict hasil (Simpan),
    'halaman' (user memilih level awal sendiri di browser), None (batal)."""
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
        # peta 685 level sudah tertanam di dalam aplikasi - pengguna tidak
        # perlu membangun apa pun. Teks bangun peta hanya utk kasus khusus
        # (kursus berbeda -> peta belum lengkap).
        info.configure(text=
            ("Level yang masih terkunci akan dikonfirmasi saat mulai.\n"
             "Tidak yakin angkanya? Klik Pilih di Halaman, lalu buka "
             "pelajaran pilihanmu di browser - bot mulai dari situ.")
            if jumlah_peta["n"] >= total_level else
            (f"Peta level: {jumlah_peta['n']}/{total_level} terpetakan - "
             "klik Bangun Peta (sekali saja, ~15 menit).\n"
             "Level yang masih terkunci akan dikonfirmasi saat mulai."))
    info_teks()
    info.pack(anchor="w")

    galat = tk.Label(d.body, text="", font=("Segoe UI", 9), fg=RED, bg=PANEL)
    galat.pack(anchor="w")

    # Bangun Peta disembunyikan saat peta lengkap (dulu wajib sebelum ada
    # peta tertanam; tombol yang tampil malah membingungkan user - keluhan).
    if jumlah_peta["n"] < total_level:
        def bangun():
            on_bangun()
            return False   # jangan tutup dialog; status terlihat di log
        d.button("Bangun Peta", None, primer=False, cmd=bangun)

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
        d.done(True)

    d.button("Pilih di Halaman", "halaman", primer=False)
    d.button("Simpan", None, cmd=simpan)
    r = d.show()
    return r if r == "halaman" else (r and hasil)




def dialog_activation(induk):
    """Aktivasi lisensi terikat mesin. Return True bila baru berhasil."""
    d = _Dialog(induk, "Aktivasi TypingBot",
                "Satu lisensi berlaku untuk satu komputer.", ikon="🔑",
                warna=ORANGE)
    kode = _machine_code()
    harapan = _norm(_make_key(kode))

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
            _save_license(var.get())
            d.done(True)
            return
        galat.configure(text="Kunci tidak cocok untuk komputer ini. "
                             "Periksa lagi, atau minta kunci baru.")
        return False

    # 'Nanti Saja' harus False eksplisit: tombol() tanpa nilai
    # mengembalikan teks tombol (truthy) - dulu menekan 'Nanti Saja'
    # malah dianggap aktivasi berhasil oleh pemanggil (bug lisensi!).
    d.button("Nanti Saja", None, primer=False, cmd=lambda: d.done(False))
    d.button("Aktivasi", True, cmd=coba)
    ent.bind("<Return>", lambda e: coba())
    return d.show()




def dialog_done(induk, akhir):
    """Popup rentang level selesai (visual, senada tema gelap - bukan
    messagebox polos Windows)."""
    d = _Dialog(induk, "Semua level selesai!", ikon="🏁", warna=GREEN)
    tk.Label(d.body, text=f"Bot sudah menyelesaikan semua level sampai "
                          f"level {akhir}.\n\nKlik Start kapan saja untuk "
                          f"melanjutkan ke level berikutnya.",
             font=("Segoe UI", 10), fg=FG, bg=PANEL, wraplength=420,
             justify="left").pack(anchor="w")
    d.button("Oke")
    return d.show()
