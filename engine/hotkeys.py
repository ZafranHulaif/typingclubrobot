"""Hotkey global F9 (jeda), F10 (kecepatan), F11 (stop)."""

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

try:
    import keyboard as _kb
    HAVE_HOTKEY = True
except Exception:
    HAVE_HOTKEY = False

from . import state
from .config import (SPEEDS)




def _toggle_pause():
    state.PAUSED = not state.PAUSED
    print(f">>> {'JEDA (paused)' if state.PAUSED else 'LANJUT (resume)'} <<<", flush=True)


def _cycle_speed():
    state.SPEED_IDX = (state.SPEED_IDX + 1) % len(SPEEDS)
    print(f">>> KECEPATAN: {SPEEDS[state.SPEED_IDX][1]} <<<", flush=True)


def _stop_bot():
    state.STOP = True
    print(">>> STOP diminta, menutup bot... <<<", flush=True)


# Wrapper cek HOTKEYS_ON: hook keyboard tidak dilepas-lepas saat toggle
# (re-hook bisa gagal diam-diam) - cukup diabaikan saat nonaktif. User bisa
# memakai F9/F10/F11 untuk aplikasi lain tanpa takut menggerakkan bot.
def _hk_pause():
    if state.HOTKEYS_ON:
        _toggle_pause()


def _hk_speed():
    if state.HOTKEYS_ON:
        _cycle_speed()


def _hk_stop():
    if state.HOTKEYS_ON:
        _stop_bot()


if HAVE_HOTKEY:
    try:
        _kb.add_hotkey("f9", _hk_pause)
        _kb.add_hotkey("f10", _hk_speed)
        _kb.add_hotkey("f11", _hk_stop)
    except Exception:
        HAVE_HOTKEY = False
