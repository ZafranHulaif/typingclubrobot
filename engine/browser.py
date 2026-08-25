"""Port debug, deteksi pemegang port, luncur browser, sambungkan CDP, kelola tab."""

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
from . import profiles
from . import session
from .config import (BROWSER_CANDIDATES, OCR_AVAILABLE)
from .jstemplates import (PLAYABLE_CHECK_JS)




def _alamat_debug():
    return f"127.0.0.1:{state.DEBUG_PORT}"

# ---------------------------------------------------------------------------
# Koneksi: cek port, bersihkan dari Edge, buka Brave otomatis, sambungkan
# ---------------------------------------------------------------------------


def _is_edclub_url(url):
    """Cek hostname ASLI (bukan substring!): URL Stripe yang di dalam
    parameternya menyebut 'edclub.com' pernah menipu cek substring dan
    bikin bot nyangkut di halaman checkout mati."""
    try:
        h = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return h.endswith("edclub.com") or h.endswith("typingclub.com")


def _real_url(pg):
    """URL asli halaman via evaluate. page.url Playwright bisa stale
    (isi sudah m.stripe.network tapi masih melaporkan edclub);
    location.href tidak pernah bohong."""
    try:
        u = pg.evaluate("() => location.href")
        if u and isinstance(u, str):
            return u
    except Exception:
        pass
    try:
        return pg.url
    except Exception:
        return ""


def _frame_edclub(fr):
    """Frame ini milik edclub? Frame Stripe checkout (iframe premium)
    TIDAK BOLEH dijalankan klik apa pun - klik di dalamnya pernah
    membawa tab ke checkout Stripe."""
    try:
        if fr == state.PAGE.main_frame:
            return _is_edclub_url(_real_url(state.PAGE))
    except Exception:
        pass
    try:
        u = fr.url
    except Exception:
        return False
    if not u or u.startswith("about:"):
        return True
    h = (urlparse(u).hostname or "").lower()
    return h.endswith("edclub.com") or h.endswith("typingclub.com")


def _cek_debug_port():
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://{_alamat_debug()}/json/version", timeout=2) as r:
            return json.loads(r.read().decode()).get("Browser", "")
    except Exception:
        return ""


def set_confirmer(fn):
    """Pasang callback konfirmasi: fn(nama, pid) -> bool (boleh ditutup?)."""
    state._confirmer = fn


def _exe_info_pid(pid):
    """(path_exe, pid_induk) dari sebuah PID. PowerShell CIM dulu (wmic
    sudah dihapus di Windows 11 baru), fallback wmic. Return ('', 0) kalau
    tidak terbaca."""
    try:
        out = _run_hidden(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}')."
             "ExecutablePath"],
            capture_output=True, text=True, timeout=12).stdout.strip()
        if out and "\n" not in out:
            exe = out
        else:
            exe = ""
    except Exception:
        exe = ""
    induk = 0
    try:
        out2 = _run_hidden(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}')."
             "ParentProcessId"],
            capture_output=True, text=True, timeout=12).stdout.strip()
        if out2.isdigit():
            induk = int(out2)
    except Exception:
        induk = 0
    if not exe:
        try:
            out3 = _run_hidden(
                ["wmic", "process", "where", f"processid={pid}",
                 "get", "ExecutablePath", "/value"],
                capture_output=True, text=True, timeout=12).stdout
            for ln in out3.splitlines():
                if ln.lower().startswith("executablepath="):
                    exe = ln.split("=", 1)[1].strip()
                    break
        except Exception:
            pass
    return exe, induk


def _identitas_pemegang(pid, nama):
    """Identitas APLIKASI sebenarnya di balik proses pemegang port.
    Kasus nyata: port dipegang msedgewebview2.exe = WebView2 yang ditanam
    aplikasi lain (mis. Adobe), dulu salah terdeteksi sebagai 'Edge' lalu
    ditutup paksa tanpa bertanya. Return dict:
    nama (untuk dialog), exe (untuk ikon), proses (nama proses asli)."""
    exe, induk = _exe_info_pid(pid)
    base = os.path.basename(exe) if exe else nama
    tampil = os.path.splitext(base)[0]
    webview = "webview" in nama.lower() or "webview" in base.lower()
    if webview and induk:
        # cari nama aplikasi induknya (pemilik WebView) - ditampilkan apa
        # adanya tanpa embel2 teknis: user cukup tahu 'Acrobat' jalan.
        pexe, _pinduk = _exe_info_pid(induk)
        if pexe:
            pbase = os.path.basename(pexe)
            tampil = os.path.splitext(pbase)[0]
            exe = pexe
        else:
            tampil = tampil + "  (WebView)"
    return {"nama": tampil, "pid": pid, "exe": exe, "proses": nama}


