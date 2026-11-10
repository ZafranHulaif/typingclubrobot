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
from ctypes import wintypes
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from . import state
from . import browser
from . import profiles
from . import session
from .config import (BROWSER_CANDIDATES, OCR_AVAILABLE)
from .jstemplates import (PLAYABLE_CHECK_JS)




def _debug_address():
    return f"127.0.0.1:{state.DEBUG_PORT}"

# ---------------------------------------------------------------------------
# Koneksi: cek port, bersihkan dari Edge, buka Brave otomatis, sambungkan
# ---------------------------------------------------------------------------

# Anti-popup: window.open & anchor target=_blank dinavigasi DI HALAMAN
# UTAMA (dipasang via add_init_script - aktif di semua dokumen baru).
# Tanpa ini, klik 'Sign in with Google' memicu popup = jendela EDGE
# sungguhan (address bar, tombol close - tak bisa dicabut via Win32)
# yang diadopsi lintas-proses ke app: klik jalan, KEYBOARD MATI (input
# tak pernah sampai ke thread msedge - keluhan user).
NO_POPUP_JS = """
(function(){
  try { window.focus = function(){}; } catch (e) {}
  // window.open edclub dipanggil dgn URL KOSONG dulu (live:
  // window.open('', '_blank', 'location=no,toolbar=yes')) lalu kodenya
  // set win.location.href = url google. Kalau open() mengembalikan null
  // -> edclub menampilkan 'allow pop-ups'. Maka: kembalikan STUB jujur
  // yang siap di-set location-nya; semua penugasan lokasi = navigasi
  // HALAMAN UTAMA (OAuth jalan full-page di dalam app, tanpa jendela
  // kedua - address bar & tombol close hilang, keyboard hidup).
  function buatStub(u0){
    var cur = u0 || 'about:blank';
    var loc = {};
    Object.defineProperty(loc, 'href', {
      set: function(v){ cur = String(v); location.href = v; },
      get: function(){ return cur; }
    });
    loc.replace = function(x){ cur = String(x); location.replace(x); };
    loc.assign  = function(x){ cur = String(x); location.href = x; };
    loc.reload  = function(){ location.reload(); };
    var w = {
      closed: false, name: '_blank', opener: window,
      focus: function(){}, blur: function(){}, close: function(){},
      print: function(){}, moveTo: function(){}, moveBy: function(){},
      resizeTo: function(){}, resizeBy: function(){},
      scrollTo: function(){}, scrollBy: function(){},
      postMessage: function(){}, addEventListener: function(){},
      removeEventListener: function(){},
      dispatchEvent: function(){ return true; },
      document: { write: function(){}, writeln: function(){},
                  open: function(){}, close: function(){} }
    };
    Object.defineProperty(w, 'location', {
      get: function(){ return loc; },
      set: function(v){ var t = (v && v.href) ? String(v.href) : String(v);
                        cur = t; location.href = t; }
    });
    return w;
  }
  window.open = function(u){
    if (u) { location.href = u; }
    return buatStub(u);
  };
  document.addEventListener('click', function(e){
    try {
      var a = e.target && e.target.closest
              ? e.target.closest('a[target="_blank"]') : null;
      if (a) a.removeAttribute('target');
    } catch (e2) {}
  }, true);
})();
"""


