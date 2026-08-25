"""Pemulihan: halaman mati, tab salah, renderer suspend."""

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
from . import levels
from .config import (LIST_URL)
from .jstemplates import (PLAYABLE_CHECK_JS)




def _switch_to_playable_tab():
    """Kalau ada tab edclub lain yang jelas punya pekerjaan (token _clr /
    boxed aktif) sedangkan tab sekarang sunyi - pindah ke sana.
    Return True kalau pindah."""
    try:
        pages = [pg for pg in state.browser.contexts[0].pages
                 if pg is not state.PAGE]
    except Exception:
        return False
    best, best_score = None, 0
    for pg in pages:
        try:
            url = browser._real_url(pg)
            if not browser._is_edclub_url(url):
                continue
            if ".play" not in url:
                continue
            info = pg.evaluate("() => {" + PLAYABLE_CHECK_JS + "}")
            s = 0
            if info:
                if info.get("clr"):
                    s += 5
                elif info.get("boxed"):
                    s += 3
                if info.get("done"):
                    s -= 8
        except Exception:
            continue
        if s > best_score:
            best, best_score = pg, s
    if best is not None:
        print(f"[TAB] pindah ke tab lain yang ada kerjaannya: "
              f"{best.url.split('/')[-1]}")
        state.PAGE = best
        state.last_url = ""
        state.last_action_time = time.time()
        return True
    return False


def recover_and_restart_lesson():
    """Pulihkan halaman macet/kosong. UTAMA: RELOAD TAB YANG SAMA -
    tab baru hanya kalau reload gagal (tab benar2 mati) atau URL lesson
    tidak diketahui. (Dulu selalu tab baru: mengganggu user dan pernah
    bertabrakan dengan refresh manual user.)"""
    state._last_recovery = time.time()
    target = state.last_url if (state.last_url and ".play" in state.last_url) else None

    if target:
        n = state._recovery_counts.get(target, 0) + 1
        state._recovery_counts[target] = n
        if n >= 3:
            # Lesson ini sudah berkali-kali recovery tetap mati = level
            # rusak -> pelajaran berikutnya sesuai urutan daftar (nomor
            # URL edclub tidak berurutan, jangan hitung N+1).
            if levels._skip_to_next_lesson("recovery berulang, level rusak"):
                return True
            return False
        try:
            state.PAGE.reload(timeout=25000)
            print(f"[RECOVERY] reload tab yang sama: "
                  f"{target.split('/')[-1]}")
            state.last_typed_text = ""
            state._std_last_rem = None    # biar handle_standard mau ketik ulang
            state._std_attempts = 0
            state.last_url = state.PAGE.url
            state.last_action_time = time.time()
            return True
        except Exception as e:
            print(f"[RECOVERY] reload gagal ({str(e)[:60]}) - coba tab baru")

    print("[RECOVERY] Halaman macet/kosong, membuka tab baru...")
    try:
        newpg = state.PAGE.context.new_page()
    except Exception as e:
        print(f"[RECOVERY] gagal bikin tab: {str(e)[:80]}")
        return False

    if target:
        try:
            newpg.goto(target, timeout=25000)
            print(f"[RECOVERY] muat ulang lesson yang sama: {target.split('/')[-1]}")
        except Exception as e:
            print(f"[RECOVERY] gagal muat ulang: {str(e)[:80]}")
            try:
                newpg.close()
            except Exception:
                pass
            return False
    else:
        # Rentang aktif: kembali ke level sesi (max start vs yang sudah
        # dilihat), bukan baris pertama di daftar (= level terdepan akun,
        # ). Fallback: baris pertama seperti biasa.
        lanjut_lvl = 0
        try:
            if state.RANGE_READY and (state.LEVEL_START > 1 or state.LEVEL_END):
                lanjut_lvl = max(state.LEVEL_START, state._range_max_seen)
        except Exception:
            lanjut_lvl = 0
        if lanjut_lvl and str(lanjut_lvl) in state._level_map:
            try:
                newpg.goto(state._level_map[str(lanjut_lvl)], timeout=25000)
                print(f"[RECOVERY] kembali ke level {lanjut_lvl} sesi ini")
                _finish_recovery(newpg)
                return True
            except Exception as e:
                print(f"[RECOVERY] gagal kembali ke level {lanjut_lvl} "
                      f"({str(e)[:60]}) - coba daftar")
                try:
                    newpg.close()
                    newpg = state.PAGE.context.new_page()
                except Exception:
                    return False
        try:
            newpg.goto(LIST_URL, timeout=20000)
        except Exception as e:
            print(f"[RECOVERY] gagal buka daftar: {str(e)[:80]}")
            try:
                newpg.close()
            except Exception:
                pass
            return False
        try:
            newpg.wait_for_selector("div.lsn_name", timeout=15000)
        except Exception:
            pass
        clicked = None
        try:
            clicked = newpg.evaluate("""
            () => {
                const rows = document.querySelectorAll('div.box-container.is_unlocked:not(.has_progress)');
                for (const r of rows) {
                    const nm = r.querySelector('div.lsn_name');
                    if (nm) { nm.click(); return (nm.innerText||'').trim(); }
                }
                const any = document.querySelector('div.lsn_name');
                if (any) { any.click(); return '(pertama) ' + (any.innerText||'').trim(); }
                return null;
            }
            """)
        except Exception:
            pass
        if not clicked:
            print("[RECOVERY] baris pelajaran tidak ditemukan")
            try:
                newpg.close()
            except Exception:
                pass
            return False
        print(f"[RECOVERY] membuka pelajaran: {clicked}")

    _finish_recovery(newpg)
    return True


def _finish_recovery(newpg):
    """ tunggu tab recovery siap, jadikan tab utama, tutup tab lama """
    for _ in range(15):
        try:
            newpg.wait_for_timeout(1000)
        except Exception:
            time.sleep(1)
        if ".play" in newpg.url:
            break
    try:
        old = state.PAGE
        state.PAGE = newpg
        if old is not newpg:
            old.close()
    except Exception:
        pass
    state.last_typed_text = ""
    state.last_url = state.PAGE.url
    state.last_action_time = time.time()
    return True
