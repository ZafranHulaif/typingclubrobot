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
from . import anim
from .theme import (ACCENT, BROWSER_COLORS, CARD, CARD_HOVER, CREATOR, DIM, EDGE, FAINT, FG, GREEN, ORANGE, PANEL, RED, YELLOW)
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
        # Izin foreground: SetForegroundWindow dari timer GUI sering
        # DITOLAK Windows kalau app sedang tidak pegang fokus (browser
        # minimized = user tidak melihat apa pun -> login tak pernah
        # terangkat). Trick standar: ikat thread input ke thread jendela
        # foreground saat ini, plus ketukan ALT singkat, supaya OS
        # mengizinkan perpindahan fokus.
        fg = user32.GetForegroundWindow()
        fg_thread = 0
        my_thread = kernel32.GetCurrentThreadId()
        if fg:
            fg_thread = user32.GetWindowThreadProcessId(fg, None)
        if fg_thread and fg_thread != my_thread:
            user32.AttachThreadInput(my_thread, fg_thread, True)
        user32.keybd_event(0x12, 0, 0, 0)      # ALT down
        try:
            for _pilih_edclub, hwnd in temuan[:3]:
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE (kalau diminimalkan)
                user32.SetForegroundWindow(hwnd)
                if user32.GetForegroundWindow() == hwnd:
                    return True
        finally:
            user32.keybd_event(0x12, 0, 2, 0)  # ALT up
            if fg_thread and fg_thread != my_thread:
                user32.AttachThreadInput(my_thread, fg_thread, False)
    except Exception:
        pass
    # jalan terakhir: SwitchToThisWindow memaksa perpindahan tanpa syarat
    try:
        if temuan:
            user32.SwitchToThisWindow(temuan[0][1], True)
            return user32.GetForegroundWindow() == temuan[0][1]
    except Exception:
        pass
    return False


def _minimize_browser_windows():
    """Kecilkan jendela browser bot (judul edclub) kembali ke belakang -
    dipakai tepat setelah login selesai: bot mengetik via CDP tanpa perlu
    jendela di depan, jadi browser tidak mengganggu dan status aplikasi
    yang terlihat user. HANYA jendela berjudul edclub/typingclub -
    jendela browser pribadi user tidak disentuh."""
    try:
        user32_ = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        kandidat = {"brave.exe", "chrome.exe", "msedge.exe"}

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum_cb(hwnd, _l):
            try:
                if not user32_.IsWindowVisible(hwnd):
                    return True
                pid = wintypes.DWORD()
                user32_.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                h = kernel32.OpenProcess(0x1000, False, pid.value)
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
                    user32_.GetWindowTextW(hwnd, judul, 256)
                    # normalisasi tanpa spasi: judul situs bisa
                    # 'EdClub' / 'Typing Club' / 'Level 87 - Typing Club'
                    jl = judul.value.lower().replace(" ", "")
                    if jl and ("edclub" in jl or "typingclub" in jl):
                        user32_.ShowWindow(hwnd, 6)  # SW_MINIMIZE (tanpa aktivasi)
            except Exception:
                pass
            return True

        user32_.EnumWindows(enum_cb, 0)
    except Exception:
        pass




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




