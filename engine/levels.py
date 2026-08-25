"""Peta level, rentang, validasi kunci, navigasi daftar pelajaran."""

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
from . import jsutil
from . import session
from .config import (LIST_URL, _LEVEL_MAP_FILE)




def _lesson_id(url):
    m = re.search(r"/program-(\d+)/(\d+)\.play", url or "")
    return int(m.group(2)) if m else None


def _level_map_muat():
    try:
        with open(_LEVEL_MAP_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            state._level_map.update({str(k): v for k, v in data.items()})
    except Exception:
        pass


def _level_map_catat(nomor, url):
    """Simpan asosiasi level -> URL (mis. '87' -> '...192.play')."""
    if not nomor or not url or ".play" not in url:
        return
    k = str(nomor)
    if state._level_map.get(k) == url:
        return
    state._level_map[k] = url
    try:
        with open(_LEVEL_MAP_FILE, "w", encoding="utf-8") as f:
            json.dump(state._level_map, f, indent=1, sort_keys=True)
    except Exception:
        pass


_level_map_muat()
for _n, _u in state._level_map.items():
    try:
        state._url_ke_level[int(_u.rsplit("/", 1)[1].split(".")[0])] = int(_n)
    except Exception:
        pass


def url_ke_level(url):
    """Nomor level dari URL .play via peta terbalik (pasti & instan,
    tidak menunggu teks halaman termuat)."""
    try:
        m = re.search(r"/program-\d+/(\d+)\.play", url or "")
        if m:
            return state._url_ke_level.get(int(m.group(1)))
    except Exception:
        pass
    return None


def _baca_unlock_set():
    """Set nomor level yang TERKUNCI/TERBUKA: kumpulkan nomor lesson yang
    punya class 'is_unlocked' di daftar lesson. Akun baru/logout = hanya
    level 1. None = daftar tidak terbaca."""
    if state.browser is None:
        return None
    pg = None
    try:
        pg = state.browser.contexts[0].new_page()
        pg.goto(LIST_URL, timeout=30000)
        pg.wait_for_selector("div.box-container", timeout=15000)
        time.sleep(1.0)
        data = pg.evaluate(r"""() => {
            const rows = [...document.querySelectorAll('div.box-container')];
            const out = [];
            for (const r of rows) {
                if (!(r.className || '').includes('is_unlocked')) continue;
                const m = (r.getAttribute('aria-label') || '')
                    .match(/Lesson (\d+)/);
                if (m) out.push(parseInt(m[1], 10));
            }
            return out;
        }""")
        return set(data or [])
    except Exception:
        return None
    finally:
        try:
            if pg is not None:
                pg.close()
        except Exception:
            pass


def _rentang_validasi_step():
    """Validasi NON-BLOKIR: LEVEL_START harus level TERBUKA di akun
    (terkunci = halaman kosong, bot akan thrash). Dipanggil tiap iterasi
    loop utama SETELAH gerbang login (live 00:04: validasi lama jalan
    SEBELUM patroli login pertama -> daftar logout hanya L1 terbuka ->
    '662 terkunci' padahal user bahkan belum login, dan wait 300 dtk
    membekukan seluruh loop: popup login & tanya rentang tak pernah
    muncul). Return False = user memilih stop."""
    if state._rentang_validasi_done or state.LEVEL_START <= 1:
        state._rentang_validasi_done = True
        return True
    # Tunda selama status login belum pasti / belum login: daftar level
    # versi logout selalu 'hanya level 1' - memvalidasi sekarang hanya
    # menghasilkan popup terkunci palsu. Setelah login, _rentang_cek
    # mengantar ke level awal; level benar2 terkunci tetap ditangani
    # runtime (deteksi halaman kosong).
    if state.PERLU_LOGIN or not state.LOGIN_DICEK:
        return True
    try:
        if session._profil_login() == "out":
            state._rentang_validasi_done = True
            return True
    except Exception:
        pass
    # user sudah membuka lesson sendiri = kerjakan itu, tanpa validasi/
    # lompatan (level terkunci yang dibuka sendiri oleh user adalah urusan
    # user - edclub yang mengizinkan/menolaknya, bukan bot)
    try:
        if ".play" in (browser._real_url(state.PAGE) or ""):
            state._rentang_validasi_done = True
            return True
    except Exception:
        pass
    if state._unlock_set is None:
        state._unlock_set = _baca_unlock_set()
    if state._unlock_set is None or state.LEVEL_START in state._unlock_set:
        state._rentang_validasi_done = True
        return True   # tidak bisa dibaca / memang terbuka: lanjut saja
    fallback = max(state._unlock_set) if state._unlock_set else 1
    print(f"[RENTANG] level {state.LEVEL_START} masih TERKUNCI di akun ini - "
          f"terbuka sampai level {fallback}.")
    ev = threading.Event()
    state.LEVEL_TANYA.update(aktif=True, start=state.LEVEL_START, fallback=fallback,
                       jawab="", event=ev)
    # tunggu bertahap: jawaban GUI, STOP, atau 300 dtk (timeout = mulai)
    batas = time.time() + 300
    while not ev.is_set() and not state.STOP and time.time() < batas:
        ev.wait(timeout=1.0)
    state.LEVEL_TANYA["aktif"] = False
    jawab = state.LEVEL_TANYA["jawab"] or "mulai"   # timeout = lanjut dari fallback
    state._rentang_validasi_done = True
    if jawab == "stop":
        print("[RENTANG] dibatalkan user - bot tidak jalan.")
        return False
    state.LEVEL_START = fallback
    print(f"[RENTANG] mulai dari level {state.LEVEL_START} "
          "(posisi terdepan akun).")
    return True


def _goto_level_url(nomor):
    """Buka lesson nomor N langsung dari peta (level_map.json)."""
    url = state._level_map.get(str(nomor))
    if not url:
        return False
    try:
        state.PAGE.goto(url, timeout=25000)
        return True
    except Exception:
        return False


def bangun_peta_level():
    """Bangun peta level -> URL lengkap (1..685) dengan membuka daftar
    lesson lalu menklik tiap baris dan merekam URL .play-nya (~1.3 dtk/
    level, sekali per akun). Baris daftar terverifikasi: aria-label
    'Lesson N' sesuai urutan. Jalan di tab terpisah supaya PAGE aktif
    tidak terganggu."""
    if state.browser is None:
        print("[PETA] belum terhubung ke browser.")
        return 0
    pg = None
    baru = 0
    try:
        pg = state.browser.contexts[0].new_page()
        pg.goto(LIST_URL, timeout=30000)
        pg.wait_for_selector("div.box-container", timeout=15000)
        total = pg.evaluate(
            "() => document.querySelectorAll('div.box-container').length") or 0
        if not total:
            print("[PETA] daftar lesson tidak terbaca.")
            return 0
        print(f"[PETA] membangun peta {total} level "
              f"(estimasi {total * 1.4 / 60:.0f} menit, jangan tutup bot)...")
        for i in range(total):
            while state.PAUSED and not state.STOP:
                time.sleep(0.3)
            if state.STOP:
                print(f"[PETA] dihentikan di level {i + 1} "
                      f"(bisa dilanjutkan lain waktu).")
                break
            try:
                try:  # modal premium di tab peta -> tutup dulu
                    x = pg.locator(".edmodal-x")
                    if x.count():
                        x.first.click(timeout=800)
                        time.sleep(0.3)
                except Exception:
                    pass
                lbl = pg.evaluate(
                    "(i)=>{const r=[...document.querySelectorAll"
                    "('div.box-container')][i];"
                    "return r ? (r.getAttribute('aria-label')||'') : '';}", i)
                m = re.match(r"Lesson\s+(\d+)", lbl or "")
                nomor = int(m.group(1)) if m else i + 1
                if str(nomor) in state._level_map:
                    continue   # sudah terpetakan (resume cepat tanpa klik)
                pg.evaluate(
                    "(i)=>{const r=[...document.querySelectorAll"
                    "('div.box-container')][i]; if(r) r.click();}", i)
                url = None
                for fase in range(40):
                    time.sleep(0.1)
                    u = pg.evaluate("() => location.href")
                    if u and ".play" in u:
                        url = u
                        break
                    if fase == 12:
                        # lesson terkunci: edclub menampilkan modal 'Are you
                        # sure? ... jumping ahead' dengan tombol Continue -
                        # klik lanjut supaya navigasi tetap terjadi .
                        pg.evaluate("""() => {
                            const t = [...document.querySelectorAll(
                                'button, .btn, [role=button]')];
                            const b = t.find(x =>
                                /continue|lanjut/i.test(x.textContent || '')
                                && x.offsetParent !== null);
                            if (b) b.click();
                        }""")
                if url and state._level_map.get(str(nomor)) != url:
                    _level_map_catat(nomor, url)
                    baru += 1
                # go_back hanya kalau memang navigasi ke .play terjadi;
                # baris yang tidak bisa diklik (mis. bagian khusus akhir
                # daftar) tidak menavigasi -> go_back dari daftar justru
                # membawa tab ke about:blank dan builder nyangkut .
                if url:
                    pg.go_back(timeout=15000)
                    pg.wait_for_selector("div.box-container", timeout=15000)
                if (i + 1) % 25 == 0:
                    print(f"[PETA] {i + 1}/{total} level terpetakan...")
            except Exception:
                pulih = False
                for _ in range(3):
                    try:
                        pg.goto(LIST_URL, timeout=30000)
                        pg.wait_for_selector("div.box-container",
                                            timeout=15000)
                        pulih = True
                        break
                    except Exception:
                        time.sleep(2)
                        try:   # tab bisa mati -> tab baru
                            pg.close()
                        except Exception:
                            pass
                        pg = state.browser.contexts[0].new_page()
                if not pulih:
                    print("[PETA] daftar tidak bisa dibuka lagi - berhenti "
                          "(lanjutkan lain waktu, sudah terpetakan "
                          f"{len(state._level_map)}).")
                    break
        print(f"[PETA] selesai: +{baru} baru, total {len(state._level_map)} "
              f"level terpetakan (level_map.json).")
    finally:
        try:
            if pg is not None:
                pg.close()
        except Exception:
            pass
    return baru


def _level_label():
    """Nomor level ASLI (mis. 'L87') dari teks halaman. Nomor URL edclub
    adalah id konten (bukan linear - setelah 651 langsung 8830), jadi
    indikator tidak boleh memakai rumus URL. Halaman menampilkan
    'Lesson 87: ...'."""
    try:
        url = state.PAGE.url
    except Exception:
        return ""
    if url in state._level_label_cache:
        return state._level_label_cache[url]
    nomor = jsutil.run_js(r"""
const t = document.body ? document.body.innerText.slice(0, 400) : '';
const m = t.match(/Lesson\s+(\d+)/);
return m ? m[1] : null;
""", state.PAGE.main_frame)
    lab = f"L{nomor}" if nomor else ""
    # Cache hanya yang berhasil: halaman yang belum selesai memuat masih
    # kosong; kalau dikosongkan pun, cache "" akan menutup label selamanya
    # untuk URL itu (pernah membuat indikator level GUI selalu salah).
    if nomor:
        state._level_label_cache[url] = lab
        _level_map_catat(nomor, url)
    return lab


def _wait_play_url(newpg):
    for _ in range(16):
        time.sleep(0.5)
        if state.STOP:
            return None
        try:
            u = newpg.evaluate("() => location.href")
        except Exception:
            u = None
        if u and ".play" in u and browser._is_edclub_url(u):
            return u
    return None


def _goto_next_lesson_in_list(newpg, current_url):
    """Buka daftar pelajaran dan klik pelajaran berikutnya SESUAI URUTAN
    KURSUS. Nomor URL edclub tidak berurutan (setelah 189.play situs
    lanjut ke 2959.play) - jangan hitung N+1. Klik baris
    pertama yang belum dikerjakan; kalau itu malah lesson yang baru
    ditinggalkan (level rusak) atau lesson yang sudah ditandai rusak,
    klik baris TEPAT SETELAH baris itu. Return URL .play, None jika gagal."""
    cur = _lesson_id(current_url)
    row = 0
    for _ in range(6):
        if state.STOP:
            return None
        try:
            newpg.goto(LIST_URL, timeout=25000)
            newpg.wait_for_selector("div.box-container div.lsn_name",
                                    timeout=15000)
        except Exception:
            continue
        idx = newpg.evaluate("""(arg) => {
            const rows = [...document.querySelectorAll('div.box-container')];
            for (let i = arg; i < rows.length; i++) {
                const cls = rows[i].className || '';
                if (!cls.includes('is_unlocked') || cls.includes('has_progress')) continue;
                const nm = rows[i].querySelector('div.lsn_name');
                if (nm) { nm.click(); return i; }
            }
            return -1;
        }""", row)
        if idx is None or idx < 0:
            continue
        row = idx + 1
        url = _wait_play_url(newpg)
        if not url:
            continue
        lid = _lesson_id(url)
        if lid != cur and lid not in state._broken_lessons:
            return url
        # baris ini = level rusak itu sendiri / sudah ditandai rusak
        # -> ulangi dari baris setelahnya.
    return None


def _skip_to_next_lesson(alasan):
    """Level rusak/premium-beku: buka tab BARU ke pelajaran berikutnya
    menurut URUTAN DAFTAR (bukan N+1 URL), tutup tab lama."""
    base = state.last_url if (state.last_url and ".play" in state.last_url) else ""
    if not base:
        try:
            base = browser._real_url(state.PAGE)
        except Exception:
            base = ""
    if ".play" not in base:
        return False
    lid = _lesson_id(base)
    if lid:
        state._broken_lessons.add(lid)
    # Coba di tab yang sama dulu (tanpa buka tab baru - user terganggu
    # dengan tab baru terus-menerus). Tab baru hanya kalau tab sekarang
    # mati (evaluate/goto gagal).
    url = None
    newpg = state.PAGE
    try:
        url = _goto_next_lesson_in_list(newpg, base)
    except Exception:
        url = None
    if url is None:
        try:
            newpg = state.PAGE.context.new_page()
            url = _goto_next_lesson_in_list(newpg, base)
        except Exception:
            url = None
        if url is None:
            try:
                newpg.close()
            except Exception:
                pass
            return False
        old = state.PAGE
        state.PAGE = newpg
        try:
            if old is not newpg:
                old.close()
        except Exception:
            pass
    state._recovery_counts.pop(base, None)
    state._hijack_counts.pop(base, None)
    state.last_url = state.PAGE.url
    state.last_action_time = time.time()
    state._last_recovery = time.time()
    print(f"[SKIP] {alasan} - lanjut ke {url.split('/')[-1]} "
          f"(urutan daftar pelajaran)")
    return True
