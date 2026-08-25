"""Level video (play, seek, skip)."""

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
from ..jstemplates import (VIDEO_SKIP_JS, VIDEO_STATE_JS)




def handle_video_level():
    for fr in jsutil.all_frames():
        info = jsutil.run_js(VIDEO_STATE_JS, fr)
        if not info:
            continue
        if info.get("paused"):
            try:
                btn = fr.locator(".vjs-big-play-button").first
                typing_core._mark_bot_click(fr)
                btn.click(timeout=2000)
                time.sleep(0.8)
            except Exception:
                pass
        jsutil.run_js(VIDEO_SKIP_JS, fr)
        state.stats["video"] += 1
        state.last_action_time = time.time()
        print(f"[Video] {jsutil.frame_label(fr)}: dilompat ke akhir")
        time.sleep(0.5)
        return True
    return False