def dialog_online_activation(induk, nickname, on_send, on_cancel, on_ready=None):
    """Aktivasi online: isi nickname, kirim, lalu tunggu persetujuan.

    on_send(nickname) dipanggil di thread utama saat tombol kirim
    ditekan; pemanggil meneruskannya ke thread jaringan. Thread itu
    kemudian memanggil d.set_status()/d.finish() lewat _ui_queue.
    """
    d = _Dialog(induk, "Aktivasi",
                "Sebutkan namamu supaya dikenali pemilik aplikasi.",
                ikon="🌐", warna=GREEN)
    fase1 = tk.Frame(d.body, bg=PANEL)
    fase1.pack(fill="x")
    tk.Label(fase1, text="Siapa nama kamu?",
             font=("Segoe UI", 11, "bold"), fg=FG,
             bg=PANEL).pack(anchor="w", pady=(0, 6))
    var = tk.StringVar(value=nickname or "")
    ent = tk.Entry(fase1, textvariable=var, font=("Segoe UI", 11), bg=CARD,
                   fg=FG, insertbackground=FG, relief="flat",
                   highlightthickness=1, highlightbackground=EDGE,
                   highlightcolor=ACCENT)
    ent.pack(fill="x", ipady=6, pady=(2, 6))

    fase2 = tk.Frame(d.body, bg=PANEL)
    # gelombang ketikan selama menunggu jawaban server - frame dirender
    # pada resolusi native kanvas & gerak berbasis jam dinding
    kan_wave = tk.Canvas(fase2, height=64, bg=PANEL, highlightthickness=0)
    kan_wave.pack(fill="x", pady=(0, 10))
    d._anim_tunggu = anim.attach_wave(kan_wave)
    status_lbl = tk.Label(fase2, text="Mengirim permintaan...",
                          font=("Segoe UI", 11, "bold"), fg=FG, bg=PANEL,
                          wraplength=420, justify="left")
    status_lbl.pack(anchor="w", pady=4)
    sub_lbl = tk.Label(fase2, text="", font=("Segoe UI", 9), fg=DIM,
                       bg=PANEL, wraplength=420, justify="left")
    sub_lbl.pack(anchor="w")

    # fase sukses: centang menggambar sendiri sebelum dialog ditutup
    fase3 = tk.Frame(d.body, bg=PANEL)
    kan_cek = tk.Canvas(fase3, height=132, bg=PANEL, highlightthickness=0)
    kan_cek.pack(fill="x")
    tk.Label(fase3, text="Disetujui! Menyiapkan aplikasi...",
             font=("Segoe UI", 11, "bold"), fg=GREEN,
             bg=PANEL).pack(pady=(0, 2))

    def kirim():
        if terkirim["ok"]:
            return
        terkirim["ok"] = True
        nick = var.get().strip() or "Tanpa-nama"
        fase1.pack_forget()
        fase2.pack(fill="x")
        # layar tunggu minimal: header dipangkas, satu baris status,
        # sisanya biarkan animasi gelombang ketikan yang bicara
        d.set_header("Menunggu persetujuan", "")
        status_lbl.configure(text="Menunggu persetujuan pemilik…")
        try:
            btn_kirim.pack_forget()      # cukup 'Batalkan' - minimal
        except Exception:
            pass
        try:
            on_send(nick)
        except Exception:
            pass

    def set_status(txt, sub=""):
        try:
            status_lbl.configure(text=txt)
            if sub:
                sub_lbl.configure(text=sub)
        except Exception:
            pass

    def _stop_anim():
        try:
            d._anim_tunggu.stop()
        except Exception:
            pass

    def _rayakan():
        """Ganti fase tunggu -> animasi centang, TUTUP dialog setelah
        animasinya selesai (bukan seketika) supaya momen 'disetujui'
        terasa."""
        try:
            _stop_anim()
            d.set_header("Disetujui", "")
            fase2.pack_forget()
            fase3.pack(fill="x")
            d._cek = anim.PlayCheck(kan_cek, done=lambda: d.done(True))
            d._cek.start()
        except Exception:
            d.done(True)

    def finish(ok):
        try:
            if ok:
                _rayakan()
                return
            _stop_anim()
            d.done(ok)
        except Exception:
            d.done(ok)

    terkirim = {"ok": False}
    d.set_status = set_status
    d.finish = finish
    d.button("Batalkan", None, primer=False,
             cmd=lambda: (_stop_anim(), on_cancel(), d.done(False)))
    btn_kirim = d.button("Kirim Permintaan", None, cmd=kirim)
    ent.bind("<Return>", lambda e: kirim())
    if on_ready:
        try:
            on_ready(d)
        except Exception:
            pass
    return d.show()