def _tanya_tutup(nama, pid, exe=""):
    if state._confirmer is not None:
        try:
            return bool(state._confirmer(nama, pid, exe))
        except Exception:
            return False
    try:
        r = input(f"  Port 9222 dipakai oleh {nama} (PID {pid}). Tutup paksa? [y/N] ")
        return r.strip().lower().startswith("y")
    except Exception:
        return False


def _run_hidden(cmd, **kw):
    """subprocess.run tanpa jendela console. Wajib untuk semua panggilan
    netstat/tasklist/taskkill dari app berjendela (PyInstaller --windowed):
    tanpa flag ini Windows membuka jendela console hitam sesaat untuk tiap
    panggilan (user melihat 'aplikasi flash' beberapa kali saat connect)."""
    kw.setdefault("creationflags", 0x08000000)   # CREATE_NO_WINDOW
    return subprocess.run(cmd, **kw)


def _bebaskan_port(tanya_semua=True):
    """Port 9222 dipakai proses lain -> identifikasi PEMEGANG ASLINYA
    (bisa bukan browser sama sekali; WebView2 milik Adobe dsb. dinaiki
    ke aplikasi induknya), lalu SELALU minta izin user sebelum taskkill.
    (dulu proses 'edge' ditutup paksa diam-diam, pernah menutup
    WebView milik aplikasi lain.)
    Parameter tanya_semua dipertahankan untuk kompatibilitas pemanggil;
    sekarang semua pemegang selalu ditanyakan."""
    pemegang = _siapa_pegang_port()
    if not pemegang:
        return False
    for pid, nama in pemegang:
        info = _identitas_pemegang(pid, nama)
        print(f"  -> port 9222 dipakai {info['nama']} "
              f"({nama}, PID {pid})")
        if not _tanya_tutup(info["nama"], pid, info["exe"]):
            print(f"     tidak jadi ditutup - port tetap dipakai {info['nama']}.")
            continue
        print("     menutup paksa atas izin user...")
        try:
            _run_hidden(["taskkill", "/F", "/T", "/PID", str(pid)],
                        capture_output=True, timeout=8)
        except Exception:
            pass
    time.sleep(2)
    return True


def _siapa_pegang_port():
    pids = []
    try:
        out = _run_hidden(["netstat", "-ano", "-p", "TCP"],
                          capture_output=True, text=True, timeout=8).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[1].endswith(f":{state.DEBUG_PORT}") and parts[4].isdigit():
                pids.append(int(parts[4]))
    except Exception:
        pass
    hasil = []
    for pid in set(pids):
        try:
            t = _run_hidden(["tasklist", "/FI", f"PID eq {pid}"],
                            capture_output=True, text=True, timeout=5).stdout
            for ln in t.splitlines():
                if ".exe" in ln.lower() and str(pid) in ln:
                    hasil.append((pid, ln.split()[0]))
                    break
        except Exception:
            pass
    return hasil


def _adalah_browser_kita(nama_pemegang):
    """Apakah pemegang port salah satu browser yang dikelola bot
    (brave/chrome/msedge)? Bukan -> aplikasi asing (widget sistem
    bawaan laptop, WebView2 milik aplikasi lain, dll.) -> jangan
    pernah dipaksa ditutup."""
    return any(c["proc"] in nama_pemegang for c in BROWSER_CANDIDATES)


def _port_bind_kosong(port):
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
            return True
    except OSError:
        return False


