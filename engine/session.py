"""Deteksi & patroli sesi login edclub."""

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
from .config import (LOGIN_URL_INDIVIDUAL)
from .jstemplates import (PROFILE_CHECK_JS, SESI_PATH_RE)




def _install_login_sentinel():
    """Pasang listener response XHR/fetch edclub -> tangkap 401/403.
    Dipasang ke semua context (tab baru ikut terpasang lewat event page)."""
    if state.browser is None:
        return

    def on_response(resp):
        try:
            if resp.status not in (401, 403):
                return
            req = resp.request
            if req.resource_type not in ("xhr", "fetch"):
                return
            host = (urlparse(resp.url).hostname or "").lower()
            if not (host.endswith("edclub.com") or host.endswith("typingclub.com")):
                return
            if resp.status == 401:
                now = time.time()
                path = urlparse(resp.url).path or "/"
                state._login_sentinel["terakhir401"] = now
                state._login_sentinel["path401"][path] = now
                for p in list(state._login_sentinel["path401"]):
                    if now - state._login_sentinel["path401"][p] > 120:
                        del state._login_sentinel["path401"][p]
                if now - state._login_sentinel["log401"] > 30:
                    state._login_sentinel["log401"] = now
                    print(f"[LOGIN] catatan: API balas 401 ({path[:60]})")
                # 401 tunggal dari endpoint acak bukan tanda sesi mati
                # (akun gratis: endpoint premium memang 401). Percayai
                # hanya endpoint sesi, atau beberapa endpoint berbeda.
                if (SESI_PATH_RE.search(path)
                        or len(state._login_sentinel["path401"]) >= 3):
                    state._login_sentinel["ok"] = False
                    state._login_sentinel["alasan"] = f"API edclub 401 ({path[:40]})"
            else:
                # 403 sesekali bisa hal lain (konten premium) -> butuh 2x
                # dalam 60 detik baru dianggap sesi mati
                now = time.time()
                if now - state._login_sentinel["gagal403"] < 60:
                    state._login_sentinel["ok"] = False
                    state._login_sentinel["alasan"] = "API edclub berulang 403"
                state._login_sentinel["gagal403"] = now
        except Exception:
            pass

    def on_page(pg):
        try:
            pg.on("response", on_response)
        except Exception:
            pass

    for ctx in state.browser.contexts:
        try:
            ctx.on("page", on_page)
            for pg in ctx.pages:
                on_page(pg)
        except Exception:
            pass


def _login_profile():
    """'in'/'out'/None dari elemen .profile-name halaman aktif. INI sinyal
 utama edclub Individual: sesi TIDAK disimpan di cookie sama sekali
 (live: user login betulan, cookie cuma tracker/cloudflare) - deteksi
 cookie mustahil. Elemen profil tampil begitu sesi hidup -> pemulihan
 popup instan setelah user login."""
    try:
        return jsutil.run_js(PROFILE_CHECK_JS, state.PAGE.main_frame)
    except Exception:
        return None


def _fetch_login():
    """Deprecated: fetch /api/v1.1/student/me/ TIDAK bisa dipakai - live
    halaman edclub sendiri mengirimnya tanpa token (401 selalu,
    bahkan saat login; API user sebenarnya memakai header Authorization:
    Token dari storage internal). Diganti _probe_tab_login()."""
    return None