def _mb(n):
    """Format megabita gaya Indonesia (koma desimal)."""
    return f"{n / (1 << 20):.1f}".replace(".", ",") + " MB"


def dialog_update(induk, info, versi_kini, tahap="awal", on_ready=None):
    """Pembaruan sebelum unduh: persetujuan + catatan rilis, lalu bilah
    kemajuan saat mengunduh, lalu pilihan pasang.

    Thread jaringan mengemudikan tampilan lewat metode objek dialog:
      d.stage_download()        tampil fase unduh
      d.set_progress(got,total) perbarui bilah + MB + kecepatan
      d.stage_ready()           unduhan selesai & terverifikasi
      d.stage_error(pesan)      gagal (tawaran coba lagi)
    Tombol mulai memanggil hook d.on_start() (dipasang pemanggil di
    on_ready); thread membaca atribut d.batal untuk batalkan unduh.
    show() -> "restart" / "later" / "cancelled" / None.
    """
    versi = info.get("version", "?")
    d = _Dialog(induk, f"Pembaruan v{versi}",
                "Versi baru tersedia untuk aplikasi ini.",
                ikon="⬇", warna=GREEN)
    d.batal = False
    d.on_start = lambda: None

    # ---------------- fase 1: persetujuan + catatan rilis
    fase1 = tk.Frame(d.body, bg=PANEL)
    bvr = tk.Frame(fase1, bg=PANEL)
    bvr.pack(fill="x", pady=(0, 8))
    tk.Label(bvr, text=f"v{versi_kini}", font=("Segoe UI", 12), fg=DIM,
             bg=PANEL).pack(side="left")
    tk.Label(bvr, text="  \u2192  ", font=("Segoe UI", 12, "bold"),
             fg=GREEN, bg=PANEL).pack(side="left")
    tk.Label(bvr, text=f"v{versi}", font=("Segoe UI", 13, "bold"),
             fg=FG, bg=PANEL).pack(side="left")
    if info.get("size"):
        tk.Label(bvr, text=f"\u2248 {_mb(info['size'])}",
                 font=("Segoe UI", 10), fg=DIM, bg=PANEL).pack(side="right")
    tk.Label(fase1, text="Apa yang baru:", font=("Segoe UI", 10, "bold"),
             fg=FG, bg=PANEL).pack(anchor="w")
    catatan = ScrolledText(fase1, height=6, bg=CARD, fg=FG, relief="flat",
                           font=("Segoe UI", 10), wrap="word", borderwidth=0,
                           highlightthickness=1, highlightbackground=EDGE)
    catatan.pack(fill="x", pady=(4, 0))
    catatan.insert("1.0", info.get("notes")
                   or "Pembaruan umum dan perbaikan kecil.")
    catatan.configure(state="disabled")

    # ---------------- fase 2: unduh (bilah kemajuan)
    fase2 = tk.Frame(d.body, bg=PANEL)
    tk.Label(fase2, text="Mengunduh pembaruan...",
             font=("Segoe UI", 12, "bold"), fg=FG,
             bg=PANEL).pack(anchor="w", pady=(0, 10))
    bar = tk.Canvas(fase2, height=26, bg=PANEL, highlightthickness=0)
    bar.pack(anchor="w", fill="x")
    ket_lbl = tk.Label(fase2, text="Menyambung ke server...",
                       font=("Segoe UI", 9), fg=DIM, bg=PANEL)
    ket_lbl.pack(anchor="w", pady=(6, 0))
    tk.Label(fase2, text="File diverifikasi SHA-256 sebelum dipasang.",
             font=("Segoe UI", 9), fg=FAINT, bg=PANEL).pack(anchor="w")

    # ---------------- fase 3: siap dipasang
    fase3 = tk.Frame(d.body, bg=PANEL)
    tk.Label(fase3, text=f"\u2713 v{versi} siap dipasang",
             font=("Segoe UI", 13, "bold"), fg=GREEN,
             bg=PANEL).pack(anchor="w")
    teks_siap = ("Mulai ulang sekarang untuk langsung memakainya, atau "
                 "lanjutkan memakai versi ini - pembaruan terpasang "
                 "otomatis saat aplikasi dibuka lagi.")
    if not getattr(sys, "frozen", False):
        teks_siap = ("Mode skrip (bukan EXE): unduhan tersimpan sebagai "
                     "TypingBot.exe.new.exe di samping program - ganti "
                     "file exe secara manual.")
    tk.Label(fase3, text=teks_siap, font=("Segoe UI", 10), fg=DIM,
             bg=PANEL, wraplength=420, justify="left").pack(
                 anchor="w", pady=(6, 0))

    # ---------------- fase 4: gagal
    fase4 = tk.Frame(d.body, bg=PANEL)
    err_lbl = tk.Label(fase4, text="", font=("Segoe UI", 12, "bold"),
                       fg=RED, bg=PANEL, wraplength=420, justify="left")
    err_lbl.pack(anchor="w")
    tk.Label(fase4, text="Unduhan bisa dicoba lagi - data lama tetap aman.",
             font=("Segoe UI", 9), fg=DIM, bg=PANEL).pack(anchor="w",
                                                          pady=(4, 0))

    def _gambar(persen):
        bar.delete("all")
        w = max(bar.winfo_width(), 320)
        bar.configure(width=w)
        # jalur 18px tinggi supaya teks % (font 9 ≈ 14px) benar-benar
        # DI DALAM bilah, bukan menjulur keluar atas-bawah (dulu 10px)
        bar.create_rectangle(0, 4, w, 22, fill=CARD, width=0)
        isi = max(3, int(w * persen / 100.0))
        bar.create_rectangle(1, 5, isi, 21, fill=GREEN, width=0)
        bar.create_text(w - 8, 13, anchor="e", text=f"{persen:.0f}%",
                        font=("Segoe UI", 9, "bold"), fill=FG)

    _spd = {"t": 0.0, "got": 0, "v": 0.0}

    def set_progress(got, total):
        try:
            persen = (min(100.0, got * 100.0 / total)) if total else 0.0
            _gambar(persen)
            kini = time.time()
            if kini - _spd["t"] >= 0.5:
                if kini > _spd["t"] and got >= _spd["got"]:
                    _spd["v"] = ((got - _spd["got"])
                                 / (kini - _spd["t"]) / (1 << 20))
                _spd.update(t=kini, got=got)
            ket = _mb(got)
            if total:
                ket += f"  dari  {_mb(total)}"
            if _spd["v"] > 0.05:
                ket += f"  \u2022  {_mb(_spd['v'])}/dtk"
            ket_lbl.configure(text=ket)
        except Exception:
            pass

    # ---------------- tombol per fase
    tombol = {}

    def _tahap_tombol(*nama):
        for k, b in tombol.items():
            if k in nama:
                b.pack(side="right", padx=(8, 0))
            else:
                b.pack_forget()

    def _mulai():
        for f in (fase1, fase3, fase4):
            f.pack_forget()
        fase2.pack(fill="x")
        _gambar(0)
        _tahap_tombol("batal")
        d.bind("<Return>", lambda e: None)
        try:
            d.on_start()
        except Exception:
            pass

    tombol["mulai"] = d.button("\u2b07  Perbarui sekarang", None,
                               warna_btn=GREEN, cmd=_mulai)
    tombol["nanti"] = d.button("Nanti", None, primer=False,
                               cmd=lambda: d.done(None))
    tombol["batal"] = d.button("Batalkan", None, primer=False,
                               cmd=lambda: _membatalkan())
    tombol["coba"] = d.button("Coba lagi", None, warna_btn=GREEN,
                              cmd=_mulai)
    tombol["pasang"] = d.button("\u21bb  Mulai ulang sekarang", None,
                                warna_btn=GREEN,
                                cmd=lambda: d.done("restart"))
    tombol["tutup"] = d.button("Tutup", None, primer=False,
                               cmd=lambda: d.done(None))

    def _membatalkan():
        d.batal = True
        try:
            tombol["batal"].configure(text="Membatalkan...", fg=DIM,
                                      bg=CARD, cursor="arrow")
            tombol["batal"].unbind("<Button-1>")
        except Exception:
            pass

    def _tutup(_e=None):
        # saat mengunduh, [X]/Esc = batalkan; dialog ditutup thread
        # setelah unduh benar-benar berhenti (d.done("cancelled"))
        if fase2.winfo_ismapped():
            _membatalkan()
            return
        d.done(None)

    def stage_download():
        _mulai()

    def stage_ready():
        for f in (fase1, fase2, fase4):
            f.pack_forget()
        fase3.pack(fill="x")
        if getattr(sys, "frozen", False):
            _tahap_tombol("pasang", "nanti")
            d.bind("<Return>", lambda e: tombol["pasang"]._klik())
        else:
            _tahap_tombol("tutup")
            d.bind("<Return>", lambda e: None)

    def stage_error(pesan):
        for f in (fase1, fase2, fase3):
            f.pack_forget()
        fase4.pack(fill="x")
        err_lbl.configure(text=str(pesan))
        _tahap_tombol("coba", "tutup")
        d.bind("<Return>", lambda e: None)

    d.set_progress = set_progress
    d.stage_download = stage_download
    d.stage_ready = stage_ready
    d.stage_error = stage_error
    d.protocol("WM_DELETE_WINDOW", _tutup)
    d.bind("<Escape>", _tutup)

    if tahap == "siap":
        stage_ready()
    else:
        fase1.pack(fill="x")
        _tahap_tombol("mulai", "nanti")
    if on_ready:
        try:
            on_ready(d)
        except Exception:
            pass
    return d.show()