_DUR_FIX_JS = """
(function () {
  // Normalisasi dur ketikan di POST postTypingResults: bot cepat
  // (300+ wpm = dur ~40ms/karakter) ditolak sistem anti-buru-buru
  // edclub (tanpa layar skor, level diulang dari awal). Hook fetch+XHR:
  // kalau rata-rata dur di bawah ambang, naikkan ke ritme natural
  // (~95-120ms) supaya penyelesaian diterima. Laju ketik ASLI tetap
  // cepat (hemat waktu nyata), hanya laporannya dibuat wajar.
  if (window.__tbDurFix) return;
  window.__tbDurFix = true;
  var FLOOR = 80;
  function perbaiki(data) {
    try {
      var f = data && data.frotz;
      var pc = f && f.per_chr;
      if (!Array.isArray(pc) || pc.length < 8) return data;
      var sum = 0, n = 0;
      for (var i = 0; i < pc.length; i++) {
        var d = +pc[i].dur || 0;
        if (d > 0) { sum += d; n++; }
      }
      var avg = n ? sum / n : 0;
      if (avg >= FLOOR) return data;   // ritme sudah wajar - biarkan
      // target 65..85 ms = terlapor ~140-185 wpm (dulu 95..120 =
      // terlapor ~110 - pemborosan angka; ambang tolak server masih
      // jauh di bawah ini, ladder live terus mengecek)
      var target = 65 + Math.random() * 20;
      var scale = target / (avg || target);
      for (var j = 0; j < pc.length; j++) {
        var d2 = +pc[j].dur || 0;
        if (d2 > 0) {
          d2 = Math.round(d2 * scale * (0.75 + Math.random() * 0.5));
          pc[j].dur = Math.max(45, d2);
        }
      }
      // history[k] = [chr, dur] cermin per_chr - tulis ulang agar
      // konsisten (server men-echo history di respons details)
      if (Array.isArray(f.history)) {
        for (var k = 0; k < f.history.length && k < pc.length; k++) {
          if (Array.isArray(f.history[k])
              && f.history[k].length >= 2) {
            f.history[k][1] = pc[k].dur;
          }
        }
      }
      if (typeof data.duration === 'number') {
        var total = 0;
        for (var m = 0; m < pc.length; m++) total += (+pc[m].dur || 0);
        if (data.duration < total) data.duration = total;
      }
    } catch (e) {}
    return data;
  }
  var of = window.fetch;
  if (of) {
    window.fetch = function (input, init) {
      try {
        var url = typeof input === 'string' ? input
          : (input && input.url) || '';
        if (url.indexOf('postTypingResults') >= 0 && init
            && typeof init.body === 'string'
            && init.body.indexOf('per_chr') >= 0) {
          init.body = JSON.stringify(perbaiki(JSON.parse(init.body)));
        }
      } catch (e) {}
      return of.apply(this, arguments);
    };
  }
  try {
    var os = XMLHttpRequest.prototype.send;
    var oo = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function (m, u) {
      this.__tbUrl = u;
      return oo.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function (b) {
      try {
        if (b && typeof b === 'string'
            && (this.__tbUrl || '').indexOf('postTypingResults') >= 0
            && b.indexOf('per_chr') >= 0) {
          b = JSON.stringify(perbaiki(JSON.parse(b)));
        }
      } catch (e) {}
      return os.call(this, b);
    };
  } catch (e) {}
})();
"""


def _is_edclub_url(url):
    """Cek hostname ASLI (bukan substring!): URL Stripe yang di dalam
    parameternya menyebut 'edclub.com' pernah menipu cek substring dan
    bikin bot nyangkut di halaman checkout mati."""
    try:
        h = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return h.endswith("edclub.com") or h.endswith("typingclub.com")


def _oauth_url(url):
    """True = URL di tengah alur OAuth/login eksternal: pilih akun
    Google, bridge YouTube, callback token. User SEDANG login - healing
    tab-hijack & popup 'menuju login' tidak boleh menyentuh halaman ini
    (dulu: halaman utama dilempar ke sportal di tengah user memilih
    akun Google -> loop loading -> daftar -> login tanpa ujung)."""
    try:
        h = (urlparse(url).hostname or "").lower()
        p = (urlparse(url).path or "").lower()
    except Exception:
        return False
    return (h.endswith("accounts.google.com")
            or h.endswith("accounts.youtube.com")
            or h.endswith("googleusercontent.com")
            or "auth_callback" in p)


def _lesson_play_url(u):
    """Rute lesson SPA baru /student/course/<c>/lesson/<id> -> bentuk
    .play lama .../program-<c>/<id>.play. ID lesson-nya SAMA (live:
    /lesson/116 = 116.play) - normalisasi di sini supaya semua cek
    '.play' & peta level bot tetap jalan di UI baru."""
    if not u or "/lesson/" not in u:
        return u
    m = re.search(r"/student/course/(\d+)/lesson/(\d+)", u)
    if not m:
        return u
    return f"https://www.edclub.com/sportal/program-{m.group(1)}/{m.group(2)}.play"


def _real_url(pg):
    """URL asli halaman via evaluate. page.url Playwright bisa stale
    (isi sudah m.stripe.network tapi masih melaporkan edclub);
    location.href tidak pernah bohong. URL lesson UI baru dinormalkan
    ke bentuk .play (lihat _lesson_play_url)."""
    u = None
    try:
        u = pg.evaluate("() => location.href")
        if u and not isinstance(u, str):
            u = None
    except Exception:
        u = None
    if not u:
        try:
            u = pg.url
        except Exception:
            return ""
    return _lesson_play_url(u)


def _pages_alive():
    """Masih ada tab/halaman di browser? Window yang ditutup mengosongkan
    daftar halaman SEKETIKA, padahal proses Chromium bisa hidup beberapa
    detik lebih lama (is_connected() masih True) - dulu bot terus
    mengetik 'ke ruang hantu' sampai level habis dan kartu GUI terpaku
    di situ (keluhan live). Browser diminimalkan tetap True: tab-nya
    masih ada."""
    try:
        for ctx in state.browser.contexts:
            if ctx.pages:
                return True
    except Exception:
        pass
    return False


