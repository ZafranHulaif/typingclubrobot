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
from .theme import (ACCENT, BROWSER_COLORS, BTN_FG, CARD, CARD_HOVER, CREATOR, DIM, EDGE, FAINT, FG, GREEN, ORANGE, PANEL, RED, YELLOW)
from .translator import _display_name
from .widgets import ScrollbarGelap, _Dialog




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

    # daftar profil hidup di kanvas yang bisa digulir: dulu baris
    # langsung dipack ke body - profil banyak membuat dialog lebih
    # tinggi dari layar dan tak bisa digulir (keluhan live: profil
    # di bawah tidak bisa dipilih).
    bingkai = tk.Frame(d.body, bg=PANEL)
    bingkai.pack(fill="both", expand=True)
    kan = tk.Canvas(bingkai, bg=PANEL, highlightthickness=0)
    gulir = ScrollbarGelap(bingkai, kan.yview)
    kan.configure(yscrollcommand=gulir.set)
    gulir.pack(side="right", fill="y")
    kan.pack(side="left", fill="both", expand=True)
    isi = tk.Frame(kan, bg=PANEL)
    jendela = kan.create_window((0, 0), window=isi, anchor="nw")

    def gulir_roda(e):
        kan.yview_scroll(-1 if e.delta > 0 else 1, "units")

    def _pas_lebar(e):
        kan.itemconfigure(jendela, width=e.width)

    kan.bind("<Configure>", _pas_lebar)

    def _rentang(_e=None):
        kan.configure(scrollregion=kan.bbox("all"))
        kan.configure(height=min(isi.winfo_reqheight(),
                                 int(d.winfo_screenheight() * 0.52)),
                      width=min(max(isi.winfo_reqwidth(), 380), 440))

    isi.bind("<Configure>", _rentang)
    for wd in (kan, isi):
        wd.bind("<MouseWheel>", gulir_roda)

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
        wrap = tk.Frame(isi, bg=CARD, highlightthickness=1,
                        highlightbackground=EDGE, cursor="hand2")
        wrap.pack(fill="x", padx=(0, 12), pady=3)
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
            wdgt.bind("<MouseWheel>", gulir_roda)
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




