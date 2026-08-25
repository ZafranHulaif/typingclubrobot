"""Terjemahan baris log engine -> kalimat awam."""

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



# ------------------------------------------------- pesan ramah (kartu aktivitas)
# Terjemahan baris log engine -> kalimat awam untuk kartu aktivitas.
# Baris yang tidak cocok aturan mana pun tetap masuk bot.log tapi tidak
# ditampilkan: layar pengguna harus bebas istilah teknis (port, debug,
# proses, dll.); pemilik tetap bisa membuka bot.log lewat jendela Dev.
_ACTIVITY_MAP = [
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
    (re.compile(r"\[PORT\] 9222 sedang dipakai"),
     "Ada aplikasi lain yang kebetulan satu jalur dengan bot - bot pakai "
     "jalur lain, tidak menutup apa pun"),
    (re.compile(r"\[PROFIL\] (\w+) sedang jalan"),
     "Menutup %s dulu supaya bot bisa memakai profil kamu"),
    (re.compile(r"\[PROFIL\] tidak ditutup"),
     "Browser tidak ditutup - bot memakai profil khusus bot"),
    (re.compile(r"\[PROFIL\] membuka (\w+) dengan profilmu \(([^)]*)\)"),
     "Membuka %s dengan profilmu (%s)..."),
    (re.compile(r"\[PROFIL\] profil kamu gagal dibuka"),
     "Profil kamu gagal dibuka - bot memakai profil khusus bot"),
    (re.compile(r"\[PROFIL\] profil '.*' tidak ada"),
     "Profil pilihanmu tidak ditemukan - bot memakai profil khusus bot"),
    (re.compile(r"\[PROFIL\] gagal (membuat pintasan|menyiapkan)"),
     "Folder profil gagal disiapkan - bot memakai profil khusus bot"),
    (re.compile(r"^Bot dihentikan"), "Bot berhenti."),
    (re.compile(r"Bot sedang berhenti"), "Berhenti..."),
    (re.compile(r"^Selesai\. Total"), "Selesai."),
]



_NICE_NAMES = {"brave": "Brave", "chrome": "Google Chrome",
              "msedge": "Microsoft Edge"}




def _friendly_text(line):
    """Baris log -> kalimat awam, atau None bila tidak perlu ditampilkan."""
    for rx, tmpl in _ACTIVITY_MAP:
        m = rx.search(line)
        if m:
            try:
                return tmpl % m.groups() if m.groups() else tmpl
            except TypeError:
                return tmpl
    return None




def _display_name(nama):
    """'brave'/'msedge' dari sistem -> nama produk yang dikenal pengguna."""
    kunci = (nama or "").strip().lower().replace("  (webview)", "")
    if kunci in _NICE_NAMES:
        return _NICE_NAMES[kunci]
    return kunci[:1].upper() + kunci[1:] if kunci else "Aplikasi"
