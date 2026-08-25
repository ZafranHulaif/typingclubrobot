"""Profil user: enumerasi, junction untuk Chrome/Edge 136+, tutup browser yang sedang jalan."""

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
from . import browser




def _ud_browser_dir(nama):
    """Folder data (User Data) ASLI milik browser terpasang. Return '' bila
    browser tidak dikenal/foldernya tidak ada."""
    base = os.path.expandvars("%LOCALAPPDATA%")
    kandidat = {
        "Brave": base + r"\BraveSoftware\Brave-Browser\User Data",
        "Chrome": base + r"\Google\Chrome\User Data",
        "Edge": base + r"\Microsoft\Edge\User Data",
    }
    ud = kandidat.get(nama, "")
    return ud if ud and os.path.isdir(ud) else ""


def _profil_daftar(nama):
    """Daftar profil manusia di browser terpasang (dibaca dari 'Local
    State', tanpa membuka browser). Return list {'dir','nama','email',
    'utama'}; 'Default' selalu di urutan pertama."""
    ud = _ud_browser_dir(nama)
    if not ud:
        return []
    try:
        with open(os.path.join(ud, "Local State"), encoding="utf-8") as f:
            info = json.load(f)
        cache = info.get("profile", {}).get("info_cache", {}) or {}
    except Exception:
        return []
    hasil = []
    for d, v in cache.items():
        if not isinstance(v, dict):
            continue
        nm = (v.get("name") or d).strip() or d
        hasil.append({"dir": d, "nama": nm,
                      "email": (v.get("user_name") or "").strip(),
                      "utama": d == "Default"})
    hasil.sort(key=lambda p: (not p["utama"], p["nama"].lower()))
    return hasil


def _ud_profil_arg(nama):
    """Argumen --user-data-dir untuk mode 'profil saya'. Brave: folder asli.
    Chrome/Edge: JUNCTION ke folder asli (path beda, data sama - satu2nya
    cara melewati larangan debug Chromium 136+ pada folder asli).
    Return '' bila tidak bisa (folder tidak ada / profil tidak ada)."""
    ud = _ud_browser_dir(nama)
    if not ud:
        return ""
    if state.PROFILE_DIR and not os.path.isdir(os.path.join(ud, state.PROFILE_DIR)):
        print(f"[PROFIL] profil '{state.PROFILE_DIR}' tidak ada di {nama} - "
              "memakai profil khusus bot.")
        return ""
    if nama == "Brave":
        return ud
    link = os.path.join(os.path.dirname(state.DEDICATED_PROFILE),
                        "ud_" + nama.lower())
    try:
        os.makedirs(os.path.dirname(link), exist_ok=True)
        if os.path.exists(link):
            os.rmdir(link)          # junction: hanya link yang terhapus
        r = browser._run_hidden(["cmd", "/c", "mklink", "/J", link, ud],
                        capture_output=True, text=True, timeout=15)
        if "Junction created" in (r.stdout or "") or \
                "created" in (r.stdout or "").lower():
            return link
        print(f"[PROFIL] gagal membuat pintasan folder ({(r.stderr or '')[:60]})"
              " - memakai profil khusus bot.")
    except Exception as ex:
        print(f"[PROFIL] gagal menyiapkan folder profil ({ex}) "
              "- memakai profil khusus bot.")
    return ""


def _proses_berdasar_nama(proc):
    """PID semua proses dengan nama image tertentu (brave.exe dsb.),
    hasil tasklist diurut seperti biasa (kolom ke-2 = PID)."""
    pids = []
    try:
        out = browser._run_hidden(["tasklist", "/FI", f"IMAGENAME eq {proc}"],
                          capture_output=True, text=True, timeout=8).stdout
        for ln in out.splitlines():
            bagian = ln.split()
            if (len(bagian) >= 2 and bagian[0].lower() == proc.lower()
                    and bagian[1].isdigit()):
                pids.append(int(bagian[1]))
    except Exception:
        pass
    return pids


def _tutup_browser_user(proc, nama):
    """Mode 'profil saya': browser harus BETUL2 mati dulu agar bisa
    diluncurkan ulang dengan profil user + mode debug (jika masih jalan,
    proses baru hanya membuka jendela di proses lama TANPA debug).
    Selalu minta izin user (dialog logo) sebelum menutup.
    Return False bila user menolak -> pemanggil jatuh ke profil khusus."""
    pids = _proses_berdasar_nama(proc)
    if not pids:
        return True
    exe, _induk = browser._exe_info_pid(pids[0])
    print(f"[PROFIL] {nama} sedang jalan - bot perlu menutupnya dulu "
          "untuk memakai profil kamu.")
    if not browser._tanya_tutup(nama, pids[0], exe):
        print("[PROFIL] tidak ditutup - bot memakai profil khusus saja.")
        return False
    for pid in pids:
        try:
            browser._run_hidden(["taskkill", "/F", "/T", "/PID", str(pid)],
                        capture_output=True, timeout=8)
        except Exception:
            pass
    for _ in range(10):
        time.sleep(0.5)
        if not _proses_berdasar_nama(proc):
            break
    return True
