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
from .jstemplates import (PROFILE_CHECK_JS, PROBE_FETCH_LOGIN_JS,
                          SESI_PATH_RE)




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
        # catat tab/jendela baru: iklan (window.open) di Chrome/Edge
        # membuka tab liar yang mengunci bot sampai recovery - sweeper
        # akan menutupnya begitu jelas bukan tab edclub
        try:
            state._adtab_watch.append([pg, time.time()])
        except Exception:
            pass

    for ctx in state.browser.contexts:
        try:
            ctx.on("page", on_page)
            for pg in ctx.pages:
                on_page(pg)
        except Exception:
            pass


def _sweep_ad_tabs():
    """Tutup tab/jendela IKLAN yang menyusup ke browser bot. Tab baru
    diberi ~2,5 detik sampai URL-nya jelas (tab gubris engine sendiri
    sebentar about:blank); yang bukan edclub ditutup. Dipanggil tiap
    iterasi main loop - dulu iklan mengunci bot sampai recovery
    lambat, sekarang tertutup dalam 1-2 detik."""
    if not state._adtab_watch:
        return
    sisa = []
    for item in state._adtab_watch:
        pg, lahir = item
        try:
            if pg.is_closed():
                continue
            url = (pg.url or "").lower()
            belum_jelas = (time.time() - lahir < 2.5 or not url
                           or url.startswith(("about:", "data:"))
                           or url.startswith(("chrome://", "edge://",
                                              "brave://")))
            if belum_jelas:
                if time.time() - lahir < 30:
                    sisa.append(item)
                continue
            if pg is state.PAGE:
                continue
            if not any(h in url for h in ("edclub.com", "typingclub.com")):
                pg.close()
                print(f"[TAB] tab iklan/liar ditutup otomatis: {url[:70]}")
        except Exception:
            pass
    state._adtab_watch[:] = sisa


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


def _probe_redirect_login(timeout_s=14.0):
    """Cek status login PERTAMA lewat TAB AKTIF saja - tanpa membuka tab
    baru (dulu: 'tab cadangan' muncul-sekejap tiap start, terlihat seperti
    bot membuat tab liar). Baca penanda di halaman sekarang; kalau tidak
    kunjung ada (lesson .play tidak punya navbar), REDIRECT sementara ke
    dashboard seperti user mengetik alamat, baca, lalu kembali ke URL
    semula. Hanya dipanggil gerbang start (sebelum bot mulai mengetik).
    Return 'in'/'out'/None."""
    if not _page_alive(state.PAGE):
        return None
    try:
        asal = state.PAGE.url or ""
    except Exception:
        return None
    mulai = time.time()
    batas = mulai + timeout_s
    hasil = None
    out_hitung = 0
    pindah = False
    while time.time() < batas:
        try:
            r = state.PAGE.evaluate("() => {" + PROFILE_CHECK_JS + "}")
        except Exception:
            r = None
        if r == "in":
            hasil = "in"
            break
        if r == "out":
            out_hitung += 1     # 'out' harus stabil 2x (hydration race)
            if out_hitung >= 2:
                hasil = "out"
                break
        else:
            out_hitung = 0
        try:
            low = (state.PAGE.url or "").lower()
            if any(k in low for k in ("signin", "login", "signup")):
                hasil = "out"
                break
        except Exception:
            pass
        if (not pindah and not hasil
                and not getattr(state, "BROWSER_WV2", False)
                and time.time() - mulai > 3.5):
            # redirect pulang-pergi = navigasi yang terlihat user; di mode
            # embedded itu terjadi DI DALAM app (kilatan putih saat start)
            # - dilarang. Penanda di halaman terlihat memang kebenaran.
            print("[LOGIN] penanda login tak ada di halaman ini - "
                  "pinjam tab sebentar ke dashboard...")
            try:
                state.PAGE.goto("https://www.edclub.com/sportal/",
                                timeout=20000)
                pindah = True
            except Exception:
                break
        time.sleep(0.8)
    if pindah:
        try:
            state.PAGE.goto(asal, timeout=20000)
        except Exception:
            pass
    return hasil


def _probe_fetch_login(timeout_s=9.0):
    """Cek sesi lewat fetch same-origin dari tab aktif: NOL tab baru dan
    NOL navigasi - tab yang dipakai user (form login, lesson) tidak
    disentuh sama sekali. Dulu tab cadangan dibuat-buat tiap 60 dtk
    selagi menunggu login -> Chromium mengangkat jendela & user melihat
    tab liar muncul-hilang. Return 'in'/'out'/'' (belum jelas)/None (tab
    tidak bisa dievaluasi -> caller boleh fallback tab cadangan)."""
    try:
        state.PAGE.wait_for_load_state(timeout=4000)
    except Exception:
        pass
    batas = time.time() + timeout_s
    while time.time() < batas:
        try:
            r = state.PAGE.evaluate(PROBE_FETCH_LOGIN_JS)
        except Exception:
            return None
        if r in ("in", "out"):
            return r
        time.sleep(2.0)
    return ""


