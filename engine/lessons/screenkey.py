"""Keyboard layar (klik tombol highlight)."""

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

from .. import state
from .. import jsutil
from ..jstemplates import (SCREENKEY_JS)




def click_screen_keyboard():
    if time.time() < state._scrkey["until"]:
        return False
    for fr in jsutil.all_frames():
        hit = jsutil.run_js(SCREENKEY_JS, fr)
        if hit:
            k = hit.get("key") or ""
            if k == state._scrkey["key"]:
                state._scrkey["count"] += 1
                if state._scrkey["count"] >= 4:
                    # klik berulang tanpa kemajuan (klik JS tidak selalu
                    # diterima) - beri jeda supaya tidak spam
                    state._scrkey["until"] = time.time() + 10
                    state._scrkey["count"] = 0
                    print("[Keyboard-layar] klik tanpa efek, jeda 10 detik")
                    return False
            else:
                state._scrkey["key"] = k
                state._scrkey["count"] = 1
            print(f"[Keyboard-layar] klik '{k}' ({hit.get('sel')})")
            state.stats["uikey"] += 1
            state.last_action_time = time.time()
            return True
    return False
