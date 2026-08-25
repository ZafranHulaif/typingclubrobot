"""Level "hold key"."""

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
from .. import typing_core
from ..jstemplates import (HOLD_JS, HOLD_KEY_MAP)




def map_hold_key(k):
    k = (k or "").strip().lower()
    if k in HOLD_KEY_MAP:
        return HOLD_KEY_MAP[k]
    if len(k) == 1 and k.isalpha():
        return k
    return None


def try_hold_level():
    for fr in jsutil.all_frames():
        instr = jsutil.run_js(HOLD_JS, fr)
        if not instr:
            continue
        key = map_hold_key(instr.get("key"))
        if not key:
            continue
        raw = instr.get("raw") or key
        if raw == state.last_hold_raw and state.hold_attempts >= 4:
            return False
        if raw != state.last_hold_raw:
            state.last_hold_raw = raw
            state.hold_attempts = 0
        state.hold_attempts += 1
        typing_core.focus_frame(fr)
        duration = min(1.5 * state.hold_attempts, 8.0)
        print(f"[Hold] instruksi '{raw}' -> menahan {duration:.1f}s (coba {state.hold_attempts})")
        try:
            state.PAGE.keyboard.down(key)
            time.sleep(duration)
        finally:
            try:
                state.PAGE.keyboard.up(key)
            except Exception:
                pass
        state.stats["hold"] += 1
        state.last_action_time = time.time()
        return True
    return False