def _probe_tab_login(timeout_s=15.0):
    """Buka tab CADANGAN ke dashboard edclub, baca penanda login di sana,
    lalu tutup. Status sesi berlaku untuk AKUN secara keseluruhan (token
    disimpan browser, bukan per-halaman) - jadi penanda di dashboard
    menjawab status untuk halaman apapun yang sedang aktif (mis. lesson
    .play yang navbarnya tidak pernah tampil).

    v3.2: mode WebView2 TIDAK BOLEH pakai tab cadangan - _tab_latar
    mengembalikan HALAMAN UTAMA yang sedang dilihat user, goto sportal
    = halaman app jadi PUTIH & pengguna tidak bisa klik apa-apa (keluhan
    live). Halaman yang terlihat MEMANG kebenaran di mode embedded:
    user login di situ, dashboard-nya mengandung penanda -> pemulihan
    jalan via _login_profile() biasa. Return None = tunggu poll berikut."""
    if getattr(state, "BROWSER_WV2", False):
        return None

    # HYDRATION RACE (bug live 08:33): dashboard yang baru dimuat merender
    # navbar versi LOGOUT dulu ('Login' link), lalu setelah cek sesi (~1-3
    # dtk) diganti nama user. Dulu poll pertama langsung percaya 'out' ->
    # popup 'belum login' padahal user sudah login. Sekarang 'out' harus
    # STABIL 2 poll berurutan; 'in' (nama user muncul) selalu pasti ->
    # langsung. Redirect URL ke /signin = keputusan server, pasti logout.
    #
    # Timeout 15 dtk: browser dingin + Cloudflare + iklan bisa >10 dtk
    # (dulu None -> patroli menunggu throttle 30-60 dtk berikutnya = cek
    # login pertama terasa lama). Return 'in'/'out'/None.
    try:
        tab = browser._tab_latar(state.PAGE.context)
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