def _edclub_frame(fr):
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
    # corevideo.edclub.app = frame player video UI student baru (update
    # Nov 2026) - dulu tidak lolos filter, handler video tidak pernah
    # melihat <video>-nya: level video TUNDA terus (keluhan 'video
    # levels won't load').
    return (h.endswith("edclub.com") or h.endswith("typingclub.com")
            or h.endswith("edclub.app"))


def _check_debug_port():
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://{_debug_address()}/json/version", timeout=2) as r:
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


def _holder_identity(pid, nama):
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


def _ask_close(nama, pid, exe=""):
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


def _free_port(tanya_semua=True):
    """Port 9222 dipakai proses lain -> identifikasi PEMEGANG ASLINYA
    (bisa bukan browser sama sekali; WebView2 milik Adobe dsb. dinaiki
    ke aplikasi induknya), lalu SELALU minta izin user sebelum taskkill.
    (dulu proses 'edge' ditutup paksa diam-diam, pernah menutup
    WebView milik aplikasi lain.)
    Parameter tanya_semua dipertahankan untuk kompatibilitas pemanggil;
    sekarang semua pemegang selalu ditanyakan."""
    pemegang = _port_holders()
    if not pemegang:
        return False
    for pid, nama in pemegang:
        info = _holder_identity(pid, nama)
        print(f"  -> port 9222 dipakai {info['nama']} "
              f"({nama}, PID {pid})")
        if not _ask_close(info["nama"], pid, info["exe"]):
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


def _port_holders():
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


def _is_our_browser(nama_pemegang):
    """Apakah pemegang port salah satu browser yang dikelola bot
    (brave/chrome/msedge)? Bukan -> aplikasi asing (widget sistem
    bawaan laptop, WebView2 milik aplikasi lain, dll.) -> jangan
    pernah dipaksa ditutup."""
    return any(c["proc"] in nama_pemegang for c in BROWSER_CANDIDATES)


def _port_bind_free(port):
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
            return True
    except OSError:
        return False


def _pick_port():
    """Dipanggil di awal ensure_browser. Port 9222 dipegang aplikasi
    ASING (bukan brave/chrome/msedge)? Bot pindah ke port kosong
    berikutnya dan MEMBIARKAN aplikasi itu tetap jalan - tanpa dialog
    'tutup aplikasi' yang menakutkan. Kasus nyata: Batterywidgethost
    bawaan laptop pegang 9222, bot malah minta ditutup padahal cukup
    pindah port."""
    pemegang = _port_holders()
    if not pemegang:
        return state.DEBUG_PORT
    nama = " ".join(n.lower() for _, n in pemegang)
    if _is_our_browser(nama):
        return state.DEBUG_PORT
    for kandidat in range(9223, 9323):
        if _port_bind_free(kandidat):
            try:
                info = _holder_identity(pemegang[0][0], pemegang[0][1])
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


def _browser_running():
    proc = (state.BROWSER or {}).get("proc", "brave.exe")
    try:
        out = _run_hidden(["tasklist", "/FI", f"IMAGENAME eq {proc}"],
            capture_output=True, text=True, timeout=5).stdout
        return proc.lower() in out.lower()
    except Exception:
        return False


def _port_held_by_other_browser():
    """Port 9222 hidup tetapi dipegang browser BERBEDA dari pilihan user?
    (mis. jendela debug Brave lama masih nyala padahal user pilih Chrome).
    Return list pemegang [(pid, nama)]; [] bila cocok / tidak ada."""
    pilihan = _find_browser() or {}
    proc_pilihan = pilihan.get("proc", "")
    pemegang = _port_holders()
    if not (proc_pilihan and pemegang):
        return []
    nama_pemegang = " ".join(n.lower() for _, n in pemegang)
    if proc_pilihan in nama_pemegang:
        return []
    return pemegang