def _sesuaikan_port():
    """Dipanggil di awal siapkan_browser. Port 9222 dipegang aplikasi
    ASING (bukan brave/chrome/msedge)? Bot pindah ke port kosong
    berikutnya dan MEMBIARKAN aplikasi itu tetap jalan - tanpa dialog
    'tutup aplikasi' yang menakutkan. Kasus nyata: Batterywidgethost
    bawaan laptop pegang 9222, bot malah minta ditutup padahal cukup
    pindah port."""
    pemegang = _siapa_pegang_port()
    if not pemegang:
        return state.DEBUG_PORT
    nama = " ".join(n.lower() for _, n in pemegang)
    if _adalah_browser_kita(nama):
        return state.DEBUG_PORT
    for kandidat in range(9223, 9323):
        if _port_bind_kosong(kandidat):
            try:
                info = _identitas_pemegang(pemegang[0][0], pemegang[0][1])
                nm = info["nama"]
            except Exception:
                nm = pemegang[0][1]
            print(f"[PORT] 9222 sedang dipakai {nm} - bot memakai jalur "
                  f"lain ({kandidat}); {nm} dibiarkan tetap jalan.")
            state.DEBUG_PORT = kandidat
            return state.DEBUG_PORT
    return state.DEBUG_PORT


def _find_browser():
    """Cari browser Chromium terpasang. Return dict kandidat + 'exe',
    atau None. Prioritas: pilihan user (FORCE_BROWSER) -> env
    TYPINGBOT_BROWSER -> deteksi otomatis (Brave -> Chrome -> Edge)."""
    for pick in (state.FORCE_BROWSER, os.environ.get("TYPINGBOT_BROWSER", "")):
        pick = (pick or "").strip()
        if pick:
            base = os.path.basename(pick).lower()
            cocok = next((c for c in BROWSER_CANDIDATES
                          if base.startswith(c["proc"].replace(".exe", ""))), None)
            if cocok:
                # nama kanonik ("Brave") - pemanggil membandingkan dengan
                # nama itu untuk memutuskan profil default vs khusus
                return {"name": cocok["name"], "exe": pick,
                        "proc": cocok["proc"]}
            if os.path.isfile(pick):
                return {"name": os.path.basename(pick), "exe": pick,
                        "proc": "brave.exe"}
            print(f"Browser pilihan ({pick}) tidak ditemukan, pakai deteksi otomatis.")
    # Preferensi Otomatis: browser yang terakhir dipakai (live tersimpan
    # GUI) - jadi Otomatis = 'browser edclub kemarin', bukan selalu Brave.
    last = (state.LAST_BROWSER or "").strip()
    if last:
        base = os.path.basename(last).lower()
        cocok = next((c for c in BROWSER_CANDIDATES
                      if base.startswith(c["proc"].replace(".exe", ""))), None)
        if cocok:
            return {"name": cocok["name"], "exe": last, "proc": cocok["proc"]}
    for c in BROWSER_CANDIDATES:
        for p in c["paths"]:
            if p and os.path.isfile(p):
                return {"name": c["name"], "exe": p, "proc": c["proc"]}
    return None


def _browser_sudah_jalan():
    proc = (state.BROWSER or {}).get("proc", "brave.exe")
    try:
        out = _run_hidden(["tasklist", "/FI", f"IMAGENAME eq {proc}"],
            capture_output=True, text=True, timeout=5).stdout
        return proc.lower() in out.lower()
    except Exception:
        return False


def _port_dipakai_browser_lain():
    """Port 9222 hidup tetapi dipegang browser BERBEDA dari pilihan user?
    (mis. jendela debug Brave lama masih nyala padahal user pilih Chrome).
    Return list pemegang [(pid, nama)]; [] bila cocok / tidak ada."""
    pilihan = _find_browser() or {}
    proc_pilihan = pilihan.get("proc", "")
    pemegang = _siapa_pegang_port()
    if not (proc_pilihan and pemegang):
        return []
    nama_pemegang = " ".join(n.lower() for _, n in pemegang)
    if proc_pilihan in nama_pemegang:
        return []
    return pemegang