def _sesi_punya_identitas():
    """True kalau file sesi_edclub.json berisi cookie identitas (bukan
    cuma cookie tracking) = sesi tersimpan layak dipercaya 'in'.
    JANGAN import gui.theme di sini (engine tak punya theme - dulu
    ImportError diam-diam mematikan seed ini, log live 2995 21:27)."""
    try:
        if getattr(sys, "frozen", False):
            base = os.path.join(
                os.environ.get("LOCALAPPDATA", ""), "TypingBot")
        else:
            base = os.path.dirname(
                os.path.dirname(os.path.abspath(__file__)))
        pth = os.path.join(base, "sesi_edclub.json")
        with open(pth, encoding="utf-8") as f:
            kuki = (json.load(f).get("cookies") or [])
        nama = {c.get("name") for c in kuki}
        return bool(nama & {"pw_uuid", "connectId", "tb_lt", "_cc_id",
                            "_lc2_fpi", "_pubcid", "_sharedid"})
    except Exception:
        return False


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
    # Halaman area student HANYA terjangkau saat login (anon langsung
    # di-redirect server ke /signin) = bukti positif tanpa penanda DOM.
    if (profil is None and not di_login
            and re.search(r"/(student|sportal)/", low)):
        profil = "in"
    # Sesi tersimpan ber-cookie identitas = bukti kuat 'in' ( popover
    # akun menampilkannya aktif): buka gerbang tanpa menunggu 40 dtk
    # apapun URL-nya - halaman game canvas kadang tanpa penanda dan
    # URL-nya berubah-ubah saat SPA mount.
    if (profil is None and not di_login
            and ("edclub" in low or "typingclub" in low)
            and not state._login_sentinel["pernah_in"]
            and not state._login_seed_cek):
        state._login_seed_cek = True
        if _sesi_punya_identitas():
            state._login_sentinel["pernah_in"] = True
            profil = "in"
            print("[LOGIN] sesi tersimpan ber-cookie identitas - "
                  "gerbang login langsung terbuka.")
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
        if state.NEEDS_LOGIN:
            # sesi mati saat bot sedang berjalan: jangan ganggu tab yang
            # sedang dipakai user - fetch same-origin dulu (nol tab baru);
            # tab cadangan cuma kalau fetch tak bisa menyimpulkan
            profil = _probe_fetch_login()
            if profil not in ("in", "out"):
                print("[LOGIN] Halaman ini tanpa penanda login - cek sesi lewat "
                      "tab cadangan...")
                profil = _probe_tab_login()
        else:
            # gerbang start: cek lewat TAB AKTIF (redirect dashboard
            # pulang-pergi) - nol tab baru; kasus paling sering sekaligus
            # yang paling terlihat user (dulu: tab kedua muncul-sekejap)
            profil = _probe_redirect_login()
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
    elif not mati and not state.NEEDS_LOGIN:
        # profil masih None walau DOM + tab cadangan gagal (halaman mati /
        # Cloudflare menggantung / renderer sibuk). Kumpulkan durasi;
        # >40 dtk di halaman edclub -> perlakukan seperti logout.
        # (live bug: di TAMPILAN LAMA penanda tidak ada sama sekali dan
        # pernah_in memblokir cabang ini -> 'Memeriksa login' macet
        # selamanya. Sekarang pernah_in justru MEMBUKA gerbang.)
        if (("edclub" in low or "typingclub" in low) and not di_login):
            if not state._login_sentinel["unknown_mulai"]:
                state._login_sentinel["unknown_mulai"] = now
                print(f"[LOGIN] Status login belum terbaca "
                      f"(url={low[:72]}) - menunggu...")
            elif now - state._login_sentinel["unknown_mulai"] > 12.0:
                # 40 dtk dulu; 12 dtk cukup: kalau sesi tersimpan ada,
                # gerbang seed di atas sudah membuka jauh lebih cepat -
                # sisa kasus = halaman tanpa penanda yang lama mount.
                if state._login_sentinel["pernah_in"]:
                    # sesi terbukti 'in' di sesi ini (penanda pernah
                    # terbaca) - halaman ini cuma tidak menyediakan
                    # penanda (tampilan lama). Buka gerbang; kalau sesi
                    # ternyata mati, patroli berikutnya menangkap 'out'.
                    state.LOGIN_DICEK = True
                    state._login_sentinel["unknown_mulai"] = 0.0
                    print("[LOGIN] halaman ini tak punya penanda "
                          "(tampilan lama?) - percaya sesi 'in' yang "
                          "sudah terverifikasi.")
                else:
                    state._login_sentinel["ok"] = False
                    state._login_sentinel["alasan"] = (
                        "login tidak terdeteksi >12 dtk")
                    mati = True
        else:
            state._login_sentinel["unknown_mulai"] = 0.0
    # GUI hanya boleh menanya rentang kalau status login pasti (in/out/mati)
    if mati or profil in ("in", "out"):
        state.LOGIN_DICEK = True
    if mati and not state.NEEDS_LOGIN:
        state.NEEDS_LOGIN = True
        # JANGAN angkat jendela browser di sini: popup login saja dulu.
        # Browser baru diangkat SETELAH user menekan "Buka Halaman Login"
        # (ASK_LOGIN_NAV di bawah) - keluhan live: Chrome melompat ke depan
        # begitu popup muncul, padahal user belum memilih apa pun.
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
            # login' - jangan biarkan popup bot yang tetap memegang fokus.
            # bring_to_front CDP sering tidak menaikkan jendela OS -> minta
            # GUI (yang baru saja menerima klik = punya izin fokus) lewat
            # flag; GUI mengangkat SETELAH halaman termuat, bukan blank
            try:
                state.PAGE.bring_to_front()
            except Exception:
                pass
            state.FOCUS_BROWSER_AT = time.time()
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
    halaman. True = hidup.

    v3.3: timeout domcontentloaded BUKAN bukti renderer mati - rantai
    redirect OAuth Google bisa >3 dtk tanpa dokumen selesai (live:
    recovery men-taskkill WebView2 di tengah user login -> layar
    abu-abu). Kalau wait gagal, probe murah dgn timeout pendek: renderer
    suspend tidak menjawab sama sekali, renderer sibuk navigasi
    biasanya tetap punya context."""
    try:
        pg.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        return True
    except Exception:
        pass
    try:
        pg.evaluate("1", timeout=2500)
        return True
    except Exception:
        return False


def _recover_renderer():
    """Renderer tab aktif mati/suspend. Satu-satunya obat:
    restart browser debug (taskkill + relaunch, tanpa curi fokus), lalu
    sambung ulang. Dipanggil dari main loop (thread pemilik Playwright).
    Return True = tersambung ulang & boleh lanjut.

    v3.3: mode embedded DILARANG KERAS di sini - pemegang port 9222
    adalah WebView2 MILIK APP (layar di dalam app). taskkill = layar
    abu-abu/hitam & engine nyambung ke browser eksternal liar (live:
    user login Google -> layar mati -> Start nyasar ke Edge tanpa
    sesi). Di mode embedded: biarkan, user tinggal Stop lalu Start
    (webview tidak pernah dibunuh)."""
    if getattr(state, "BROWSER_WV2", False):
        print("[PEMULIHAN] mode embedded - WebView2 tidak boleh dibunuh. "
              "Tekan Stop lalu Start untuk mulai ulang sesi.")
        return False
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