def _probe_tab_login(timeout_s=15.0):
    """Buka tab CADANGAN ke dashboard edclub, baca penanda login di sana,
    lalu tutup. Status sesi berlaku untuk AKUN secara keseluruhan (token
    disimpan browser, bukan per-halaman) - jadi penanda di dashboard
    menjawab status untuk halaman apapun yang sedang aktif (mis. lesson
    .play yang navbarnya tidak pernah tampil).

    HYDRATION RACE (bug live 08:33): dashboard yang baru dimuat merender
    navbar versi LOGOUT dulu ('Login' link), lalu setelah cek sesi (~1-3
    dtk) diganti nama user. Dulu poll pertama langsung percaya 'out' ->
    popup 'belum login' padahal user sudah login. Sekarang 'out' harus
    STABIL 2 poll berurutan; 'in' (nama user muncul) selalu pasti ->
    langsung. Redirect URL ke /signin = keputusan server, pasti logout.

    Timeout 15 dtk: browser dingin + Cloudflare + iklan bisa >10 dtk
    (dulu None -> patroli menunggu throttle 30-60 dtk berikutnya = cek
    login pertama terasa lama). Return 'in'/'out'/None."""
    try:
        tab = state.PAGE.context.new_page()
    except Exception:
        return None
    hasil = None
    out_hitung = 0
    try:
        try:
            tab.goto("https://www.edclub.com/sportal/", timeout=20000)
        except Exception:
            pass
        batas = time.time() + timeout_s
        while time.time() < batas and hasil is None:
            try:
                r = tab.evaluate("() => {" + PROFILE_CHECK_JS + "}")
            except Exception:
                r = None
            if r == "in":
                hasil = "in"
                break
            if r == "out":
                out_hitung += 1
                if out_hitung >= 2:
                    hasil = "out"
                    break
                time.sleep(1.5)
                continue
            out_hitung = 0
            try:
                lowtab = (tab.url or "").lower()
            except Exception:
                lowtab = ""
            if any(k in lowtab for k in ("signin", "login", "signup")):
                hasil = "out"
                break
            time.sleep(0.7)
    finally:
        try:
            tab.close()
        except Exception:
            pass
    return hasil


def _login_patrol(url):
    """Cek berkala dari main loop: set/bersihkan NEEDS_LOGIN. Interval 8 dtk
    biasa, 3 dtk saat sedang menunggu user login (popup harus tertutup
    cepat begitu user selesai login, bukan 8 dtk kemudian)."""
    now = time.time()
    jeda = 3.0 if state.NEEDS_LOGIN else 8.0
    if now - state._login_ck["terakhir"] < jeda:
        return
    state._login_ck["terakhir"] = now
    profil = _login_profile()
    low = (url or "").lower()
    di_login = any(k in low for k in ("login", "signin", "sign-in", "signup"))
    # DOM halaman aktif tidak punya penanda (lesson .play, SPA kosong,
    # navbar belum selesai render, Cloudflare) -> cek lewat tab cadangan
    # ke dashboard (status sesi berlaku akun-wide). Throttle 30 dtk;
    # hanya saat jawaban benar-benar dibutuhkan (gerbang belum terbuka
    # atau sedang menunggu login).
    if (profil is None and not di_login
            and ("edclub" in low or "typingclub" in low)
            and (state.NEEDS_LOGIN or not state.LOGIN_DICEK)
            and now - state._probe_tab_ck["terakhir"]
                > (60.0 if state.NEEDS_LOGIN else 30.0)):
        state._probe_tab_ck["terakhir"] = now
        print("[LOGIN] Halaman ini tanpa penanda login - cek sesi lewat "
              "tab cadangan...")
        profil = _probe_tab_login()
    # pemulihan instan: profil bernama = pasti login (menimpa sentinel)
    if profil == "in":
        state._login_sentinel["pernah_in"] = True
        if not state._login_sentinel["ok"] or state.NEEDS_LOGIN:
            state._login_sentinel["ok"] = True
            state._login_sentinel["alasan"] = ""
            state._login_sentinel["path401"].clear()
    mati = (di_login or not state._login_sentinel["ok"]
            or profil == "out") and profil != "in"
    if profil is not None:
        state._login_sentinel["unknown_mulai"] = 0.0
    elif not mati and not state.NEEDS_LOGIN and not state._login_sentinel["pernah_in"]:
        # profil masih None walau DOM + tab cadangan gagal (halaman mati /
        # Cloudflare menggantung / renderer sibuk). Kumpulkan durasi;
        # >40 dtk di halaman edclub -> perlakukan seperti logout.
        if (("edclub" in low or "typingclub" in low) and not di_login):
            if not state._login_sentinel["unknown_mulai"]:
                state._login_sentinel["unknown_mulai"] = now
                print("[LOGIN] Status login belum terbaca (halaman masih "
                      "memuat/diverifikasi) - menunggu...")
            elif now - state._login_sentinel["unknown_mulai"] > 40.0:
                state._login_sentinel["ok"] = False
                state._login_sentinel["alasan"] = "login tidak terdeteksi >40 dtk"
                mati = True
        else:
            state._login_sentinel["unknown_mulai"] = 0.0
    # GUI hanya boleh menanya rentang kalau status login pasti (in/out/mati)
    if mati or profil in ("in", "out"):
        state.LOGIN_DICEK = True
    if mati and not state.NEEDS_LOGIN:
        state.NEEDS_LOGIN = True
        print("[LOGIN] Sesi edclub tidak aktif"
              + (f" ({state._login_sentinel['alasan']})" if state._login_sentinel["alasan"] else "")
              + ". Login di jendela browser bot - bot menunggu di sini.")
    elif state.NEEDS_LOGIN and profil == "in":
        # Pulih hanya dengan bukti positif login (profil 'in'). Kalau profil
        # None (halaman tanpa penanda + tab cadangan tertahan throttle)
        # dianggap 'pulih' -> NEEDS_LOGIN=False -> popup login tertutup &
        # bot jalan mengetik padahal user logout .
        state.NEEDS_LOGIN = False
        state._login_sentinel["ok"] = True
        state._login_sentinel["alasan"] = ""
        print("[LOGIN] Sesi edclub aktif kembali - lanjut.")
    if state.NEEDS_LOGIN and state.ASK_LOGIN_NAV:
        state.ASK_LOGIN_NAV = False
        # URL login yang benar (live: /login = 404). Individu = /signin
        # ("Login Individual Edition"); akun sekolah = portal sportal.
        tujuan = state.ASK_LOGIN_URL or LOGIN_URL_INDIVIDUAL
        try:
            state.PAGE.goto(tujuan, timeout=25000)
            # fokus ke jendela browser: user baru memilih 'buka halaman
            # login' - jangan biarkan popup bot yang tetap memegang fokus
            try:
                state.PAGE.bring_to_front()
            except Exception:
                pass
            print(f"[LOGIN] Halaman login dibuka: {tujuan}")
        except Exception as e:
            print(f"[LOGIN] Gagal membuka halaman login: {str(e)[:60]}")