def _matikan_restore_profil():
    """Mode app + restore sesi = jendela NORMAL yang di-restore ikut
    muncul (dengan tab strip + toolbar) dan justru dipilih sebagai
    jendela embed (judulnya edclub) - hasilnya UI browser kelihatan.
    Matikan 'lanjutkan sesi' di profil khusus bot supaya peluncuran
    embed hanya menghasilkan SATU jendela app: murni halaman web."""
    root = state.DEDICATED_PROFILE
    if not os.path.isdir(root):
        return
    for nama in ("Default", "Profile 1", "Profile 2"):
        pref = os.path.join(root, nama, "Preferences")
        if not os.path.isfile(pref):
            continue
        try:
            with open(pref, encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("session", {})["restore_on_startup"] = 5
            prof = data.setdefault("profile", {})
            prof["exit_type"] = "Normal"
            with open(pref, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception:
            pass


def bersihkan_browser_embed():
    """v3.1: browser debug sisa sesi sebelumnya berjalan dalam mode NORMAL
    (tab strip + toolbar terlihat di dalam app). Supaya tampilan murni
    halaman web (mode app), pemegang port yang PASTI milik bot (cmdline
    memakai profil khusus DEDICATED_PROFILE) dimatikan dulu - ensure
    berikutnya meluncurkan ulang dalam mode app. Browser pribadi user
    (profil saya) tidak disentuh."""
    _matikan_restore_profil()
    pemegang = _port_holders()
    if not pemegang:
        return False
    ded = state.DEDICATED_PROFILE.replace("/", "\\").lower()
    dibunuh = False
    for pid, _nama in pemegang:
        try:
            out = _run_hidden(
                ["powershell", "-NoProfile", "-Command",
                 f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}')"
                 ".CommandLine"],
                capture_output=True, text=True, timeout=12).stdout or ""
            if ded and ded in out.lower():
                _run_hidden(["taskkill", "/F", "/T", "/PID", str(pid)],
                            capture_output=True, timeout=8)
                dibunuh = True
        except Exception:
            pass
    if dibunuh:
        for _ in range(20):
            time.sleep(0.5)
            if not _check_debug_port():
                break
        print("Browser debug lama ditutup untuk ganti ke tampilan app...")
    return dibunuh


def _restart_browser_debug():
    """Pemulihan terakhir: browser debug hidup di HTTP tetapi websocket
    DevTools-nya menggantung (Brave lama yang jarang dipakai ditidurkan
    Windows; 3x retry connect tetap timeout).
    Restart saja: tutup pemegang 9222, jalankan ulang dengan mode debug.
    Tab browser dipulihkan otomatis oleh sesi restore."""
    pemegang = _port_holders()
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
        if not _check_debug_port():
            break
    pilihan = _find_browser() or (state.BROWSER or {}) or {}
    exe = pilihan.get("exe") or ""
    if not exe or not os.path.isfile(exe):
        print("[PEMULIHAN] Browser tidak ditemukan - tidak bisa restart.")
        return False
    args = [exe, f"--remote-debugging-port={state.DEBUG_PORT}", "--restore-last-session",
            "--start-minimized"]
    if state.PROFILE_MODE == "saya" and state.PROFILE_DIR:
        ud_saya = profiles._profile_dir_arg(pilihan.get("name", ""))
        if ud_saya:
            args += [f"--user-data-dir={ud_saya}",
                     f"--profile-directory={state.PROFILE_DIR}"]
        else:
            args.append(f"--user-data-dir={state.DEDICATED_PROFILE}")
    elif pilihan.get("name") != "Brave":
        args.append(f"--user-data-dir={state.DEDICATED_PROFILE}")
    # jangan mencuri fokus: jendela browser muncul di belakang tanpa
    # mengaktifkan dirinya (user bisa sedang mengetik di aplikasi lain).
    _popen_latar(args)
    for _ in range(40):
        time.sleep(0.5)
        if state.STOP:
            sys.exit(0)
        if _check_debug_port().startswith("Chrome"):
            print("[PEMULIHAN] Browser debug hidup kembali.")
            return True
    return False


def _popen_latar(args):
    """Luncurkan browser TANPA mencuri fokus: jendela muncul di belakang
    (minimized tanpa aktivasi). Filosofi alur: fokus browser hanya saat
    ada yang harus dikerjakan user di sana (login, pilih level, set-up)
    - engine mengibarkan FOCUS_BROWSER_AT untuk kasus itu.
    v3: saat browser ditanam di app (EMBED_BROWSER), jendela diluncurkan
    dalam MODE APP (--app): tanpa tab strip, tanpa toolbar, tanpa
    bookmark - yang tampak di dalam app hanya halaman web. Tab-tab latar
    CDP tetap hidup sebagai target tersembunyi di jendela yang sama
    (teruji: createTarget & ctx.new_page tidak membuat jendela baru)."""
    if getattr(state, "EMBED_BROWSER", False):
        args = [a for a in args if a != "--restore-last-session"]
        if not any(a.startswith("--app=") for a in args):
            args.append("--app=about:blank")
    lama = _hwnd_browser_visible()
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 7   # SW_SHOWMINNOACTIVE
    subprocess.Popen(args, close_fds=True, startupinfo=si)
    # Brave mengabaikan --start-minimized saat cold start (keluhan live:
    # jendela PERTAMA melompat ke depan dan mencuri fokus) - jaga dan
    # kecilkan jendela baru tanpa aktivasi sampai masa launch selesai.
    threading.Thread(target=_kecilkan_jendela_baru, args=(lama,),
                     daemon=True).start()


_KANDIDAT_EXE = {"brave.exe", "chrome.exe", "msedge.exe"}


def _hwnd_browser_visible():
    """Set hwnd semua jendela browser kandidat yang terlihat saat ini."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    temuan = set()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_cb(hwnd, _l):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            h = kernel32.OpenProcess(0x1000, False, pid.value)
            if not h:
                return True
            buf = ctypes.create_unicode_buffer(512)
            n = wintypes.DWORD(512)
            ok = kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n))
            kernel32.CloseHandle(h)
            if ok:
                exe = buf.value.replace("\\", "/").split("/")[-1].lower()
                if exe in _KANDIDAT_EXE:
                    temuan.add(hwnd)
        except Exception:
            pass
        return True

    user32.EnumWindows(enum_cb, 0)
    return temuan


def _kecilkan_jendela_baru(lama, batas=12.0):
    """Kecilkan HANYA jendela browser BARU hasil launch, tanpa aktivasi.
    Jendela yang sudah ada sebelum launch (browser pribadi user yang
    ikut jalan berdampingan) tidak disentuh. Begitu engine meminta fokus
    (FOCUS_BROWSER_AT - halaman login siap dilihat) watcher langsung
    pamit supaya tidak mengecilkan jendela yang memang harus terlihat."""
    user32 = ctypes.windll.user32
    mulai = time.time()
    tenggat = time.perf_counter() + batas
    while time.perf_counter() < tenggat:
        if state.STOP or state.EMBED_BROWSER \
                or state.FOCUS_BROWSER_AT > mulai:
            return
        baru = _hwnd_browser_visible() - lama
        if state.STOP or state.FOCUS_BROWSER_AT > mulai:
            return
        for hwnd in baru:
            try:
                user32.ShowWindow(hwnd, 7)  # SW_SHOWMINNOACTIVE
            except Exception:
                pass
        time.sleep(0.25)


def _kecilkan_jendela_bot():
    """Kecilkan jendela browser bot kembali setelah bot membuat tab di
    latar: Chromium TETAP mengaktifkan dirinya walau Target.createTarget
    memakai background=True (keluhan live: jendela melompat ke depan
    sesaat). Judul dinormalisasi tanpa spasi - judul situs bisa
    'Typing Club' / 'EdClub'. Hanya jendela bot yang disentuh.
    v3: bila GUI menanam browser di app (EMBED_BROWSER), jendela tidak
    disentuh sama sekali - user sedang menonton bot bekerja di dalam app."""
    if getattr(state, "EMBED_BROWSER", False):
        return
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        kandidat = {"brave.exe", "chrome.exe", "msedge.exe"}

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum_cb(hwnd, _l):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                h = kernel32.OpenProcess(0x1000, False, pid.value)
                if not h:
                    return True
                buf = ctypes.create_unicode_buffer(512)
                n = wintypes.DWORD(512)
                ok = kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n))
                kernel32.CloseHandle(h)
                if not ok:
                    return True
                exe = buf.value.replace("\\", "/").split("/")[-1].lower()
                if exe in kandidat:
                    judul = ctypes.create_unicode_buffer(256)
                    user32.GetWindowTextW(hwnd, judul, 256)
                    jl = judul.value.lower().replace(" ", "")
                    if jl and ("edclub" in jl or "typingclub" in jl):
                        user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE (tanpa aktivasi)
            except Exception:
                pass
            return True

        user32.EnumWindows(enum_cb, 0)
    except Exception:
        pass


def _tab_latar(ctx):
    """Tab baru TANPA mengangkat jendela browser. ctx.new_page() Playwright
    membuat tab FOREGROUND - Chromium mengaktifkan dirinya dan menaikkan
    jendela OS (keluhan live: browser melompat ke depan di tengah bot
    bekerja, padahal user sedang tidak perlu melihat apa pun). Lewat CDP
    Target.createTarget(background=True) tab tetap di belakang; kalau CDP
    gagal, jatuh ke new_page() biasa. Hanya untuk context default - context
    lain butuh browserContextId, pakai jalur lama.
    v3.2: di mode WebView2 (browser DI DALAM app) createTarget = jendela
    POPUP BARU yang menumpuk & tak pernah tertutup (browser single-window)
    - selalu pakai halaman utama yang sama; engine melanjutkan dengannya."""
    if getattr(state, "BROWSER_WV2", False):
        pg = getattr(state, "PAGE", None)
        if pg is None:
            try:
                pg = ctx.pages[0]
            except Exception:
                pg = None
        if pg is not None:
            if not getattr(state, "EMBED_BROWSER", False):
                try:
                    pg.bring_to_front()
                except Exception:
                    pass
            return pg
    lama = []
    try:
        lama = list(ctx.pages)
    except Exception:
        pass
    br = None
    try:
        br = ctx.browser
    except Exception:
        br = None
    default_ctx = bool(br and br.contexts and ctx is br.contexts[0])
    baru = None
    if default_ctx:
        try:
            ses = br.new_browser_cdp_session()
            ses.send("Target.createTarget",
                     {"url": "about:blank", "background": True})
            for _ in range(50):
                time.sleep(0.1)
                for pg in ctx.pages:
                    if pg not in lama:
                        baru = pg
                        break
                if baru is not None:
                    break
        except Exception:
            baru = None
    if baru is None:
        # CDP sempat berhasil tapi Playwright belum mencatat page-nya saat
        # poll habis - scan sekali lagi sebelum membuat duabelas (dulu:
        # fallback new_page() membuat tab KEDUA, user melihat dua tab).
        try:
            for pg in ctx.pages:
                if pg not in lama:
                    baru = pg
                    break
        except Exception:
            pass
    if baru is None:
        try:
            baru = ctx.new_page()
        except Exception:
            return None
    # app mode: halaman SUDAH selalu terlihat (webview = app sendiri)
    # - bring_to_front di sini cuma mencuri fokus OS tiap lesson
    # (keluhan live: 'app keeps focusing itself') - jangan.
    if not getattr(state, "EMBED_BROWSER", False) and not state.NEEDS_LOGIN:
        _kecilkan_jendela_bot()
    return baru


def _find_setup_tab(br, pg_utama):
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


def _close_empty_tabs(br, pg_utama):
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


def _browser_from_port_holder():
    """Browser TERPASANG yang saat ini memegang port 9222 (untuk mode
    Otomatis: tempeli saja yang sudah jalan). None kalau port kosong atau
    dipegang proses non-browser (WebView/Adobe dsb. - itu tetap lewat
    dialog izin)."""
    if not _check_debug_port():
        return None
    holder = _port_holders()
    nama = " ".join(n.lower() for _, n in holder)
    for c in BROWSER_CANDIDATES:
        if c["proc"] in nama:
            for p in c["paths"]:
                if p and os.path.isfile(p):
                    return {"name": c["name"], "exe": p, "proc": c["proc"]}
    return None


def ensure_browser():
    """Pastikan ada browser Chromium (Brave/Chrome/Edge) debug di port
    9222 (atau port berikutnya bila 9222 dipakai aplikasi asing - lihat
    _pick_port). Browser LAIN milik bot yang memegang port tetap
    ditangani dengan izin user, bukan asal ditutup."""
    if state.STOP:
        sys.exit(0)
    wv2 = bool(getattr(state, "BROWSER_WV2", False))
    if wv2:
        # v3.2: browsernya WebView2 milik GUI (chromeless di dalam app)
        # - TIDAK ada peluncuran browser eksternal sama sekali. GUI sudah
        # menyiapkan port debug sebelum tombol Start bisa diklik.
        state.BROWSER = {"name": "WebView2", "exe": "", "proc": ""}
        browser_on_port = _check_debug_port()
        if not browser_on_port:
            print("WebView2 dalam app belum siap - tunggu 1-2 detik, "
                  "klik Start lagi.")
            sys.exit(1)
        print(f"Menyambungkan Playwright ke WebView2 dalam app...")
    else:
        _pick_port()
        browser_on_port = _check_debug_port()

    # otomatis pintar: port sudah dipegang browser terpasang -> pakai browser
    # itu langsung (dulu Otomatis selalu Brave -> 'port dipegang browser lain'
    # -> minta izin menutup Chrome/Edge padahal tinggal ditempeli).
    otomatis = not ((state.FORCE_BROWSER or os.environ.get("TYPINGBOT_BROWSER", "")).strip())
    reuse = _browser_from_port_holder() if (otomatis and not wv2) else None
    if reuse is not None:
        state.BROWSER = reuse
        print(f"[OTOMATIS] {reuse['name']} sudah jalan dengan port debug - "
              "dipakai langsung tanpa menutup apa pun.")

    if not wv2 and "Edg" in browser_on_port and reuse is None:
        # Bisa Edge betulan, bisa juga WebView2 milik aplikasi lain (mis.
        # Adobe) yang membalas /json/version dengan string "Edg/...".
        print("Port 9222 dipegang proses berbasis Edge/WebView, "
              "mencari proses pemegangnya...")
        _free_port()
        browser_on_port = _check_debug_port()
        if "Edg" in browser_on_port:
            print("MASIH terkunci. Cek pemegang port: netstat -ano | findstr :9222")
            print("Tutup manual aplikasinya, lalu jalankan ulang program.")
            sys.exit(1)
        print("Port 9222 berhasil dibebaskan.")

    if browser_on_port and reuse is None and not wv2:
        # Port hidup, tapi dipegang browser lain dari pilihan user? (mis.
        # user pilih Chrome sementara jendela debug Brave lama masih nyala
        # atau menggantung) -> tutup pemegangnya (dengan izin) supaya
        # browser pilihan bisa memakai port.
        lain = _port_held_by_other_browser()
        if lain:
            print(f"Port 9222 dipegang browser lain "
                  f"({', '.join(n for _, n in lain)}), padahal pilihan: "
                  f"{(_find_browser() or {}).get('name', '?')}. "
                  "Menutup pemegang port...")
            _free_port(tanya_semua=True)
            browser_on_port = _check_debug_port()
            if browser_on_port:
                print("Pemegang port tidak ditutup - bot tidak bisa lanjut. "
                      "Tutup jendela browser lama, lalu klik Start lagi.")
                sys.exit(1)

    if wv2 and not browser_on_port:
        # tak punya apa pun untuk dibuka: WebView2 mati (app crash/restart)
        print("WebView2 dalam app tidak hidup - buka ulang appnya.")
        sys.exit(1)
    if not browser_on_port:
        if _port_holders():
            print("Port 9222 dipakai proses lain (bukan browser debug)...")
            _free_port()
            browser_on_port = _check_debug_port()
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
            # Chrome/Edge dibuka lewat junction (lihat _profile_dir_arg).
            if state.PROFILE_MODE == "saya" and state.PROFILE_DIR:
                if _browser_running() and not profiles._close_user_browser(
                        state.BROWSER["proc"], nm):
                    ud_saya = ""
                else:
                    ud_saya = profiles._profile_dir_arg(nm)
                if ud_saya:
                    print(f"[PROFIL] membuka {nm} dengan profilmu "
                          f"({state.PROFILE_LABEL or state.PROFILE_DIR})...")
                    _popen_latar(
                        [state.BROWSER["exe"], f"--remote-debugging-port={state.DEBUG_PORT}",
                         f"--user-data-dir={ud_saya}",
                         f"--profile-directory={state.PROFILE_DIR}",
                         "--no-first-run", "--start-minimized"])
                    for _ in range(30):
                        time.sleep(0.5)
                        if state.STOP:
                            sys.exit(0)
                        if _check_debug_port().startswith("Chrome"):
                            break
                    if _check_debug_port().startswith("Chrome"):
                        browser_on_port = _check_debug_port()
                    else:
                        print("[PROFIL] profil kamu gagal dibuka - bot "
                              "memakai profil khusus bot.")
            # Chrome/Edge modern menolak flag debug di profil default
            # (Chromium 136+). Jangan coba-coba (buka jendela tanpa debug
            # lalu tunggu 15 dtk sia-sia): langsung profil khusus bot.
            # Hal yang sama kalau browser sama sudah jalan tanpa debug -
            # profil khusus bisa berjalan berdampingan dengan jendela itu.
            if not browser_on_port:
                langsung_profil = (nm != "Brave") or _browser_running()
                if not langsung_profil:
                    print(f"Port 9222 kosong: membuka {nm} otomatis "
                          "dengan mode debug...")
                    _popen_latar([state.BROWSER["exe"],
                                  f"--remote-debugging-port={state.DEBUG_PORT}",
                                  "--start-minimized"])
                    for _ in range(30):
                        time.sleep(0.5)
                        if state.STOP:
                            sys.exit(0)
                        if _check_debug_port().startswith("Chrome"):
                            break
                    if not _check_debug_port().startswith("Chrome"):
                        langsung_profil = True
                if langsung_profil:
                    # Profil khusus bot: login edclub sekali, tersimpan selamanya.
                    alasan = ("sudah jalan tanpa debug" if _browser_running()
                              else "profil default menolak mode debug")
                    print(f"Membuka {nm} dengan profil khusus bot ({alasan})...")
                    _popen_latar([state.BROWSER["exe"],
                                  f"--remote-debugging-port={state.DEBUG_PORT}",
                                  f"--user-data-dir={state.DEDICATED_PROFILE}",
                                  "--start-minimized"])
                    for _ in range(30):
                        time.sleep(0.5)
                        if state.STOP:
                            sys.exit(0)
                        if _check_debug_port().startswith("Chrome"):
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
                    f"http://{_debug_address()}",
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
    if browser is None and _check_debug_port() and not wv2:
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

    def _hidup(pg, t=2500):
        """Renderer masih menjawab? evaluate/_real_url di renderer yang
        di-suspend Windows MENGHANG TANPA timeout (bug live dua kali:
        bot mati diam saat menyentuh tab lama). wait_for_load_state
        menerima timeout -> gerbang aman sebelum menyentuh tab mana pun."""
        try:
            pg.wait_for_load_state("domcontentloaded", timeout=t)
            return True
        except Exception:
            return False

    page = None
    # Tutup sisa tab Stripe/checkout dari sesi sebelumnya (dibuat saat bot
    # pernah salah klik CTA premium). Tab ini tidak berguna, dan pernah
    # menipu deteksi tab edclub.
    for pg in list(ctx.pages):
        if not _hidup(pg):
            continue
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
        if not _hidup(pg):
            continue
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
        if not _hidup(pg):     # renderer kritis -> lewati
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
        # Kalau tidak ada tab edclub: PAKAI tab kosong yang sudah ada
        # (tab pertama browser baru selalu newtab/blank) daripada membuat
        # tab lagi - live: tab menumpuk dan membebani perangkat lambat,
        # dan membuat tab selalu MENGANGKAT jendela browser walau
        # minimized (keluhan live 2.9.10). Tab start-up kadang mendaftar
        # ke CDP belakangan (scan pertama kosong -> dulu langsung bikin
        # tab baru) - tunggu sebentar sebelum menyerah.
        for _ in range(10):
            for c2 in browser.contexts:
                try:
                    for pg in (c2.pages or []):
                        u = (_real_url(pg) or "").strip().lower()
                        if (not u or u in ("about:blank", "about:newtab")
                                or "newtab" in u
                                or u.startswith(("chrome://", "edge://",
                                                 "brave://"))):
                            page = pg
                            break
                except Exception:
                    continue
                if page is not None:
                    break
            if page is not None:
                break
            time.sleep(0.5)
        if page is None:
            # Tidak ada tab kosong: pakai tab apa saja yang ada (jangan
            # buat tab baru - pasti mengangkat jendela). Profil bot
            # dedikasi, jadi tab yang ada memang tab milik bot.
            for c2 in browser.contexts:
                try:
                    if c2.pages:
                        page = c2.pages[0]
                        break
                except Exception:
                    continue
        # Tab baru dibuat hanya bila browser benar-benar punya nol tab
        # (kasus langka). pernah gagal live: menutup tab Stripe sisa =
        # satu-satunya tab di jendelanya -> Brave membongkar jendela itu
        # -> Target.createTarget gagal sesaat. Solusi: retry + fallback
        # ke context baru.
        for attempt in range(4):
            if page is not None:
                break
            try:
                page = _tab_latar(ctx)
            except Exception as e:
                print(f"Buka tab baru gagal ({attempt + 1}/4): {str(e)[:60]}")
            time.sleep(1.5)
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
    _close_empty_tabs(browser, page)
    # Tab set-UP first-run (Edge/Chrome/Brave baru pertama kali dibuka di
    # profil khusus bot): welcome / pilih default browser / izin cookie /
    # sign-in sync. Dulu bot langsung jalan menimpa set-up (
    # sebaiknya tunggu). Sekarang: instruksi + tunggu sampai semua tab
    # set-up ditutup user, bot lanjut otomatis setelahnya.
    if _find_setup_tab(browser, page) is not None:
        state.WAITING_SETUP = True
        print("[SETUP] Browser baru sedang set-up (welcome / pilih default "
              "browser / cookie). Selesaikan dulu set-upnya di jendela "
              "browser, lalu TUTUP tab set-upnya - bot mulai bekerja "
              "otomatis begitu tab set-up ditutup.")
        while not state.STOP:
            time.sleep(1.0)
            if _find_setup_tab(browser, page) is None:
                break
        state.WAITING_SETUP = False
        if not state.STOP:
            print("[SETUP] Set-up browser selesai - bot mulai bekerja.")
            _close_empty_tabs(browser, page)
    # Anti-popup dipasang di sini (sesi bot): add_init_script utk semua
    # dokumen baru + sekali untuk dokumen yang SUDAH terbuka.
    try:
        page.add_init_script(NO_POPUP_JS)
        page.evaluate(NO_POPUP_JS)
        page.add_init_script(_DUR_FIX_JS)
        page.evaluate(_DUR_FIX_JS)
    except Exception:
        pass
    return pw, browser, page


def connect():
    """Sambungkan ke Brave. HARUS dipanggil dari thread yang sama dengan
    main_loop() - objek Playwright tidak boleh dipakai lintas thread."""
    if state.PAGE is not None:
        return True
    try:
        state.pw, state.browser, state.PAGE = ensure_browser()
    except SystemExit:
        raise
    except Exception as e:
        print(f"Gagal menyambung ke browser: {str(e)[:120]}")
        print("Tutup semua jendela browser, lalu klik Start lagi.")
        sys.exit(1)
    print(f"Terhubung! Tab aktif: {state.PAGE.url}")
    session._install_login_sentinel()
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
    state.NEEDS_LOGIN = False
    state.LOGIN_DICEK = False
    state.BROWSER_CLOSED = False
    state.RANGE_READY = False
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
