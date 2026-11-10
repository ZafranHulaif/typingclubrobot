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
from .jstemplates import (SPA_SKIP_JS)




def _lesson_id(url):
    m = re.search(r"/program-(\d+)/(\d+)\.play", url or "")
    return int(m.group(2)) if m else None


def _load_level_map():
    try:
        with open(_LEVEL_MAP_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            state._level_map.update({str(k): v for k, v in data.items()})
    except Exception:
        pass


def _record_level_map(nomor, url):
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


_load_level_map()
for _n, _u in state._level_map.items():
    try:
        state._url_to_level[int(_u.rsplit("/", 1)[1].split(".")[0])] = int(_n)
    except Exception:
        pass


def url_to_level(url):
    """Nomor level dari URL .play via peta terbalik (pasti & instan,
    tidak menunggu teks halaman termuat)."""
    try:
        m = re.search(r"/program-\d+/(\d+)\.play", url or "")
        if m:
            return state._url_to_level.get(int(m.group(1)))
    except Exception:
        pass
    return None


def _posisi_path():
    return os.path.join(os.path.dirname(_LEVEL_MAP_FILE),
                        "posisi_level.json")


def catat_posisi(n):
    """Level terakhir yang dikerjakan bot - dipakai kartu 'Lanjut'
    di dialog pilih mulai (nomornya = level berikutnya yang belum
    selesai, level premium/terkunci memang tak pernah dikerjakan).
    Tidak pernah mundur."""
    if not n or n <= state.POSISI_LEVEL:
        return
    state.POSISI_LEVEL = n
    try:
        with open(_posisi_path(), "w", encoding="utf-8") as f:
            json.dump({"posisi": n}, f)
    except Exception:
        pass


def muat_posisi():
    try:
        with open(_posisi_path(), encoding="utf-8") as f:
            state.POSISI_LEVEL = int(json.load(f).get("posisi", 0) or 0)
    except Exception:
        pass
    return state.POSISI_LEVEL


def _wait_daftar(pg):
    """Buka daftar lesson & tunggu barisnya (UI baru ATAU lama)."""
    pg.goto(LIST_URL, timeout=30000)
    pg.wait_for_selector("a[aria-label^='Lesson '], div.box-container",
                         timeout=20000)


def _baca_unlock_js(pg):
    """Set nomor level terbuka dari daftar (dua UI)."""
    return set(pg.evaluate(r"""() => {
        const parse = aria => { const m = (aria||'').match(/Lesson (\d+)/);
          return m ? parseInt(m[1], 10) : 0; };
        const out = [];
        const baru = [...document.querySelectorAll('a[aria-label^="Lesson "]')];
        if (baru.length) {
            for (const a of baru)
                if (!/is locked/i.test(a.getAttribute('aria-label')||'')) {
                    const n = parse(a.getAttribute('aria-label')); if (n) out.push(n);
                }
        } else {
            for (const r of document.querySelectorAll('div.box-container')) {
                if (!((r.className||'') + '').includes('is_unlocked')) continue;
                const m = (r.getAttribute('aria-label')||'').match(/Lesson (\d+)/);
                if (m) out.push(parseInt(m[1], 10));
            }
        }
        return out;
    }""") or [])


def _read_unlock_set():
    """Set nomor level yang TERKUNCI/TERBUKA: kumpulkan nomor lesson yang
    punya class 'is_unlocked' di daftar lesson. Akun baru/logout = hanya
    level 1. None = daftar tidak terbaca. Redirect TAB UTAMA pulang-pergi
    (dulu tab cadangan - tab baru selalu mengangkat jendela browser,
    keluhan live)."""
    if state.browser is None:
        return None
    pg = state.PAGE
    try:
        asal = browser._real_url(pg) or ""
    except Exception:
        return None
    kembali = asal if ".play" in asal else ""
    try:
        _wait_daftar(pg)
        time.sleep(1.0)
        return _baca_unlock_js(pg)
    except Exception:
        return None
    finally:
        if kembali:
            try:
                pg.goto(kembali, timeout=25000)
            except Exception:
                pass


def _range_validate_step():
    """Validasi NON-BLOKIR: LEVEL_START harus level TERBUKA di akun
    (terkunci = halaman kosong, bot akan thrash). Dipanggil tiap iterasi
    loop utama SETELAH gerbang login (live 00:04: validasi lama jalan
    SEBELUM patroli login pertama -> daftar logout hanya L1 terbuka ->
    '662 terkunci' padahal user bahkan belum login, dan wait 300 dtk
    membekukan seluruh loop: popup login & tanya rentang tak pernah
    muncul). Return False = user memilih stop."""
    if state._range_validated or state.LEVEL_START <= 1:
        state._range_validated = True
        return True
    # Tunda selama status login belum pasti / belum login: daftar level
    # versi logout selalu 'hanya level 1' - memvalidasi sekarang hanya
    # menghasilkan popup terkunci palsu. Setelah login, _range_check
    # mengantar ke level awal; level benar2 terkunci tetap ditangani
    # runtime (deteksi halaman kosong).
    if state.NEEDS_LOGIN or not state.LOGIN_DICEK:
        return True
    try:
        if session._login_profile() == "out":
            state._range_validated = True
            return True
    except Exception:
        pass
    # user sudah membuka lesson sendiri = kerjakan itu, tanpa validasi/
    # lompatan (level terkunci yang dibuka sendiri oleh user adalah urusan
    # user - edclub yang mengizinkan/menolaknya, bukan bot)
    try:
        if ".play" in (browser._real_url(state.PAGE) or ""):
            state._range_validated = True
            return True
    except Exception:
        pass
    # edclub membuka level BERURUTAN: POSISI_LEVEL = level terdepan
    # akun (pertama yang belum selesai) -> semua level di bawahnya
    # PASTI terbuka. Cek tanpa navigasi (live bug: baca set unlock dari
    # daftar lama hanya dapat bagian lazy-load 64-66 -> level 35
    # dianggap terkunci -> popup salah 'masih terkunci' + fallback 66).
    if state.POSISI_LEVEL and state.LEVEL_START <= state.POSISI_LEVEL:
        state._range_validated = True
        return True
    if state._unlock_set is None:
        state._unlock_set = _read_unlock_set()
    # set partial (daftar lazy-load): ada level terbaca >= start =
    # start pasti terbuka (urutan edclub). Dulu 'start in set' ->
    # popup palsu tiap set cuma memuat satu bagian daftar.
    if (state._unlock_set is None or not state._unlock_set
            or max(state._unlock_set) >= state.LEVEL_START):
        state._range_validated = True
        return True
    fallback = max(state._unlock_set) if state._unlock_set else 1
    print(f"[RENTANG] level {state.LEVEL_START} masih TERKUNCI di akun ini - "
          f"terbuka sampai level {fallback}.")
    ev = threading.Event()
    state.LEVEL_ASKED.update(aktif=True, start=state.LEVEL_START, fallback=fallback,
                       jawab="", event=ev)
    # tunggu bertahap: jawaban GUI, STOP, atau 300 dtk (timeout = mulai)
    batas = time.time() + 300
    while not ev.is_set() and not state.STOP and time.time() < batas:
        ev.wait(timeout=1.0)
    state.LEVEL_ASKED["aktif"] = False
    jawab = state.LEVEL_ASKED["jawab"] or "mulai"   # timeout = lanjut dari fallback
    state._range_validated = True
    if jawab == "stop":
        print("[RENTANG] dibatalkan user - bot tidak jalan.")
        return False
    state.LEVEL_START = fallback
    print(f"[RENTANG] mulai dari level {state.LEVEL_START} "
          "(posisi terdepan akun).")
    return True


def _lesson_hidup(pg, batas=8.0):
    """Lesson benar-benar dirender (canvas/video/isi teks muncul) - bukan
    halaman kosong (URL 403/SPA mati: live: level 1 -> 116.play PUTIH,
    config 404, 'reading sources'). Live level 2 = body 357 -> ambang
    200, bukan 400."""
    mulai = time.time()
    while time.time() - mulai < batas:
        if state.STOP:
            return False
        try:
            n = pg.evaluate(
                "() => ({c: document.querySelectorAll('canvas').length," 
                "v: !!document.querySelector('video')," 
                "b: document.body ? document.body.innerText.length : 0," 
                "u: location.href})")
        except Exception:
            n = None
        if n and ".play" in (n.get("u") or "") \
                and (n.get("c") or n.get("v") or (n.get("b") or 0) > 200):
            return True
        if n and ".play" in (n.get("u") or "") \
                and _gate_atau_mulai(pg):
            # lesson di balik gerbang audio ('Sound can only play once
            # you start' + tombol Start, body cuma 59) = HALAMAN HIDUP
            return True
        time.sleep(0.5)
    return False


def _gate_atau_mulai(pg):
    """Gerbang audio / tombol Start terlihat di halaman lesson?"""
    try:
        return pg.evaluate(
            r"""() => !!document.querySelector(
                    'button[data-testid="audio-activation-gate"]')
                 || /sound can only play once you start/i
                    .test(document.body.innerText)""")
    except Exception:
        return False


def _goto_level_via_daftar(nomor):
    state.PETA_BANGUN = True     # pengawas: jangan bounce rute lama
    try:
        return _goto_level_via_daftar_isi(nomor)
    finally:
        state.PETA_BANGUN = False


def _goto_level_via_daftar_isi(nomor):
    """Klik baris/kartu 'Lesson N' di daftar lesson (UI baru & lama),
    tunggu URL .play (dinormalisasi dari rute SPA baru), lalu REKAM
    peta - peta level menyembuhkan dirinya dari URL stale. Level jauh
    butuh SCROLL: UI baru lazy-load per bagian (live: baru 23 kartu
    tampil, section 'Home Row' 1-23)."""
    if state.browser is None:
        return False
    pg = state.PAGE
    try:
        _wait_daftar(pg)
    except Exception:
        return False
    ketemu = -1
    for putaran in range(10):   # scroll sampai nomor ketemu / habis
        if state.STOP:
            return False
        try:
            ketemu = pg.evaluate(r"""(n) => {
              const parse = aria => { const m = (aria||'').match(/Lesson (\d+)/);
                return m ? parseInt(m[1], 10) : 0; };
              const baru = [...document.querySelectorAll('a[aria-label^="Lesson "]')];
              const rows = baru.length ? baru
                : [...document.querySelectorAll('div.box-container')];
              for (let i = 0; i < rows.length; i++) {
                const aria = baru.length ? rows[i].getAttribute('aria-label')
                                         : (rows[i].getAttribute('aria-label')||'');
                if (parse(aria) === n) return i;
              }
              return -1;
            }""", nomor)
        except Exception:
            ketemu = -1
        if ketemu >= 0:
            break
        # belum ketemu: scroll bawah untuk memuat section berikutnya
        try:
            pg.evaluate(
                "() => window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            break
        time.sleep(1.0)
    if ketemu < 0:
        return False
    try:
        pg.evaluate(_klik_baris_js(), ketemu)
    except Exception:
        return False
    url = _wait_play_url(pg)
    if state.STOP:
        return False
    if not url:
        return False
    # rute SPA baru kadang tidak mount lesson (live: body 61) - paksa
    # rute .play klasik yang sudah terbukti buat mesin ketik.
    try:
        mentah = pg.evaluate("() => location.href") or ""
    except Exception:
        mentah = ""
    if mentah and "/lesson/" in mentah and mentah != url:
        try:
            pg.goto(url, timeout=25000)
        except Exception:
            pass
    if state._level_map.get(str(nomor)) != url:
        _record_level_map(nomor, url)
        print(f"[PETA] level {nomor} diperbarui via daftar: {url}")
    return True


def url_untuk_level(nomor):
    """URL .play level N dari peta (TANPA menavigasi). Dipakai GUI:
    mengarahkan browser embed via watcher (ke_url) saat user memilih
    level di dialog - tanpa menyentuh state.PAGE dari thread Tk."""
    u = state._level_map.get(str(nomor)) or ""
    return u if ".play" in u else ""


def _goto_level_url(nomor):
    """Buka lesson nomor N langsung dari peta (level_map.json).

    v3.2: peta bisa STALE - course TypingClub direorganisasi (UI baru
    Nov 2026): URL id lama kini 403/blank (live: level 1 = 116.play
    putih terus). Setelah goto, lesson HARUS benar-benar hidup; kalau
    tidak, jatuh ke klik baris daftar & peta diperbarui otomatis."""
    url = state._level_map.get(str(nomor))
    if url:
        try:
            state.PAGE.goto(url, timeout=25000)
        except Exception:
            pass
        if _lesson_hidup(state.PAGE):
            return True
        print(f"[PETA] URL terpetakan level {nomor} tidak hidup "
              "(course berubah?) - pakai daftar lesson...")
    if _goto_level_via_daftar(nomor):
        # navigasi berhasil - halaman tetap kosong = LEVEL-nya yang rusak
        # (asset 404, live: level 1 akun baru). Bukan gagal navigasi:
        # biarkan supervisor TUNDA/skip yang menandai & melompati.
        return True
    return False


def baca_progres_akun(pg, maks_pas=3):
    """Baca progres ASLI akun dari halaman course (instal baru: peta bot
    kosong & posisi bot 0 - tapi edclub tahu posisi akunnya). Baris
    daftar virtualized dan edclub memosisikannya tepat di garis depan
    akun; tiap baris membawa status di aria-label:
      'Lesson N: ... Lesson completed'        -> selesai
      'Lesson N: ... N out of 5 stars earned' -> ada progres (dilewati)
      'Lesson N: ... Lesson is locked'        -> terkunci
      sisanya                                 -> belum disentuh
    TIDAK SCROLL (live: menggulung 685 baris terlihat user - 'it still
    scrolled itself', dia Stop dulu, scan selepus habis sia-sia). Baris
    awal jendela SAH saja: edclub memposisikan tepat di garis depan, dan
    baris sebelum jendela = pelajaran lama (terbuka berurutan = selesai).
    Return {total, pertama_baru, jendela_awal, rows} / None."""
    try:
        if pg is None:
            return None
        try:
            # evaluate jangan menggantung menit-menit saat halaman sibuk
            pg.set_default_timeout(6000)
        except Exception:
            pass
        js_kumpul = """() => [...document.querySelectorAll('[aria-label^="Lesson "]')].map(e => e.getAttribute("aria-label"))"""
        labels = set(pg.evaluate(js_kumpul) or [])
        if not labels:
            return None

        # tandai kontainer scroll (ancestor baris dgn overflow) sekali,
        # lalu scroll dia tiap putaran - window.scrollBy tidak menggerakkan
        # daftar virtualized ini (body scrollHeight cuma 553px, live).
        pg.evaluate("""() => {
            const row = document.querySelector('[aria-label^="Lesson "]');
            let el = row && row.parentElement;
            while (el && el !== document.body) {
                const st = getComputedStyle(el);
                if ((st.overflowY === 'auto' || st.overflowY === 'scroll')
                        && el.scrollHeight > el.clientHeight + 50) {
                    el.dataset.tbscan = '1';
                    return el.dataset.tbscan;
                }
                el = el.parentElement;
            }
            return '';
        }""")
        ada_kont = pg.evaluate(
            '() => !!document.querySelector(\'[data-tbscan="1"]\')')

        def _pas():
            try:
                kini = set(pg.evaluate(js_kumpul) or [])
            except Exception:
                # halaman sedang navigasi (bot/user menggerakkan) - anggap
                # pass diam, jangan biarkan exception bunuh pemindaian
                return False
            tumbuh = len(kini) > len(labels)
            labels.update(kini)   # |= akan me-rebind nama -> UnboundLocal
            return tumbuh

        # maks_pas 1: TIDAK scroll - cukup jendela awal (edclub memposisi-
        # kan list di garis depan akun). Dulu 50 pass menggulung seluruh
        # kursus terlihat user 20-30 dtk.
        mantap = 0
        for _ in range(max(1, maks_pas)):
            if not _pas():
                mantap += 1
                if mantap >= 2:
                    break
            else:
                mantap = 0

        no_re = re.compile(r"Lesson (\d+)")
        status = {}
        for lab in labels:
            m = no_re.search(lab)
            if not m:
                continue
            no = int(m.group(1))
            if "is locked" in lab:
                status[no] = "kunci"
            elif "completed" in lab or "stars earned" in lab:
                status[no] = "ok"
            else:
                status[no] = "baru"
        if not status:
            return None
        semua = sorted(status)
        baru = [n for n, st in status.items() if st == "baru"]
        # 'pertama_baru': level pertama yang belum disentuh. Baris SEBELUM
        # jendela termuat diasumsikan selesai (edclub buka pelajaran
        # berurutan) - kalau tidak ada yg 'baru' di jendela, ambil
        # sesudah baris tertinggi yg tidak terkunci.
        if baru:
            pertama = min(baru)
        else:
            bebas = [n for n, st in status.items() if st != "kunci"]
            pertama = (max(bebas) + 1) if bebas else max(semua)
        rows = {n: status[n] for n in semua}
        return {"total": max(semua), "pertama_baru": pertama,
                "jendela_awal": min(semua), "rows": rows}
    except Exception:
        import traceback as _tb
        _tb.print_exc()
        return None


def build_level_map():
    """Bangun peta level -> URL lengkap (1..685) dengan membuka daftar
    lesson lalu menklik tiap baris dan merekam URL .play-nya (~1.3 dtk/
    level, sekali per akun). Baris daftar terverifikasi: aria-label
    'Lesson N' sesuai urutan. Jalan di TAB UTAMA (redirect pulang-pergi;
    dulu tab terpisah - tab baru mengangkat jendela browser, keluhan
    live). Supervisor ikut menunggu di sini, jadi tidak ada yang lain
    menyentuh tab selama memetakan."""
    if state.browser is None:
        print("[PETA] belum terhubung ke browser.")
        return 0
    pg = state.PAGE
    state.PETA_BANGUN = True     # pengawas: jangan bounce rute lama
    asal = ""
    try:
        asal = browser._real_url(pg) or ""
    except Exception:
        asal = ""
    baru = 0
    try:
        _wait_daftar(pg)

        def _jumlah_baris():
            return pg.evaluate(
                "() => document.querySelectorAll"
                "('a[aria-label^=\"Lesson \"], div.box-container').length") or 0

        total = _jumlah_baris()
        if not total:
            print("[PETA] daftar lesson tidak terbaca.")
            return 0
        print("[PETA] membangun peta (scroll otomatis memuat semua "
              "bagian - jangan tutup bot)...")
        i = 0
        mentok = 0
        while i < total:
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
                lbl = pg.evaluate(r"""(i) => {
                  const baru = [...document.querySelectorAll(
                    'a[aria-label^="Lesson "]')];
                  const rows = baru.length ? baru
                    : [...document.querySelectorAll('div.box-container')];
                  return rows[i] ? (rows[i].getAttribute('aria-label') || '') : '';
                }""", i)
                m = re.match(r"Lesson\s+(\d+)", lbl or "")
                nomor = int(m.group(1)) if m else i + 1
                if str(nomor) in state._level_map:
                    i += 1
                    continue   # sudah terpetakan (resume cepat tanpa klik)
                pg.evaluate(_klik_baris_js(), i)
                url = None
                for fase in range(40):
                    time.sleep(0.1)
                    u = pg.evaluate("() => location.href")
                    try:
                        u2 = browser._lesson_play_url(u)
                    except Exception:
                        u2 = u
                    if u2 and ".play" in u2:
                        url = u2
                        break
                    if fase in (12, 28):
                        # lesson terkunci: modal 'jumping ahead' (UI baru:
                        # 'Skip anyways') - klik supaya navigasi tetap terjadi.
                        pg.evaluate(_KLIK_LANJUT_JS)
                if url and state._level_map.get(str(nomor)) != url:
                    _record_level_map(nomor, url)
                    baru += 1
                # go_back hanya kalau memang navigasi ke .play terjadi;
                # baris yang tidak bisa diklik (mis. bagian khusus akhir
                # daftar) tidak menavigasi -> go_back dari daftar justru
                # membawa tab ke about:blank dan builder nyangkut .
                if url:
                    pg.go_back(timeout=15000)
                    pg.wait_for_selector(
                        "a[aria-label^='Lesson '], div.box-container",
                        timeout=20000)
                if (i + 1) % 25 == 0:
                    print(f"[PETA] {i + 1}/{total} level terpetakan...")
                i += 1
                if i >= total:
                    # UI baru lazy-load per bagian: scroll bawah untuk
                    # memuat section berikutnya; dua kali tanpa baris baru
                    # = daftar habis.
                    pg.evaluate(
                        "() => window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(1.2)
                    total2 = _jumlah_baris()
                    if total2 > total:
                        total = total2
                        mentok = 0
                    else:
                        mentok += 1
                        if mentok >= 2:
                            break
            except Exception:
                pulih = False
                for _ in range(3):
                    try:
                        _wait_daftar(pg)
                        pulih = True
                        break
                    except Exception:
                        time.sleep(2)
                        try:   # tab bisa mati -> tab baru
                            pg.close()
                        except Exception:
                            pass
                        pg = browser._tab_latar(state.browser.contexts[0])
                if not pulih:
                    print("[PETA] daftar tidak bisa dibuka lagi - berhenti "
                          "(lanjutkan lain waktu, sudah terpetakan "
                          f"{len(state._level_map)}).")
                    break
        print(f"[PETA] selesai: +{baru} baru, total {len(state._level_map)} "
              f"level terpetakan (level_map.json).")
    finally:
        state.PETA_BANGUN = False
        if pg is not state.PAGE:
            state.PAGE = pg   # halaman lama mati -> tab pengganti jadi utama
        kembali = asal if ".play" in asal else ""
        if kembali:
            try:
                pg.goto(kembali, timeout=25000)
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
        _record_level_map(nomor, url)
    return lab


_KLIK_LANJUT_JS = """() => {
    const t = [...document.querySelectorAll('button, .btn, [role=button]')];
    const b = t.find(x => /continue|lanjut|skip anyway/i.test(x.textContent || '')
                        && x.offsetParent !== null);
    if (b) { b.click(); return true; }
    return false;
}"""

# Baris daftar lesson, DUA UI sekaligus (course TypingClub pindah ke SPA
# baru Nov 2026 - live: program-3.game REDIRECT ke /student/course/3 dan
# div.box-container = 0). UI baru: kartu <a aria-label="Lesson N: Judul.
# Lesson is locked/completed">; UI lama: div.box-container aria 'Lesson N'
# + class is_unlocked. Pemilih baris: terbuka pertama pada/awal, kalau
# tidak ada sama sekali -> baris TERKUNCI pertama (urut ketat, tidak
# pernah mundur; modal 'Skip anyways' edclub diklik pemanggil).
_DAFTAR_JS = r"""(arg) => {
  const parse = aria => { const m = (aria||'').match(/Lesson (\\d+)/);
    return m ? parseInt(m[1], 10) : 0; };
  const rows = [];
  const baru = [...document.querySelectorAll('a[aria-label^="Lesson "]')];
  if (baru.length) {
    for (const a of baru) {
      const aria = a.getAttribute('aria-label') || '';
      rows.push({no: parse(aria), locked: /is locked/i.test(aria)});
    }
  } else {
    for (const r of document.querySelectorAll('div.box-container')) {
      const aria = r.getAttribute('aria-label') || '';
      rows.push({no: parse(aria),
                 locked: !((r.className||'') + '').includes('is_unlocked')});
    }
  }
  let awal = arg.awal || 0;
  if (arg.cari > 0) {
    for (let i = 0; i < rows.length; i++) {
      if (rows[i].no === arg.cari) { awal = Math.max(awal, i + 1); break; }
    }
  }
  let terkunci = -1;
  for (let i = awal; i < rows.length; i++) {
    if (arg.cari > 0 && rows[i].no && rows[i].no < arg.cari) continue;
    if (!rows[i].locked) return i;
    if (terkunci < 0) terkunci = i;
  }
  return terkunci;   // -1 = tidak ada baris setelah posisi ini
}"""


def _klik_baris_js():
    """Klik baris daftar ke-i (UI baru = anchor, UI lama = lsn_name)."""
    return r"""(i) => {
  const baru = [...document.querySelectorAll('a[aria-label^="Lesson "]')];
  const rows = baru.length ? baru
    : [...document.querySelectorAll('div.box-container')];
  const r = rows[i];
  if (!r) return false;
  const klik = (!baru.length && r.querySelector('div.lsn_name')) || r;
  klik.click();
  return true;
}"""


def _wait_play_url(newpg):
    for i in range(20):
        time.sleep(0.5)
        if state.STOP:
            return None
        try:
            u = newpg.evaluate("() => location.href")
        except Exception:
            u = None
        # rute SPA baru /student/course/<c>/lesson/<id> dinormalisasi ke
        # .play (site pindah UI Nov 2026 - URL lama tetap hidup juga)
        try:
            u2 = browser._lesson_play_url(u)
        except Exception:
            u2 = u
        if u2 and ".play" in u2 and browser._is_edclub_url(u2):
            return u2
        if i in (3, 9):
            # baris terkunci: edclub menampilkan modal 'Are you sure? ...
            # jumping ahead' (UI baru tombolnya 'Skip anyways') - klik
            # supaya navigasi tetap terjadi. Akun baru: semua level
            # kecuali level 1 terkunci, dan level 1 bisa jadi rusak.
            try:
                newpg.evaluate(_KLIK_LANJUT_JS)
            except Exception:
                pass
    return None


def _goto_next_lesson_in_list(newpg, current_url):
    """Buka daftar pelajaran dan klik pelajaran berikutnya SESUAI URUTAN
    KURSUS. Nomor URL edclub tidak berurutan (setelah 189.play situs
    lanjut ke 2959.play) - jangan hitung N+1. Klik baris TERBUKA pertama
    TEPAT SETELAH posisi sekarang - urutan ketat, TANPA melompati baris
    yang sudah ada progres (dulu filter has_progress membuat satu skip
    melompat 16-17 level sekaligus: live 540 -> 556 -> 573 -> 589,
    keluhan user 'tidak urut'). Return URL .play, None jika gagal."""
    cur = _lesson_id(current_url)
    # Nomor level sekarang: scan daftar MULAI SETELAH baris level ini.
    # Dulu scan selalu dari baris 0 -> 'pelajaran terbuka pertama tanpa
    # progres' bisa level lama yang terlewat (live: user di 295, skip
    # malah mendarat di 106) - jangan pernah mundur ke belakang posisi.
    lvl_now = url_to_level(current_url) or 0
    if not lvl_now:
        try:
            lab = _level_label()
            lvl_now = int(lab[1:]) if lab[:1] == "L" and lab[1:].isdigit() else 0
        except Exception:
            lvl_now = 0
    row = 0
    for _ in range(3):
        if state.STOP:
            return None
        try:
            _wait_daftar(newpg)
        except Exception:
            continue
        try:
            idx = newpg.evaluate(_DAFTAR_JS, {"awal": row, "cari": lvl_now})
        except Exception:
            continue
        if idx is None or idx < 0:
            continue
        newpg.evaluate(_klik_baris_js(), idx)
        row = idx + 1
        url = _wait_play_url(newpg)
        if not url:
            continue
        # rute SPA baru kadang TIDAK mount lesson-nya (live: body 61
        # terus di /lesson/117) - paksa rute .play klasik yang sudah
        # terbukti buat mesin ketik.
        try:
            mentah = newpg.evaluate("() => location.href") or ""
        except Exception:
            mentah = ""
        if mentah and "/lesson/" in mentah and mentah != url:
            try:
                newpg.goto(url, timeout=25000)
            except Exception:
                pass
        lid = _lesson_id(url)
        if lid != cur and lid not in state._broken_lessons:
            return url
        # baris ini = level rusak itu sendiri / sudah ditandai rusak
        # -> ulangi dari baris setelahnya.
    return None


def _wait_spa_next_url(old_lid):
    """Setelah klik tombol Skip UI baru: tunggu URL pindah ke lesson
    lain (id beda). Return URL bentuk .play, None kalau tidak pindah."""
    for _ in range(12):
        time.sleep(0.7)
        if state.STOP:
            return None
        try:
            u = browser._real_url(state.PAGE)
        except Exception:
            continue
        if ".play" in u:
            nid = _lesson_id(u)
            if nid and nid != old_lid:
                return u
    return None


def _skip_to_next_lesson(alasan):
    """Level rusak/premium-beku: lanjut ke pelajaran berikutnya sesuai
    URUTAN DAFTAR (bukan N+1 URL). Utama: tombol 'Skip' footer lesson
    UI baru (daftar lama .game tak merender barisnya lagi sejak update
    Nov 2026); fallback: klik baris daftar seperti dulu."""
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
    # UI baru: klik 'Skip' milik edclub sendiri di tab yang sama -
    # urutan kurus terjaga, tanpa tab baru (user terganggu tab baru
    # terus-menerus).
    try:
        titik = jsutil.run_js(SPA_SKIP_JS, state.PAGE.main_frame)
    except Exception:
        titik = None
    if titik:
        try:
            state.PAGE.mouse.click(titik["x"], titik["y"])
        except Exception:
            titik = None
        if titik:
            url = _wait_spa_next_url(lid)
            if url:
                state._recovery_counts.pop(base, None)
                state._hijack_counts.pop(base, None)
                state.last_url = url
                state.last_action_time = time.time()
                state._last_recovery = time.time()
                print(f"[SKIP] {alasan} - lanjut ke {url.split('/')[-1]} "
                      "(tombol Skip UI baru)")
                return True
    # UI lama: klik baris pelajaran berikutnya di daftar
    url = None
    newpg = state.PAGE
    try:
        url = _goto_next_lesson_in_list(newpg, base)
    except Exception:
        url = None
    if url is None:
        try:
            newpg = browser._tab_latar(state.PAGE.context)
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