def _sweep_stripe_tabs(force=False):
    """Tutup TAB Stripe liar kapan pun mereka muncul. Dulu pembersihan
    hanya jalan saat TAB UTAMA kabur ke Stripe - padahal modal premium
    (iframe checkout) juga bisa membuka/men-navigasi tab LAIN diam-diam,
    sehingga sesi berikutnya selalu dibuka dengan sisa 'Stripe'."""
    now = time.time()
    if not force and now - state._stripe_sweep_last < 5.0:
        return
    state._stripe_sweep_last = now
    try:
        for c in state.browser.contexts:
            for pg in list(c.pages):
                if pg is state.PAGE:
                    continue
                try:
                    h = (urlparse(browser._real_url(pg)).hostname or "").lower()
                except Exception:
                    continue
                if "stripe" in h:
                    pg.close()
                    print("[TAB] tab Stripe liar ditutup")
    except Exception:
        pass


def _page_alive(pg, timeout_ms=3000):
    """Renderer halaman masih merespons? evaluate() di renderer yang
    di-suspend Windows (browser idle di latar) MENGHANG TANPA TIMEOUT -
    pernah membuat main loop mati diam total (live). wait_for_load_state
    MENERIMA timeout -> panggilan pembuka yang aman sebelum menyentuh
    halaman. True = hidup."""
    try:
        pg.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        return True
    except Exception:
        return False


def _recover_renderer():
    """Renderer tab aktif mati/suspend. Satu-satunya obat:
    restart browser debug (taskkill + relaunch, tanpa curi fokus), lalu
    sambung ulang. Dipanggil dari main loop (thread pemilik Playwright).
    Return True = tersambung ulang & boleh lanjut."""
    print("[PEMULIHAN] Halaman tidak merespons (renderer menggantung) - "
          "memulai ulang browser debug...")
    state.PAGE = None
    try:
        browser.disconnect()
    except Exception:
        pass
    if not browser._restart_browser_debug():
        print("[PEMULIHAN] Browser tidak bisa direstart.")
        return False
    try:
        browser.connect()
        return state.PAGE is not None
    except SystemExit:
        return False
