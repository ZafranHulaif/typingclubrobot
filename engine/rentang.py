"""Cek rentang level tiap iterasi loop utama."""

import ctypes
import io
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from . import state
from . import levels
from . import typing_core




def _rentang_cek(url):
    """Terapkan rentang level pilihan user. Return True = main loop harus
    `continue` (navigasi/berhenti ditangani di sini). Kasus penting (live):
    setelah login bot mendarat di DAFTAR lesson (.game) - dulu lompatan
    hanya berlaku di halaman .play, sehingga recovery malah membuka level
    TERDEPAN akun (L106) mengabaikan rentang; sekarang dari daftar pun
    langsung menuju LEVEL_START.
    RENTANG_SIAP: rentang baru boleh DITERAPKAN setelah user menjawab
    dialog rentang saat Start (live 00:2x: patroli login membersihkan
    PERLU_LOGIN, dan SEBELUM dialog rentang sempat terbuka (poll GUI
    150ms belumlah jalan) case-3 di bawah langsung melompat ke LEVEL_START
    lama yang tersimpan (662) - browser pindah ke level sendiri padahal
    user belum menjawab apapun)."""
    if not state.RENTANG_SIAP:
        return False
    if state.RENTANG_SELESAI or (state.LEVEL_START <= 1 and not state.LEVEL_END):
        return False
    on_play = ".play" in (url or "")
    nomor = 0
    if on_play:
        if state.STATUS_LABEL.startswith("L"):
            try:
                nomor = int(state.STATUS_LABEL[1:])
            except ValueError:
                pass
        if not nomor:
            nomor = levels.url_ke_level(url) or 0
        if nomor > state._rentang_max_seen:
            state._rentang_max_seen = nomor
    # 1) melewati akhir rentang -> selesai
    if nomor and state.LEVEL_END and nomor > state.LEVEL_END:
        state.RENTANG_SELESAI = True
        state.STOP = True
        print(f"[RENTANG] level {nomor} melewati akhir rentang "
              f"({state.LEVEL_END}) - bot selesai.")
        return True
    # 1b) selesai saat meninggalkan level akhir: level terakhir kursus
    # (live: L685 = video) tidak pernah punya lesson berikutnya - begitu
    # selesai, situs mendarat ke daftar lesson dan cek 'nomor > LEVEL_END'
    # di atas tidak pernah terpicu. Dulu bot malah lompat balik ke level
    # awal rentang dan mengerjakan ulang 668..685 terus-menerus.
    if (state.LEVEL_END and state._rentang_max_seen >= state.LEVEL_END and not on_play
            and not state.PERLU_LOGIN):
        state.RENTANG_SELESAI = True
        state.STOP = True
        print(f"[RENTANG] level akhir {state._rentang_max_seen} selesai (keluar dari "
              f"lesson) - bot selesai.")
        return True
    if on_play:
        if state.LEVEL_START <= 1 or state._rentang_jump_done:
            return False
        # Jangan lompat balik ke awal rentang kalau level dalam rentang sudah
        # pernah dikerjakan sesi ini - user sengaja membuka level itu.
        if state._rentang_max_seen >= state.LEVEL_START and state._rentang_max_seen > 1:
            return False
    # 2) di lesson yang di bawah awal rentang -> lompat
    if on_play:
        if nomor and nomor < state.LEVEL_START and time.time() - state._rentang_nav > 10:
            state._rentang_nav = time.time()
            print(f"[RENTANG] level {nomor} di bawah awal ({state.LEVEL_START}) "
                  f"- lompat ke level {state.LEVEL_START}")
            if levels._goto_level_url(state.LEVEL_START):
                state._rentang_jump_done = True
            else:
                print("[RENTANG] URL level awal belum ada di peta - "
                      "bangun peta dulu (tombol Rentang).")
            return True
        return False
    # 3) tidak di lesson (daftar/home edclub) dan sudah login, user diam:
    # kembali ke level yang sedang dikerjakan sesi ini (LEVEL_START kalau
    # belum ada), bukan level terdepan akun. (Keluhan live: user diam di
    # daftar pelajaran, recovery malah membuka L106 terdepan dan bot
    # mengetiknya.) Dulu case ini dibiarkan ke recovery.
    if not state.PERLU_LOGIN and not typing_core._user_aktif(25.0) \
            and time.time() - state._rentang_nav > 10:
        state._rentang_nav = time.time()
        lanjut = max(state.LEVEL_START, state._rentang_max_seen)
        if levels._goto_level_url(lanjut):
            state._rentang_jump_done = True
            print(f"[RENTANG] kembali ke level {lanjut}...")
            return True
        print("[RENTANG] URL level lanjut belum ada di peta - lanjut otomatis.")
    return False