def _restart_browser_debug():
    """Pemulihan terakhir: browser debug hidup di HTTP tetapi websocket
    DevTools-nya menggantung (Brave lama yang jarang dipakai ditidurkan
    Windows; 3x retry connect tetap timeout).
    Restart saja: tutup pemegang 9222, jalankan ulang dengan mode debug.
    Tab browser dipulihkan otomatis oleh sesi restore."""
    pemegang = _siapa_pegang_port()
    if not pemegang:
        return False
    print(f"[PEMULIHAN] Browser debug tidak merespons - memulai ulang "
          f"({', '.join(n for _, n in pemegang)})...")
    for pid, _nama in pemegang:
        try:
            _run_hidden(["taskkill", "/F", "/T", "/PID", str(pid)],
                        capture_output=True, timeout=8)
        except Exception:
            pass
    for _ in range(16):
        time.sleep(0.5)
        if not _cek_debug_port():
            break
    pilihan = _find_browser() or (state.BROWSER or {}) or {}
    exe = pilihan.get("exe") or ""
    if not exe or not os.path.isfile(exe):
        print("[PEMULIHAN] Browser tidak ditemukan - tidak bisa restart.")
        return False
    args = [exe, f"--remote-debugging-port={state.DEBUG_PORT}", "--restore-last-session"]
    if state.PROFILE_MODE == "saya" and state.PROFILE_DIR:
        ud_saya = profiles._ud_profil_arg(pilihan.get("name", ""))
        if ud_saya:
            args += [f"--user-data-dir={ud_saya}",
                     f"--profile-directory={state.PROFILE_DIR}"]
        else:
            args.append(f"--user-data-dir={state.DEDICATED_PROFILE}")
    elif pilihan.get("name") != "Brave":
        args.append(f"--user-data-dir={state.DEDICATED_PROFILE}")
    # jangan mencuri fokus: jendela browser muncul diminimized tanpa
    # mengaktifkan dirinya (user bisa sedang mengetik di aplikasi lain).
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 7   # SW_SHOWMINNOACTIVE
    subprocess.Popen(args, close_fds=True, startupinfo=si)
    for _ in range(40):
        time.sleep(0.5)
        if state.STOP:
            sys.exit(0)
        if _cek_debug_port().startswith("Chrome"):
            print("[PEMULIHAN] Browser debug hidup kembali.")
            return True
    return False


def _cari_tab_setup(br, pg_utama):
    """Tab SET-UP first-run (Edge/Chrome/Brave baru pertama kali dibuka di
    profil khusus bot): welcome / pilih default browser / izin cookie /
    sign-in sync. Return tab set-up pertama yang terlihat, None kalau
    tidak ada. (dulu bot langsung menimpa tab set-up; sekarang tunggu
    sampai user menutupnya.)"""
    for ctx2 in br.contexts:
        try:
            for pg2 in ctx2.pages:
                if pg2 == pg_utama:
                    continue
                u = (pg2.url or "").lower()
                if any(k in u for k in
                       ("first-run", "first_run", "firstrun", "welcome",
                        "onboarding", "getting-started", "chrome-signin")):
                    return pg2
        except Exception:
            continue
    return None


def _tutup_tab_kosong(br, pg_utama):
    """Tutup tab kosong sisa start-up browser (newtab/welcome/blank).
    Hanya kalau masih ada tab lain di context - jangan sampai jendela
    ikut tertutup."""
    for ctx in br.contexts:
        try:
            halaman = list(ctx.pages)
            if len(halaman) < 2:
                continue
            for pg in halaman:
                if pg == pg_utama:
                    continue
                try:
                    u = (pg.url or "").lower()
                except Exception:
                    continue
                if (u.startswith(("chrome://new", "edge://new", "brave://new",
                                  "chrome://newtab", "edge://newtab"))
                        or u in ("about:blank", "chrome://welcome",
                                 "edge://welcome", "brave://welcome")):
                    try:
                        pg.close()
                        print("Tab kosong sisa start-up browser ditutup.")
                    except Exception:
                        pass
        except Exception:
            pass


def _browser_dari_pemegang_port():
    """Browser TERPASANG yang saat ini memegang port 9222 (untuk mode
    Otomatis: tempeli saja yang sudah jalan). None kalau port kosong atau
    dipegang proses non-browser (WebView/Adobe dsb. - itu tetap lewat
    dialog izin)."""
    if not _cek_debug_port():
        return None
    holder = _siapa_pegang_port()
    nama = " ".join(n.lower() for _, n in holder)
    for c in BROWSER_CANDIDATES:
        if c["proc"] in nama:
            for p in c["paths"]:
                if p and os.path.isfile(p):
                    return {"name": c["name"], "exe": p, "proc": c["proc"]}
    return None