def dialog_range(induk, mulai, akhir, jumlah_peta, total_level, on_bangun,
                 posisi=0, baris=None):
    """Pilih titik mulai bot. Return: "lanjut" (dari posisi akun - level
    berikutnya yang terbuka), dict {mulai,akhir} (rentang khusus / lanjut
    yang digeser), "halaman" (user memilih level awal sendiri di halaman),
    None (batal).

    v3 (permintaan user): TIGA TILE POTRET sama lebar, lebih TINGGI dari
    lebarnya, sudut membulat, tanpa kepala/bingkai. Lanjut = carousel:
    level terpilih besar di tengah, level sebelumnya di kiri & berikutnya
    di kanan (kunci + abu kalau terkunci), tombol '»' loncat ke level
    terakhir saat menjauh. Rentang Khusus: kotak angka besar diedit
    langsung di tempat."""
    hasil = {"mulai": mulai, "akhir": akhir}
    d = _Dialog(induk, "", "")
    kartu_ov = getattr(d, "_kartu", None)
    overlay = kartu_ov is not None
    lebar_area = 1350
    if overlay:
        try:
            layer = getattr(d, "_layer", None)
            if layer is not None:
                lebar_area = max(layer.winfo_width() - 96, 900)
        except Exception:
            pass
        lebar_area = min(1560, lebar_area)
    LATAR = "#0c0d11" if overlay else PANEL

    NAVY = "#2e4059"
    TILE = "#eef2f8"
    TILE_EDGE = "#dde4ee"
    PUTIH = "#ffffff"
    HIJAU = "#2fb463"
    ABU = "#9aa6b8"
    ABU_MUDA = "#c3cad6"

    # tile potret: LEBAR < TINGGI, ketiga tile sama persis
    GAP = 24                    # jarak antar tile (keluhan: menempel)
    W = max(320, min(480, (lebar_area - 72) // 3))
    H = min(620, max(440, int(W * 1.18)))
    R = 22                      # radius sudut membulat

    # kartu PERSIS selebar isi 3 tile (3W + 6 pad 12) -> kartu yang
    # memang di tengah layar membawa tile ikut di tengah (dulu kartu
    # 1560 dgn tile total 1440 nempel kiri: keluhan 'offset ke kiri')
    if overlay and kartu_ov is not None:
        try:
            kartu_ov.place_configure(width=min(lebar_area, 3 * W + 72))
        except Exception:
            pass

    baris_kartu = tk.Frame(d.body, bg=LATAR)
    baris_kartu.pack(fill="x", expand=True, pady=(8, 2))

    def bulat(cv, x1, y1, x2, y2, warna_isi, warna_tepi):
        pts = [x1 + R, y1, x2 - R, y1, x2, y1, x2, y1 + R, x2, y2 - R,
               x2, y2, x2 - R, y2, x1 + R, y2, x1, y2, x1, y2 - R,
               x1, y1 + R, x1, y1]
        return cv.create_polygon(pts, smooth=True, fill=warna_isi,
                                 outline=warna_tepi, width=2)

    def tile(judul):
        cv = tk.Canvas(baris_kartu, width=W, height=H, bg=LATAR,
                       highlightthickness=0)
        cv.pack(side="left", padx=(GAP // 2, GAP // 2), pady=0)
        cv._tepi = TILE_EDGE
        l = tk.Label(cv, text=judul, font=("Segoe UI", 12, "bold"),
                     fg=NAVY, bg=PUTIH, cursor="hand2")
        cv.create_window(W // 2, 44, window=l, tags="isi")
        return cv, l

    def gambar_tile(cv, tepi):
        bulat(cv, 2, 2, W - 2, H - 2, PUTIH, tepi)

    def redraw(cv, judul_lbl, tepi):
        # delete("all") membuang window-item judul juga -> pasang ulang.
        # bingkai/badan diberi TAG supaya hover TIDAK perlu redraw: cukup
        # itemconfig (dulu hover = redraw penuh -> isi tile terhapus
        # diam-diam saat kursor lewat - tile jadi kosong).
        cv.delete("all")
        badan = bulat(cv, 2, 2, W - 2, H - 2, PUTIH, tepi)
        cv.itemconfigure(badan, tags="badan")
        # bingkai ikut warna param (dulu ACCENT permanen - keluhan user:
        # Lanjut tampak 'hover' padahal tidak)
        b = bulat(cv, 4, 4, W - 4, H - 4, "", tepi)
        cv.itemconfigure(b, fill="", width=3, tags="bingkai")
        cv.create_window(W // 2, 44, window=judul_lbl, tags="isi")

    def tepi(cv, warna):
        if cv.find_withtag("bingkai"):
            cv.itemconfigure("bingkai", outline=warna)

    def sorot(cv, nyala):
        """Hover tile: bingkai biru + badan ber-tint biru muda -
        keluhan user 'hovering not clear enough' - sekarang KELIHATAN."""
        if cv.find_withtag("bingkai"):
            cv.itemconfigure("bingkai", outline=ACCENT if nyala else
                             (ACCENT if cv._aktif else TILE_EDGE))
        if cv.find_withtag("badan"):
            cv.itemconfigure("badan", fill="#f3f7ff" if nyala else PUTIH)

    def kedip(cv):
        """Umpan balik tekan: bingkai menebal sebentar."""
        if cv.find_withtag("bingkai"):
            cv.itemconfigure("bingkai", width=5)
            cv.after(120, lambda: cv.itemconfigure("bingkai", width=3))

    kartu_khusus = [None]

    def _nav(level=None, daftar=False):
        """Arahkan browser embed SAAT KLIK (webview masih tersembunyi di
        balik dialog - watcher menavigasi diam-diam, user tidak pernah
        melihat halaman lama/refresh). Dulu 'Lanjut' cuma menggenggam
        bot tanpa navigasi = 'Menunggu kamu' padahal user sudah pilih
        (keluhan user). Fallback: daftar level tampilan baru."""
        try:
            from .widgets import _DIALOG_LAYER
            l = _DIALOG_LAYER
            if l is None:
                return
            url = "https://www.edclub.com/student/course/3"
            if not daftar and level:
                try:
                    from engine import levels as _lv
                    url = _lv.url_untuk_level(level) or url
                except Exception:
                    pass
            l.ke_url(url)
        except Exception:
            pass

    def hover(cv, judul_lbl, nilai):
        def masuk(_e=None):
            sorot(cv, True)
        def keluar(_e=None):
            sorot(cv, False)
        cv._aktif = False
        cv.bind("<Enter>", masuk)
        cv.bind("<Leave>", keluar)
        return masuk

    # ================= 1) LANJUT (kiri): carousel level =================
    lvl_awal = max(1, min(posisi or mulai or 1, total_level))
    lvl = {"n": lvl_awal}

    cv1, l1 = tile("Lanjut")

    def tombol(cv, cx, cy, label, aktif, tags):
        """Tombol kotak-membulat utk panah carousel. Return item.
        Hover/tekan ditangani tag_bind di bawah (keluhan user: panah
        terasa mati - sekarang ada kotak, terang saat hover, tonejok
        saat ditekan, abu saat mati)."""
        bw, bh = 26, 22
        x1, y1, x2, y2 = cx - bw, cy - bh, cx + bw, cy + bh
        pts = [x1 + 6, y1, x2 - 6, y1, x2, y1, x2, y1 + 6, x2, y2 - 6,
               x2, y2, x2 - 6, y2, x1 + 6, y2, x1, y2, x1, y2 - 6,
               x1, y1 + 6, x1, y1]
        kotak = cv.create_polygon(
            pts, smooth=True, fill="#eef2f8" if aktif else "#f3f4f7",
            outline=TILE_EDGE if aktif else "#e3e6ec", width=1,
            tags=tags)
        warna_teks = ACCENT if aktif else ABU_MUDA
        cv.create_text(cx, cy, text=label,
                       font=("Segoe UI", 15, "bold"), fill=warna_teks,
                       tags=tags)
        return kotak

    def hidupkan_tombol(cv, tags, aktif):
        """Pasang efek hover + tekan pd semua item ber-tags."""
        def masuk(_e=None):
            if aktif:
                cv.itemconfigure(tags, fill="#e4eeff", outline=ACCENT)
        def keluar(_e=None):
            if aktif:
                cv.itemconfigure(tags, fill="#eef2f8", outline=TILE_EDGE)
        def tekan(_e=None):
            if not aktif:
                return
            cv.itemconfigure(tags, fill="#d5e3ff")
            cv.after(110, lambda: cv.itemconfigure(tags, fill="#eef2f8"))
        cv.tag_bind(tags, "<Enter>", masuk)
        cv.tag_bind(tags, "<Leave>", keluar)
        cv.tag_bind(tags, "<Button-1>", tekan)

    def gbr_lanjut():
        cv = cv1
        # dulu bingkai ACCENT permanen (keluhan user: 'why is there a
        # blue outline even when not hovering') - sekarang sama seperti
        # tile lain: biru CUMA saat hover.
        redraw(cv, l1, TILE_EDGE)
        n = lvl["n"]
        # ---- kiri: level sebelumnya (angka + tombol ‹)
        if n > 1:
            cv.create_text(int(W * 0.16), int(H * 0.40), text=f"{n - 1:02d}",
                           font=("Segoe UI", 20, "bold"), fill=ABU)
        tombol(cv, int(W * 0.16), int(H * 0.42) + 34, "\u2039", n > 1,
               "btn-kiri")
        hidupkan_tombol(cv, "btn-kiri", n > 1)
        # ---- tengah: level terpilih (besar)
        cv.create_text(W // 2, int(H * 0.38), text=f"{n:02d}",
                       font=("Segoe UI", 46, "bold"), fill=NAVY)
        kx1, ky1 = W // 2 - 60, int(H * 0.50)
        cv.create_rectangle(kx1, ky1, kx1 + 120, ky1 + 46, fill=TILE,
                            outline=TILE_EDGE)
        for i, x in enumerate((kx1 + 8, kx1 + 27, kx1 + 46, kx1 + 65,
                               kx1 + 84, kx1 + 103)):
            cv.create_rectangle(x, ky1 + 10, x + 14, ky1 + 23,
                                fill=(ACCENT if i == 2 else PUTIH),
                                outline=TILE_EDGE)
        cv.create_rectangle(kx1 + 8, ky1 + 30, kx1 + 112, ky1 + 39,
                            fill=PUTIH, outline=TILE_EDGE)
        cv.create_oval(kx1 + 96, ky1 - 24, kx1 + 132, ky1 + 12,
                       fill=HIJAU, width=0, tags="play", outline=HIJAU)
        cv.create_polygon(kx1 + 109, ky1 - 15, kx1 + 109, ky1 - 1,
                          kx1 + 121, ky1 - 8, fill="white", width=0,
                          tags="play")
        # badge play membesar saat hover (umpan balik 'interactive')
        cv.tag_bind("play", "<Enter>", lambda _e: (
            cv.itemconfigure("play", width=3),
            cv.itemconfigure("play", outline="#27a355")))
        cv.tag_bind("play", "<Leave>", lambda _e: (
            cv.itemconfigure("play", width=0),
            cv.itemconfigure("play", outline=HIJAU)))
        ket = ("level berikutnya yang belum selesai"
               if n == lvl_awal else "mulai dari level ini")
        cv.create_text(W // 2, int(H * 0.72), text=ket,
                       font=("Segoe UI", 9), fill=ABU)
        # ---- kanan: level berikutnya (kunci kalau lewat lvl_awal)
        if n < lvl_awal:
            cv.create_text(int(W * 0.84), int(H * 0.40), text=f"{n + 1:02d}",
                           font=("Segoe UI", 20, "bold"), fill=NAVY)
            tombol(cv, int(W * 0.84), int(H * 0.42) + 34, "\u203a", True,
                   "btn-kanan")
            hidupkan_tombol(cv, "btn-kanan", True)
        else:
            # terkunci: kotak abu + gembok + tombol ›  mati
            cv.create_text(int(W * 0.84), int(H * 0.40), text=f"{n + 1:02d}",
                           font=("Segoe UI", 20, "bold"), fill=ABU)
            tombol(cv, int(W * 0.84), int(H * 0.42) + 34, "\u203a", False,
                   "btn-kanan")
            hidupkan_tombol(cv, "btn-kanan", False)
            bx, by = int(W * 0.84) - 13, int(H * 0.40) - 46
            cv.create_rectangle(bx, by, bx + 26, by + 26,
                                fill="#f0f2f6", outline=TILE_EDGE)
            cv.create_text(bx + 13, by + 13, text="🔒",
                           font=("Segoe UI Emoji", 10), fill=ABU)
        # ---- '»' loncat ke terakhir saat menjauh dari lvl_awal
        if n < lvl_awal:
            tombol(cv, int(W * 0.84), int(H * 0.72), "\u00bb", True,
                   "btn-akhir")
            hidupkan_tombol(cv, "btn-akhir", True)
            cv.create_text(int(W * 0.84), int(H * 0.72) + 26,
                           text="langsung ke terakhir",
                           font=("Segoe UI", 8), fill=ABU)

    def klik_lanjut(e):
        x, y = e.x, e.y
        zt = W * 0.14          # zona telunjuk kiri/kanan
        if abs(x - W * 0.16) < zt and abs(y - H * 0.42) < H * 0.20:
            if lvl["n"] > 1:
                kedip(cv1)
                lvl["n"] -= 1
                gbr_lanjut()
            return
        if abs(x - W * 0.84) < zt and abs(y - H * 0.42) < H * 0.20:
            if lvl["n"] < lvl_awal:
                kedip(cv1)
                lvl["n"] += 1
                gbr_lanjut()
            return
        if abs(x - W * 0.84) < zt and abs(y - H * 0.72) < H * 0.10 \
                and lvl["n"] < lvl_awal:
            kedip(cv1)
            lvl["n"] = lvl_awal
            gbr_lanjut()
            return
        # tengah = pilih -> SEKALIGUS navigasi ke level itu (webview
        # masih tersembunyi; dulu cuma 'menunggu kamu' = user kesal)
        if W * 0.30 < x < W * 0.70:
            kedip(cv1)
            if lvl["n"] == lvl_awal:
                _nav(lvl["n"])
                d.done("lanjut")
            else:
                _nav(lvl["n"])
                d.done({"mulai": lvl["n"], "akhir": 0})
    cv1.bind("<Button-1>", klik_lanjut)
    l1.bind("<Button-1>", klik_lanjut)
    hover(cv1, l1, "lanjut")
    gbr_lanjut()

    # ============ 2) PILIH DI HALAMAN (tengah): grid edclub ============
    cv2, l2 = tile("Pilih di Halaman")

    def _hover_mini(cv, tag, rect, nyala):
        # HANYA rect yang di-config: tagm juga memuat item teks/oval/garis
        # yang TIDAK punya opsi outline -> itemconfigure(tag, outline=..)
        # selalu TclError 'unknown option -outline' walau tag ada (live:
        # log penuh traceback tiap hover, v3).
        try:
            cv.itemconfigure(rect, outline=ACCENT if nyala else TILE_EDGE,
                             fill="#f3f7ff" if nyala else PUTIH)
        except tk.TclError:
            pass      # redraw menghapus item - hover basi, abaikan

    def gbr_halaman():
        cv = cv2
        redraw(cv, l2, TILE_EDGE)
        # baris ASLI dari pemindaian akun (dulu: data pura-pura hardcoded
        # 01 ok 02 ok 03-06 kunci - keluhan sim: 'level 3 locked? akun saya
        # sudah level 90'). Tampilkan 6 level mulai dari posisi akun.
        awal = lvl_awal
        brs = []
        if baris and baris.get(awal) is not None:
            for no in range(awal, awal + 6):
                st = baris.get(no, "")
                brs.append((f"{no:02d}", "ok" if st == "ok"
                            else ("kunci" if st == "kunci" else "")))
        if not brs:
            brs = [(f"{n:02d}", "") for n in range(awal, awal + 6)]
        urut = brs
        gx = W // 2 - 3 * 52
        for i, (no, st) in enumerate(urut):
            x = gx + (i % 3) * 104
            y = int(H * 0.22) + (i // 3) * 76
            tagm = f"mini{i}"
            rm = cv.create_rectangle(x, y, x + 92, y + 66, fill=PUTIH,
                                     outline=TILE_EDGE, tags=tagm)
            cv.create_text(x + 14, y + 17, text=no,
                           font=("Segoe UI", 11, "bold"), fill=NAVY,
                           tags=tagm)
            cv.tag_bind(tagm, "<Enter>", lambda _e, t=tagm, rr=rm:
                        _hover_mini(cv, t, rr, True))
            cv.tag_bind(tagm, "<Leave>", lambda _e, t=tagm, rr=rm:
                        _hover_mini(cv, t, rr, False))
            if st == "ok":
                cx, cy = x + 46, y + 42
                cv.create_oval(cx - 13, cy - 13, cx + 13, cy + 13,
                               fill=HIJAU, width=0, tags=tagm)
                cv.create_line(cx - 5, cy, cx - 1, cy + 4,
                               cx + 6, cy - 5, fill="white", width=2,
                               joinstyle="round", capstyle="round",
                               tags=tagm)
            elif st == "kunci":
                cv.create_text(x + 46, y + 42, text="🔒",
                               font=("Segoe UI Emoji", 14), fill=ABU,
                               tags=tagm)
        cv.create_text(W // 2, int(H * 0.82),
                       text="klik, lalu pilih level di halaman",
                       font=("Segoe UI", 9), fill=ABU)
    gbr_halaman()
    def klik_halaman(_e=None):
        kedip(cv2)
        _nav(daftar=True)      # langsung tampilan BARU, tanpa flash tua
        d.done("halaman")
    cv2.bind("<Button-1>", klik_halaman)
    l2.bind("<Button-1>", klik_halaman)
    hover(cv2, l2, "halaman")

    # ====== 3) RENTANG KHUSUS (kanan): kotak angka besar langsung ======
    cv3, l3 = tile("Rentang Khusus")

    cv3.bind("<Button-1>", lambda e: None)   # Entry menyerap kliknya
    def kotak_angka(label, nilai):
        # create_window Tk mensyaratkan anak LANGSUNG dari canvas
        # (cucu = TclError) - jadi kol = anak langsung cv3, tanpa baris3.
        kol = tk.Frame(cv3, bg=PUTIH)
        # JANGAN pack() kol di dalam canvas: canvas yang dipakai jadi
        # geometry manager merespon ukurannya (live: cv3 jadi 17x1).
        # Penempatan murni lewat create_window di gbr_rentang.
        var = tk.StringVar(value=str(nilai))
        ent = tk.Entry(kol, textvariable=var,
                       font=("Segoe UI", 26, "bold"), width=5,
                       bg=PUTIH, fg=NAVY, insertbackground=NAVY,
                       relief="flat", justify="center",
                       highlightthickness=1,
                       highlightbackground=TILE_EDGE,
                       highlightcolor=ACCENT)
        ent.pack(ipady=7)
        tk.Label(kol, text=label, font=("Segoe UI", 9), fg=ABU,
                 bg=PUTIH).pack()
        return kol, var

    kol_a, var_a = kotak_angka("dari", mulai or 1)
    kol_b, var_b = kotak_angka("sampai", akhir or total_level)

    def gbr_rentang():
        cv = cv3
        redraw(cv, l3, ACCENT if khusus.winfo_ismapped() else TILE_EDGE)
        cv.create_text(W // 2, int(H * 0.24), text=f"Level 1-{total_level}",
                       font=("Segoe UI", 11, "bold"), fill=ABU)
        # pasang ulang SEMUA isi: redraw di atas = delete("all") yang
        # dulu MENGHAPUS window-item Entry yang digambar duluan
        # (keluhan: 'selector rentang mana?' - kosong melompong)
        y = int(H * 0.46)
        cv.create_window(W // 2 - 118, y, window=kol_a, tags="isi")
        cv.create_text(W // 2, y, text="\u2192",
                       font=("Segoe UI", 22, "bold"), fill=ACCENT,
                       tags="isi")
        cv.create_window(W // 2 + 118, y, window=kol_b, tags="isi")
        cv.create_text(W // 2, int(H * 0.64),
                       text="klik angka untuk mengubah",
                       font=("Segoe UI", 9), fill=ABU, tags="isi")

    # info/galat di bawah baris (muncul saat rentang dipilih)
    khusus = tk.Frame(d.body, bg=LATAR)
    info = tk.Label(khusus, font=("Segoe UI", 9), fg=DIM, bg=LATAR,
                    wraplength=640, justify="center")
    galat = tk.Label(khusus, text="", font=("Segoe UI", 9), fg=RED,
                     bg=LATAR)

    def pilih3(_e=None):
        if not khusus.winfo_ismapped():
            khusus.pack(fill="x", pady=(0, 2))
            b_simpan.pack(side="right")
        pilih3._aktif = True
        cv3._aktif = True
        gbr_rentang()
        info_teks()
    pilih3._aktif = False

    cv3._aktif = False     # awal: khusus belum dipilih

    def masuk3(_e=None):
        sorot(cv3, True)

    def keluar3(_e=None):
        sorot(cv3, False)
    for w in (cv3, l3):
        w.bind("<Enter>", masuk3)
        w.bind("<Leave>", keluar3)
    l3.bind("<Button-1>", pilih3)
    cv3.bind("<Button-1>", pilih3)

    def info_teks():
        info.configure(text=
            ("Level yang masih terkunci akan dikonfirmasi saat mulai.")
            if jumlah_peta["n"] >= total_level else
            ("Peta level: %d/%d terpetakan - klik Bangun Peta "
             "(sekali saja, ~15 menit).\nLevel yang masih terkunci akan "
             "dikonfirmasi saat mulai." % (jumlah_peta["n"], total_level)))

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
        _nav(a)               # langsung ke level 'dari' - bukan menunggu
        d.done(hasil)

    b_simpan = d.button("Simpan", None, cmd=simpan)
    b_simpan.pack_forget()
    if jumlah_peta["n"] < total_level:
        def bangun():
            on_bangun()
            return False
        d.button("Bangun Peta", None, primer=False, cmd=bangun)

    galat.pack(anchor="center")
    info.pack(anchor="center")
    gbr_rentang()          # setelah khusus ada (butuh winfo_ismapped)

    r = d.show()
    if r == "halaman" or r == "lanjut":
        return r
    return r if isinstance(r, dict) else None


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
    kan_wave = tk.Canvas(fase2, height=40, bg=PANEL, highlightthickness=0)
    kan_wave.pack(fill="x", pady=(0, 6))
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
    kan_cek = tk.Canvas(fase3, height=90, bg=PANEL, highlightthickness=0)
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