def dialog_dev_code(induk):
    """Gerbang kecil area developer (bukan pengaman keras): kodenya
    nama pembuat aplikasi - huruf kecil, tanpa spasi - yang memang
    terpajang di kaki jendela utama. Cukup menyaring klik tidak sengaja."""
    d = _Dialog(induk, "Area developer",
                "Area ini teknis, dipakai untuk diagnosis dan pengujian.",
                ikon="\U0001f510", warna=ORANGE)
    var = tk.StringVar(value="")
    ent = tk.Entry(d.body, textvariable=var, font=("Segoe UI", 13),
                   bg=CARD, fg=FG, insertbackground=FG, relief="flat",
                   justify="center", show="\u2022",
                   highlightthickness=1, highlightbackground=EDGE,
                   highlightcolor=ACCENT)
    ent.pack(fill="x", ipady=7, pady=(4, 8))
    salah = tk.Label(d.body, text="", font=("Segoe UI", 9), fg=RED,
                     bg=PANEL)
    salah.pack(anchor="w")
    tk.Label(d.body,
             text="Petunjuk: siapa pembuat aplikasi ini? (huruf kecil "
                  "semua - jawabannya ada di kaki jendela utama)",
             font=("Segoe UI", 9), fg=FAINT, bg=PANEL, wraplength=420,
             justify="left").pack(anchor="w", pady=(6, 0))

    def cek():
        jawab = "".join(var.get().lower().split())
        if jawab == CREATOR.lower():
            d.done(True)
        else:
            salah.configure(text="Kode belum cocok.")
            var.set("")
            ent.focus_set()

    d.button("Buka", None, warna_btn=ORANGE, cmd=cek)
    d.button("Batal", None, primer=False)
    ent.bind("<Return>", lambda e: cek())
    ent.focus_set()
    return d.show()