def siapkan_browser():
    """Pastikan ada browser Chromium (Brave/Chrome/Edge) debug di port
    9222 (atau port berikutnya bila 9222 dipakai aplikasi asing - lihat
    _sesuaikan_port). Browser LAIN milik bot yang memegang port tetap
    ditangani dengan izin user, bukan asal ditutup."""
    if state.STOP:
        sys.exit(0)
    _sesuaikan_port()
    browser_on_port = _cek_debug_port()

    # otomatis pintar: port sudah dipegang browser terpasang -> pakai browser
    # itu langsung (dulu Otomatis selalu Brave -> 'port dipegang browser lain'
    # -> minta izin menutup Chrome/Edge padahal tinggal ditempeli).
    otomatis = not ((state.FORCE_BROWSER or os.environ.get("TYPINGBOT_BROWSER", "")).strip())
    reuse = _browser_dari_pemegang_port() if otomatis else None
    if reuse is not None:
        state.BROWSER = reuse
        print(f"[OTOMATIS] {reuse['name']} sudah jalan dengan port debug - "
              "dipakai langsung tanpa menutup apa pun.")

    if "Edg" in browser_on_port and reuse is None:
        # Bisa Edge betulan, bisa juga WebView2 milik aplikasi lain (mis.
        # Adobe) yang membalas /json/version dengan string "Edg/...".
        print("Port 9222 dipegang proses berbasis Edge/WebView, "
              "mencari proses pemegangnya...")
        _bebaskan_port()
        browser_on_port = _cek_debug_port()
        if "Edg" in browser_on_port:
            print("MASIH terkunci. Cek pemegang port: netstat -ano | findstr :9222")
            print("Tutup manual aplikasinya, lalu jalankan ulang program.")
            sys.exit(1)
        print("Port 9222 berhasil dibebaskan.")

    if browser_on_port and reuse is None:
        # Port hidup, tapi dipegang browser lain dari pilihan user? (mis.
        # user pilih Chrome sementara jendela debug Brave lama masih nyala
        # atau menggantung) -> tutup pemegangnya (dengan izin) supaya
        # browser pilihan bisa memakai port.
        lain = _port_dipakai_browser_lain()
        if lain:
            print(f"Port 9222 dipegang browser lain "
                  f"({', '.join(n for _, n in lain)}), padahal pilihan: "
                  f"{(_find_browser() or {}).get('name', '?')}. "
                  "Menutup pemegang port...")
            _bebaskan_port(tanya_semua=True)
            browser_on_port = _cek_debug_port()
            if browser_on_port:
                print("Pemegang port tidak ditutup - bot tidak bisa lanjut. "
                      "Tutup jendela browser lama, lalu klik Start lagi.")
                sys.exit(1)

    if not browser_on_port:
        if _siapa_pegang_port():
            print("Port 9222 dipakai proses lain (bukan browser debug)...")
            _bebaskan_port()
            browser_on_port = _cek_debug_port()
        if not browser_on_port:
            state.BROWSER = _find_browser()
            if state.BROWSER is None:
                print("Tidak ada browser Chromium (Brave/Chrome/Edge). "
                      "Install salah satunya dulu.")
                sys.exit(1)
            nm = state.BROWSER["name"]
            # Mode 'profil saya': luncurkan dengan profil asli user. Browser
            # yang sedang jalan harus dimatikan dulu (dengan izin) - proses
            # baru hanya membuka jendela di proses lama tanpa mode debug.
            # Chrome/Edge dibuka lewat junction (lihat _ud_profil_arg).
            if state.PROFILE_MODE == "saya" and state.PROFILE_DIR:
                if _browser_sudah_jalan() and not profiles._tutup_browser_user(
                        state.BROWSER["proc"], nm):
                    ud_saya = ""
                else:
                    ud_saya = profiles._ud_profil_arg(nm)
                if ud_saya:
                    print(f"[PROFIL] membuka {nm} dengan profilmu "
                          f"({state.PROFILE_LABEL or state.PROFILE_DIR})...")
                    subprocess.Popen(
                        [state.BROWSER["exe"], f"--remote-debugging-port={state.DEBUG_PORT}",
                         f"--user-data-dir={ud_saya}",
                         f"--profile-directory={state.PROFILE_DIR}",
                         "--no-first-run"],
                        close_fds=True)
                    for _ in range(30):
                        time.sleep(0.5)
                        if state.STOP:
                            sys.exit(0)
                        if _cek_debug_port().startswith("Chrome"):
                            break
                    if _cek_debug_port().startswith("Chrome"):
                        browser_on_port = _cek_debug_port()
                    else:
                        print("[PROFIL] profil kamu gagal dibuka - bot "
                              "memakai profil khusus bot.")
            # Chrome/Edge modern menolak flag debug di profil default
            # (Chromium 136+). Jangan coba-coba (buka jendela tanpa debug
            # lalu tunggu 15 dtk sia-sia): langsung profil khusus bot.
            # Hal yang sama kalau browser sama sudah jalan tanpa debug -
            # profil khusus bisa berjalan berdampingan dengan jendela itu.
            if not browser_on_port:
                langsung_profil = (nm != "Brave") or _browser_sudah_jalan()
                if not langsung_profil:
                    print(f"Port 9222 kosong: membuka {nm} otomatis "
                          "dengan mode debug...")
                    subprocess.Popen([state.BROWSER["exe"], f"--remote-debugging-port={state.DEBUG_PORT}"],
                                     close_fds=True)
                    for _ in range(30):
                        time.sleep(0.5)
                        if state.STOP:
                            sys.exit(0)
                        if _cek_debug_port().startswith("Chrome"):
                            break
                    if not _cek_debug_port().startswith("Chrome"):
                        langsung_profil = True
                if langsung_profil:
                    # Profil khusus bot: login edclub sekali, tersimpan selamanya.
                    alasan = ("sudah jalan tanpa debug" if _browser_sudah_jalan()
                              else "profil default menolak mode debug")
                    print(f"Membuka {nm} dengan profil khusus bot ({alasan})...")
                    subprocess.Popen([state.BROWSER["exe"],
                                      f"--remote-debugging-port={state.DEBUG_PORT}",
                                      f"--user-data-dir={state.DEDICATED_PROFILE}"],
                                     close_fds=True)
                    for _ in range(30):
                        time.sleep(0.5)
                        if state.STOP:
                            sys.exit(0)
                        if _cek_debug_port().startswith("Chrome"):
                            break
    if state.BROWSER is None:
        state.BROWSER = _find_browser() or {"name": "browser", "exe": "", "proc": ""}

    print(f"Menyambungkan Playwright ke browser ({state.BROWSER['name']})...")
    # Retry wajib : sambungan websocket sesi sebelumnya yang
    # terputus paksa (taskkill/app ditutup) menyisakan koneksi setengah
    # terbuka di sisi browser - sambungan pertama setelah itu timeout,
    # tetapi justru menendang koneksi mati itu lepas dan percobaan ke-2
    # langsung berhasil. Tanpa retry = "gagal connect" padahal browser baik.
    def _tangga_connect():
        """Return SELALU 3-tuple (pw, browser, pesan_gagal).
        Pernah bug: slot ke-2 diisi string pesan -> 'browser is None'
        tidak pernah benar -> pemulihan restart tidak pernah jalan dan
        crash 'str' object has no attribute 'contexts'."""
        br = None
        p = None
        pesan = ""
        for percobaan in range(3):
            if state.STOP:
                sys.exit(0)
            try:
                p = sync_playwright().start()
                br = p.chromium.connect_over_cdp(
                    f"http://{_alamat_debug()}",
                    timeout=20000 if percobaan == 0 else 12000)
                return p, br, ""
            except Exception as e:
                pesan = str(e)[:120]
                if p is not None:
                    try:
                        p.stop()
                    except Exception:
                        pass
                p = None
                br = None
                if percobaan == 0:
                    print("Sambungan pertama gagal (sisa koneksi lama di "
                          "browser) - mencoba lagi...")
                time.sleep(1.5)
        return None, None, pesan

    pw, browser, pesan = _tangga_connect()
    if browser is None and _cek_debug_port():
        # Port hidup di HTTP tetapi websocket menolak = DevTools browser
        # menggantung (idle lama). Restart browser debug lalu coba lagi.
        # kill + relaunch debug browser -> connect langsung ok.
        if _restart_browser_debug():
            pw, browser, pesan = _tangga_connect()
    if browser is None:
        print(f"Gagal menyambung ke browser: {pesan or 'tidak diketahui'}")
        print("Tutup semua jendela browser, lalu klik Start lagi.")
        sys.exit(1)
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()

    page = None
    # Tutup sisa tab Stripe/checkout dari sesi sebelumnya (dibuat saat bot
    # pernah salah klik CTA premium). Tab ini tidak berguna, dan pernah
    # menipu deteksi tab edclub.
    for pg in list(ctx.pages):
        try:
            h = (urlparse(_real_url(pg)).hostname or "").lower()
        except Exception:
            continue
        if "stripe" in h:
            try:
                pg.close()
                print(f"Tab sisa Stripe ditutup ({h})")
            except Exception:
                pass
    # Tab edclub sisa sesi lalu sering mati (layar gelap / ter-bawa ke
    # Stripe checkout) dan malah menang pemilihan tab - bot lalu nyangkut
    # 20-25 detik sebelum recovery menyalakannya. Solusi: periksa
    # kesehatan tiap tab, ambil satu terbaik, tutup sisanya otomatis.
    edclub_tabs = []
    for pg in ctx.pages:
        try:
            if _is_edclub_url(_real_url(pg)):
                edclub_tabs.append(pg)
        except Exception:
            continue
    healthy = []
    for pg in edclub_tabs:
        try:
            u1 = _real_url(pg)
            time.sleep(0.25)
            u2 = _real_url(pg)
        except Exception:
            continue
        # URL masih berubah / pindah host = tab sedang restore atau
        # replay redirect Stripe (hijack sisa sesi lama) - jangan dipakai.
        if u1 != u2 or not _is_edclub_url(u2):
            continue
        try:
            pg.evaluate("() => 1")   # renderer kritis -> raise di sini
        except Exception:
            continue
        healthy.append(pg)
    # Tutup tab edclub yang tidak sehat supaya tidak menumpuk.
    for pg in edclub_tabs:
        if pg not in healthy:
            try:
                pg.close()
                print("Tab edclub mati/sisa ditutup otomatis")
            except Exception:
                pass
    # Pilih yang paling mungkin punya pekerjaan: .play dengan token/canvas
    # aktif > .play apa pun. Skor sama -> tab paling kanan (terbaru) menang;
    # (dulu: skor sama dimenangkan tab pertama = tab lama yang mati).
    def _score(pg):
        try:
            url = _real_url(pg)
        except Exception:
            return -1
        s = 0
        if ".play" in url:
            s += 10
        try:
            info = pg.evaluate("() => {" + PLAYABLE_CHECK_JS + "}")
            if info:
                if info.get("clr"):
                    s += 5
                elif info.get("boxed"):
                    s += 3
                elif info.get("canvas"):
                    s += 1
                if info.get("done"):
                    s -= 8   # layar skor/selesai = tidak ada kerjaan
        except Exception:
            pass
        return s
    if healthy:
        page = max(healthy, key=lambda pg: (_score(pg), healthy.index(pg)))
        others = [pg for pg in healthy if pg is not page]
        for pg in others:
            try:
                pg.close()
            except Exception:
                pass
        if others:
            print(f"{len(others)} tab edclub lain ditutup otomatis "
                  "(dipilih 1 tab terbaik)")
    if page is None:
        # Kalau tidak ada tab edclub: buka tab baru. pernah gagal live:
        # menutup tab Stripe sisa = satu-satunya tab di jendelanya ->
        # Brave membongkar jendela itu -> Target.createTarget gagal sesaat.
        # Solusi: retry + fallback ke tab yang ada / context baru.
        for attempt in range(4):
            try:
                page = ctx.new_page()
                break
            except Exception as e:
                print(f"Buka tab baru gagal ({attempt + 1}/4): {str(e)[:60]}")
                time.sleep(1.5)
        if page is None:
            for c2 in browser.contexts:
                try:
                    if c2.pages:
                        page = c2.pages[0]
                        break
                except Exception:
                    continue
        if page is None:
            try:
                page = browser.new_context().new_page()
            except Exception:
                pass
        if page is None:
            print("Gagal membuka tab. Buka edclub.com manual di Brave, "
                  "lalu jalankan ulang program.")
            sys.exit(1)
        print("Tab edclub belum ada. Membuka edclub.com otomatis...")
        try:
            page.goto("https://www.edclub.com/sportal/program-3.game",
                      timeout=25000)
        except Exception:
            print("Gagal membuka edclub - buka manual di Brave, bot menunggu.")
    # Tutup tab sisa START-UP browser (selalu, dua kali: sekarang + setelah
    # set-up): browser baru dibuka dengan 1 tab kosong (newtab), lalu bot
    # membuat/menemukan tab edclub sendiri -> tab kosong menganggung.
    # Live: Edge membuat tab newtab-nya belakangan (setelah welcome-nya
    # ditutup), jaitu pembersihan sekali di sini kurang - jalankan lagi
    # setelah gerbang set-up. Hanya tab newtab/welcome/blank, hanya kalau
    # masih ada tab lain (jangan sampai jendela ikut tertutup).
    _tutup_tab_kosong(browser, page)
    # Tab set-UP first-run (Edge/Chrome/Brave baru pertama kali dibuka di
    # profil khusus bot): welcome / pilih default browser / izin cookie /
    # sign-in sync. Dulu bot langsung jalan menimpa set-up (
    # sebaiknya tunggu). Sekarang: instruksi + tunggu sampai semua tab
    # set-up ditutup user, bot lanjut otomatis setelahnya.
    if _cari_tab_setup(browser, page) is not None:
        state.MENUNGGU_SETUP = True
        print("[SETUP] Browser baru sedang set-up (welcome / pilih default "
              "browser / cookie). Selesaikan dulu set-upnya di jendela "
              "browser, lalu TUTUP tab set-upnya - bot mulai bekerja "
              "otomatis begitu tab set-up ditutup.")
        while not state.STOP:
            time.sleep(1.0)
            if _cari_tab_setup(browser, page) is None:
                break
        state.MENUNGGU_SETUP = False
        if not state.STOP:
            print("[SETUP] Set-up browser selesai - bot mulai bekerja.")
            _tutup_tab_kosong(browser, page)
    return pw, browser, page


def connect():
    """Sambungkan ke Brave. HARUS dipanggil dari thread yang sama dengan
    main_loop() - objek Playwright tidak boleh dipakai lintas thread."""
    if state.PAGE is not None:
        return True
    try:
        state.pw, state.browser, state.PAGE = siapkan_browser()
    except SystemExit:
        raise
    except Exception as e:
        print(f"Gagal menyambung ke browser: {str(e)[:120]}")
        print("Tutup semua jendela browser, lalu klik Start lagi.")
        sys.exit(1)
    print(f"Terhubung! Tab aktif: {state.PAGE.url}")
    session._pasang_login_sentinel()
    if not OCR_AVAILABLE:
        print("Catatan: 'winocr' tidak ada -> fallback OCR nonaktif (pip install winocr).")
    return True


def disconnect():
    """Putuskan koneksi Playwright dan reset cache global. Harus dipanggil
    dari thread yang menjalankan connect(). Tanpa ini, restart dari GUI
    memakai objek Playwright milik thread lama yang sudah mati ->
    error "cannot switch to a different thread"."""
    # Reset status login dulu (sebelum guard): disconnect yang dipanggil
    # tanpa koneksi pun harus membersihkan state sesi sebelumnya.
    state.PERLU_LOGIN = False
    state.LOGIN_DICEK = False
    state.RENTANG_SIAP = False
    state._login_sentinel["ok"] = True
    state._login_sentinel["alasan"] = ""
    state._login_sentinel["pernah_in"] = False
    state._login_sentinel["unknown_mulai"] = 0.0
    state._login_ck["terakhir"] = 0.0
    if state.pw is None and state.PAGE is None:
        return
    try:
        state.pw.stop()
    except Exception:
        pass
    state.pw, state.browser, state.PAGE = None, None, None
