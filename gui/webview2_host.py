"""Host WebView2 chromeless di dalam jendela app (v3.2).

Ganti total dari trik SetParent-jendela-browser (v3.0/3.1): sekarang
browser engine-nya sendiri (WebView2, bawaan Windows 10/11) ditanam
sebagai permukaan TANPA UI apa pun - seperti preview browser di app
agent modern. Yang tampak hanya halaman webnya.

Alur:
  - tersedia(): cek pythonnet + pywebview + runtime WebView2 ada.
  - Entry point menjalankan seluruh Tk di CLR thread STA (syarat
    WebView2 - pola yang sama dipakai tkwebview2).
  - buka(port, url): membuat EdgeChrome (pywebview) dengan folder
    profil dedikasi TypingBot, menempel (SetParent) ke frame Tk, dan
    menyalakan remote debugging di port itu.
  - Engine Playwright connect_over_cdp ke port yang sama - engine
    tidak berubah; BROWSER_WV2 membuat ensure_browser melewati semua
    peluncuran browser eksternal.
"""

import ctypes
import ctypes.wintypes as wintypes
import json
import math
import os
import re
import time
import tkinter as tk

user32 = ctypes.windll.user32
GWL_STYLE = -16
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

# Pengarah halaman awal: course/3 tanpa sesi = tampil anon (tombol
# 'Log in' di header) -> lempar ke /signin supaya app terbuka LANGSUNG
# di halaman login (permintaan user). Halaman error edclub ('Oops!
# Something went wrong' - sportal legacy pernah 500 dgn sesi basi)
# dipulihkan ke course/3. Aman utk semua halaman lain: /signin tidak
# disentuh (guard path), domain non-edclub (Google OAuth) tidak
# disentuh, halaman lesson tak punya 'Log in' -> tak ada redirect.
# DIPASANG via pengawas playwright (bukan ExecuteScriptAsync: jalur
# .NET pythonnet terbukti SUNG - script tak pernah jalan, tak error).
_LOGIN_REDIRECT_JS = """
(function(){
  try {
    var p = location.pathname || '';
    if (p.indexOf('signin') >= 0) return;
    if ((location.host || '').indexOf('edclub') < 0) return;
    var t = (document.body && document.body.innerText) || '';
    if (t.indexOf('Something went wrong') >= 0) {
      // pemulih error tidak boleh ikut loop course/3 <-> /signin
      // (breaker sama dgn branch 3a: >3 navigasi dlm 3 menit = diam)
      var nE = parseInt(sessionStorage.getItem('tb_loop') || '0', 10);
      var tE = parseInt(sessionStorage.getItem('tb_loop_t') || '0', 10);
      if (nE > 3 && Date.now() - tE < 180000) return;
      location.href = '/student/course/3';
      return;
    }
    var els = document.querySelectorAll('a,button');
    for (var i = 0; i < els.length; i++) {
      var s = (els[i].textContent || '').trim();
      if (s === 'Log in' && els[i].offsetParent) {
        location.href = '/signin';
        return;
      }
    }
  } catch (e) {}
})();
"""

# Relay token OAuth SEMUANYA DI DALAM HALAMAN (init script). Alur asli
# edclub: callback s.typingclub.com hidup di POPUP dan menyerahkan code
# ke signin via window.opener postMessage. Di mode embedded halaman
# utama yang navigasi (signin -> google -> callback) jadi saat callback
# tiba signin sudah mati - postMessage ke opener=null gagal diam,
# callback menggantung blank/abu-abu selamanya (keluhan live).
#
# edclub cuma butuh {issuer, code, domain} untuk tukar token (state =
# CSRF client-side saja): POST /auth/resolve_oauth_token/ ->
# login_token -> POST /j/auth/refresh-tokens (credentials:include).
# Kedua fetch ini DIJALANKAN DI HALAMAN www.edclub.com (origin yang
# sama dgn SPA, CORS aman - dibuktikan live). Sengaja TIDAK lewat
# evaluate watcher: thread pengawas bisa menggantung/mati di exe
# frozen, sedangkan init script TERBUKTI selalu jalan (stub+redirect
# idup bertahun-tahun).
_RELAY_LANGSUNG_JS = """
async (arg) => {
  const kode = arg.kode, issuer = arg.issuer;
  const r1 = await fetch('https://api.edclub.com/auth/resolve_oauth_token/', {
    method: 'POST', credentials: 'include',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({issuer: issuer, code: kode, domain: 'www'})});
  const j1 = await r1.json().catch(() => ({}));
  const lt = (j1.user && j1.user.login_token)
             || (j1.tpc_users && j1.tpc_users[0] && j1.tpc_users[0].login_token);
  if (!lt) return 'resolve-fail:' + r1.status;
  const r2 = await fetch('https://www.edclub.com/j/auth/refresh-tokens', {
    method: 'POST', credentials: 'include',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({login_token: lt})});
      if (!r2.ok) return 'refresh-fail:' + r2.status;
      try {
        document.cookie = 'tb_lt=' + encodeURIComponent(lt) +
          '; path=/; max-age=31536000; SameSite=Lax';
        document.cookie = 'tb_lt_gagal=; path=/; max-age=0';
      } catch (e) {}
      try { localStorage.setItem('tb_lt', lt); } catch (e) {}
  return 'ok';
}
"""

_OAUTH_RELAY_PAGE_JS = """
(function(){
  try {
    var h = location.host || '';
    var p = location.pathname || '';
    // 1) halaman callback: bawa code pulang lewat query /signin.
    //    Google kadang mengirim code di QUERY, kadang di FRAGMENT
    //    (#code=...) - parse keduanya (dulu cuma search: halaman
    //    terdampar selamanya saat code ada di fragment, live terbukti).
    if (h.indexOf('typingclub') >= 0 && p.indexOf('auth_callback') >= 0) {
      var q = new URLSearchParams(location.search);
      var fh = new URLSearchParams((location.hash || '').slice(1));
      var galat = q.get('error') || fh.get('error') || '';
      var kode = q.get('code') || fh.get('code') || '';
      var issx = q.get('iss') || fh.get('iss') || '';
      if (galat) { location.replace('https://www.edclub.com/signin'); return; }
      if (kode) {
        location.replace('https://www.edclub.com/signin?oauth_relay=' +
                         encodeURIComponent(kode) + '&iss=' +
                         encodeURIComponent(issx));
      }
      return;
    }
    // 2) halaman edclub membawa oauth_relay: tukar token dari dalam
    //    halaman, lalu masuk ke daftar level.
    if (h.indexOf('edclub') < 0) return;
    var q2 = new URLSearchParams(location.search);
    var rc = q2.get('oauth_relay') || '';
    // DULU: if (!rc) return;  <- MEMATIKAN SELURUH SCRIPT: branch 3
    // (tukar-ulang tiket di /signin) TAK PERNAH TERJANGKAU di boot
    // normal (tanpa param) - login bertahan tak pernah jalan. Sekarang
    // bungkus pertukaran relay dalam if(rc), eksekusi lanjut ke bawah.
    if (rc) {
    try { history.replaceState(null, '', location.pathname); } catch (e) {}
    var issuers = ['google', 'clever', 'office365'];
    var api = 'https://api.edclub.com';
    var opt = {method: 'POST', credentials: 'include',
               headers: {'Content-Type': 'application/json'}};
    (async () => {
      for (var i = 0; i < issuers.length; i++) {
        try {
          var r = await fetch(api + '/auth/resolve_oauth_token/',
            Object.assign({}, opt, {body: JSON.stringify(
              {issuer: issuers[i], code: rc, domain: 'www'})}));
          if (!r.ok) continue;
          var d = await r.json();
          var k = [];
          if (d && d.user) k.push(d.user);
          if (d && d.tpc_users) k.push(...d.tpc_users);
          var tok = null;
          for (var j = 0; j < k.length; j++)
            if (k[j] && k[j].login_token) { tok = k[j].login_token; break; }
          if (!tok) break;
          // simpan login_token: tiket tukar-token ini yang bikin sesi
          // hidup (cookie rt saja TIDAK cukup - boot dengan rt tetap
          // anon, terbukti live). SIMPAN SEBAGAI KUKI: localStorage
          // dibersihkan SPA saat boot anon (live: tb_lt lenyap ->
          // branch 3 fetch 422 null), kuki tidak ikut dibersihkan.
          try {
            document.cookie = 'tb_lt=' + encodeURIComponent(tok) +
              '; path=/; max-age=31536000; SameSite=Lax';
            document.cookie = 'tb_lt_gagal=; path=/; max-age=0';
          } catch (e) {}
          try { localStorage.setItem('tb_lt', tok); } catch (e) {}
          var r2 = await fetch(api + '/j/auth/refresh-tokens',
            Object.assign({}, opt, {body: JSON.stringify({login_token: tok})}));
          if (r2.ok) {
            location.replace('https://www.edclub.com/student/course/3');
            return;
          }
        } catch (e) {}
      }
      location.replace('https://www.edclub.com/signin');
    })();
    }
  } catch (e) {}
  // 3) boot berikutnya dgn login_token tersimpan: halaman /signin +
  //    token ada = sesi kemarin masih bisa ditukar -> masuk sendiri
  //    tanpa Google lagi (kuki rt saja tak bertahan boot, terbukti).
  try {
    function bacaKuki(nama) {
      var m = document.cookie.match(
        new RegExp('(?:^|; )' + nama + '=([^;]*)'));
      return m ? decodeURIComponent(m[1]) : null;
    }
    var lt0 = bacaKuki('tb_lt') || localStorage.getItem('tb_lt');
    var gagal0 = parseInt(bacaKuki('tb_lt_gagal')
      || localStorage.getItem('tb_lt_gagal') || '0', 10);
    // 3a) RE-LOGIN DENGAN KUKI RT (panggilan yang SAMA dengan boot SPA:
    // {domain:'www'} credentials:include - server baca kuki rt).
    // Balas 200 = sesi masih sah -> masuk tanpa Google. DUA JALUR:
    // (a) dokumen dimuat langsung di /signin (hard load), dan (b) SPA
    // berpindah rute ke /signin TANPA muat ulang dokumen (bounce anon
    // setelah boot - live 11:52: init script jalan di course/3, SPA
    // pindah rute client-side, setTimeout lama tidak pernah pecah).
    // Karena itu: interval 3 dtk yang membaca path SETIAP tick, max
    // 8 percobaan, counter reset saat path keluar /signin. Percobaan
    // pertama beri jeda 2 dtk supaya watcher kebagian memulihkan kuki
    // (dulu 401 karena boot SPA mendahului pemulihan kuki).
    if (h.indexOf('edclub') >= 0) {
      var coba3 = 0;
      // breaker antar-dokumen: navigasi auto dibatasi 3x / 3 menit
      // (sessionStorage ikut hidup lintas navigasi dalam satu tab)
      function penuh() {
        var n = parseInt(sessionStorage.getItem('tb_loop') || '0', 10);
        var t0 = parseInt(sessionStorage.getItem('tb_loop_t') || '0', 10);
        if (Date.now() - t0 > 180000) n = 0;
        n += 1;
        sessionStorage.setItem('tb_loop', String(n));
        sessionStorage.setItem('tb_loop_t', String(Date.now()));
        return n > 3;
      }
      var cek = function () {
        var ph = location.host || '';
        var pp = location.pathname || '';
        if (ph.indexOf('edclub') < 0) return;
        if (pp.indexOf('/signin') < 0) { coba3 = 0; return; }
        if (coba3 >= 8) return;
        coba3 += 1;
        if (!/sign in with|log in|sign up/i.test(
            (document.body.innerText || ''))) return;   // sudah login
        fetch('https://api.edclub.com/j/auth/refresh-tokens',
          {method: 'POST', credentials: 'include',
           headers: {'Content-Type': 'application/json'},
           body: JSON.stringify({domain: 'www'})})
          .then(function (r) {
            return r.text().then(function (t) {
              // LIVE BUG 20:10: 200 dgn bodi '[]' = rotasi ANONIM
              // tanpa sesi. Dulu 200 apa pun langsung navigasi ->
              // bounce course/3 <-> /signin tanpa ujung (kuki rt
              // muter tiap lewat, watcher sempat menyimpannya).
              var sah = r.ok && t && t !== '[]' && t.length > 10;
              if (!sah) {
                // rt basi (403/401 ATAU 200 anon) -> coba tiket lt
                if (lt0 && Date.now() - gagal0 > 12 * 3600 * 1000) {
                  return fetch(
                    'https://api.edclub.com/j/auth/refresh-tokens',
                    {method: 'POST', credentials: 'include',
                     headers: {'Content-Type': 'application/json'},
                     body: JSON.stringify({login_token: lt0})})
                    .then(function (r2) {
                      return r2.text().then(function (t2) {
                        var sah2 = r2.ok && t2 && t2 !== '[]' &&
                          t2.length > 10;
                        if (sah2 && !penuh()) {
                          location.replace(
                            'https://www.edclub.com/student/course/3');
                        } else if (!sah2) {
                          document.cookie = 'tb_lt_gagal=' +
                            Date.now() +
                            '; path=/; max-age=43200; SameSite=Lax';
                        }
                      });
                    });
                }
                return;   // sesi memang mati: diam di signin (manual)
              }
              if (penuh()) return;   // breaker: jangan ikut loop
              location.replace(
                'https://www.edclub.com/student/course/3');
            });
          })
          .catch(function () {});
      };
      setTimeout(cek, 2000);
      setInterval(cek, 3000);
    }
  } catch (e) {}
})();
"""

# Suntikan per-dokumen: window.open dipanggil edclub dgn URL KOSONG
# (('', '_blank', ...)) lalu kode edclub set win.location.href = url
# google - kalau open() mengembalikan null muncul error 'allow pop-ups'.
# Kembalikan stub yang siap di-set location-nya; semua penugasan lokasi
# = navigasi HALAMAN UTAMA (OAuth full-page di dalam app, tanpa jendela
# kedua dgn address bar & tombol close, dan keyboard tetap hidup).
# href getter harus mengembalikan URL yang BARU di-assign (bukan
# about:blank terus): halaman signin edclub punya watchdog ~5 dtk -
# win.location.href yang tak pernah berubah = "popup mati" -> halaman
# utama dilempar ke sportal/program-3.game (keluhan live: pencet login
# balik lagi ke halaman awal). Real popup asli: baca href lintas-origin
# = THROW (dianggap sehat); stub kita "sehat" = href berubah.
_NO_POPUP_JS = """
(function(){
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


def tersedia():
    """Runtime lengkap ada? Import berat dilakukan di sini (lambat),
    BUKAN saat modul dimuat - supaya test suite & mesin tanpa WebView2
    tetap aman memakai jalur browser eksternal lama."""
    try:
        import clr
        try:
            from System.Threading import Thread as _T
            print(f"[WEBVIEW2] thread UI: "
                  f"{_T.CurrentThread.GetApartmentState()}")
        except Exception:
            pass
        try:
            # build beku (PyInstaller): probing GAC tidak sama seperti dev -
            # muat eksplisit per strong name supaya namespace terlihat
            from System.Reflection import Assembly
            for _nm in ("System.Windows.Forms, Version=4.0.0.0, "
                        "Culture=neutral, PublicKeyToken=b77a5c561934e089",
                        "System.Drawing, Version=4.0.0.0, "
                        "Culture=neutral, PublicKeyToken=b03f5f7f11d50a3a"):
                try:
                    Assembly.Load(_nm)
                except Exception:
                    pass
            clr.AddReference("System.Windows.Forms")
            clr.AddReference("System.Drawing")
        except Exception:
            pass
        from System.Windows.Forms import Control  # noqa: F401
        from webview.platforms.edgechromium import EdgeChrome  # noqa: F401
        return True
    except Exception as ex:
        print(f"[WEBVIEW2] tidak tersedia ({str(ex)[:80]}) - pakai "
              "browser eksternal.")
        return False


COURSE_URL = "https://www.edclub.com/student/course/3"


def _rute_lama(u):
    """True = URL halaman daftar/home TAMPILAN LAMA edclub (bukan
    lesson .play, bukan UI baru /student/). Keluhan user: menu hamburger
    / logo kadang menjebak ke tampilan lama penuh iklan - pengawas
    membawa balik ke daftar level baru otomatis."""
    try:
        from urllib.parse import urlparse
        p = (urlparse(u).path or "/").lower()
    except Exception:
        return False
    if ".play" in p or "/student/" in p:
        return False     # lesson & UI baru: biarkan
    if "auth_callback" in u or "signin" in u:
        return False     # alur login: jangan sentuh
    if p in ("", "/"):
        return True
    return (p.startswith("/sportal") or p.startswith("/typing-jungle")
            or p.startswith("/library"))


def _sesi_path():
    """File cookie sesi edclub: satu folder dgn bot.log (otomatis
    ikut %LOCALAPPDATA%/TypingBot di exe frozen)."""
    try:
        from .theme import LOG_FILE
        return os.path.join(os.path.dirname(LOG_FILE), "sesi_edclub.json")
    except Exception:
        return os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "sesi_edclub.json")


def _sesi_muat():
    """Cookie sesi edclub tersimpan; None kalau tidak ada / basi."""
    pth = _sesi_path()
    if not pth:
        return None
    try:
        with open(pth, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and d.get("cookies") \
                and time.time() - d.get("t", 0) < 60 * 86400:
            return d["cookies"]
    except Exception:
        pass
    return None


def _sesi_tulis(cookies):
    pth = _sesi_path()
    if not pth:
        return
    try:
        with open(pth, "w", encoding="utf-8") as f:
            json.dump({"t": time.time(), "cookies": cookies}, f)
    except Exception:
        pass


# ----------------------------------------------------- simpanan akun
# Ganti akun (permintaan user 11 Nov 2026): daftar sesi edclub yang
# tersimpan di folder akun/ - pilih satu = cookie-nya dipasang ke
# webview. Sesi AKTIF tetap sesi_edclub.json (restorasi boot tidak
# berubah); folder ini hanya buku alamat akun.

def _dir_akun():
    """Folder buku alamat akun (satu folder dgn bot.log - otomatis ikut
    %LOCALAPPDATA%/TypingBot, dan TypingBot-SIM saat sandbox)."""
    try:
        from .theme import LOG_FILE
        return os.path.join(os.path.dirname(LOG_FILE), "akun")
    except Exception:
        return os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "akun")


def daftar_akun():
    """[{nama, waktu}] akun tersimpan, urut abjad."""
    d = _dir_akun()
    out = []
    try:
        for f in sorted(os.listdir(d)):
            if not f.endswith(".json") or f == "aktif.json":
                continue
            try:
                with open(os.path.join(d, f), encoding="utf-8") as fh:
                    meta = json.load(fh)
                out.append({"nama": meta.get("nama") or f[:-5],
                            "waktu": meta.get("waktu", 0)})
            except Exception:
                continue
    except Exception:
        pass
    out.sort(key=lambda a: a["nama"].lower())
    return out


def akun_aktif_nama():
    try:
        with open(os.path.join(_dir_akun(), "aktif.json"),
                  encoding="utf-8") as f:
            return (json.load(f) or {}).get("nama")
    except Exception:
        return None


def _akun_aktif_set(nama):
    try:
        os.makedirs(_dir_akun(), exist_ok=True)
        with open(os.path.join(_dir_akun(), "aktif.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"nama": nama}, f)
    except Exception:
        pass


def simpan_akun(nama=None, cookies=None):
    """Daftarkan sesi sebagai akun tersimpan. Default = sesi AKTIF +
    nama otomatis 'Akun N'. Return nama terpakai, None kalau tak ada sesi."""
    c = cookies or _sesi_muat()
    if not c:
        return None
    d = _dir_akun()
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        return None
    if not nama:
        n = 1
        while os.path.exists(os.path.join(d, f"akun-{n}.json")):
            n += 1
        nama = f"Akun {n}"
    aman = "".join(ch for ch in nama
                   if ch.isalnum() or ch in " -_.").strip() or "akun"
    try:
        with open(os.path.join(d, f"akun-{aman}.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"nama": nama, "waktu": time.time(), "cookies": c}, f)
    except Exception:
        return None
    _akun_aktif_set(nama)
    return nama


def hapus_akun(nama):
    """Buang akun tersimpan (berdasarkan nama di meta). Return bool."""
    d = _dir_akun()
    try:
        for f in os.listdir(d):
            if not f.endswith(".json") or f == "aktif.json":
                continue
            try:
                with open(os.path.join(d, f), encoding="utf-8") as fh:
                    meta = json.load(fh)
            except Exception:
                continue
            if meta.get("nama") == nama:
                os.remove(os.path.join(d, f))
                return True
    except Exception:
        pass
    return False


def akun_auto_simpan(nama, cookies):
    """Simpan OTOMATIS saat login (permintaan user: 'when we're logged
    in, it should automatically save it'): nama = nama profil edclub.
    Akun baru = dibuat; akun yang sudah ada = cookie-nya disegarkan bila
    file lebih tua 30 menit (sesi simpanan tetap hidup utk ganti akun).
    Selalu set aktif. Thread pengawas aman (file saja)."""
    d = _dir_akun()
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        return False
    aman = "".join(ch for ch in nama
                   if ch.isalnum() or ch in " -_.").strip() or "akun"
    pth = os.path.join(d, f"akun-{aman}.json")
    try:
        lama = 0.0
        if os.path.exists(pth):
            with open(pth, encoding="utf-8") as f:
                lama = json.load(f).get("waktu", 0)
        if time.time() - lama > 1800:
            with open(pth, "w", encoding="utf-8") as f:
                json.dump({"nama": nama, "waktu": time.time(),
                           "cookies": cookies}, f)
        _akun_aktif_set(nama)
        return True
    except Exception:
        return False


def _akun_cookies(nama):
    d = _dir_akun()
    try:
        for f in os.listdir(d):
            if not f.endswith(".json") or f == "aktif.json":
                continue
            try:
                with open(os.path.join(d, f), encoding="utf-8") as fh:
                    meta = json.load(fh)
            except Exception:
                continue
            if meta.get("nama") == nama:
                return meta.get("cookies") or []
    except Exception:
        pass
    return None


def jalankan_sta(main_fn):
    """Jalankan main_fn (seluruh app Tk) di CLR thread STA.

    Dipanggil dari entry point. Kalau pythonnet tidak ada (build lama /
    lingkungan tanpa dependensi), main_fn jalan di thread utama seperti
    biasa - jalur WebView2 memang dinonaktifkan."""
    try:
        from System.Threading import Thread, ThreadStart, ApartmentState
    except Exception as ex:
        try:
            from .theme import LOG_FILE
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[WEBVIEW2] STA tidak tersedia: {str(ex)[:120]}\n")
        except Exception:
            pass
        main_fn()
        return
    t = Thread(ThreadStart(main_fn))
    t.ApartmentState = ApartmentState.STA
    t.Start()
    t.Join()


class Wv2Host(tk.Frame):
    """Frame Tk yang menjadi permukaan halaman web (WebView2)."""

    def __init__(self, master, profil_dir, bg="#101116", edge="#2a2c33",
                 **kw):
        super().__init__(master, bg=bg, highlightthickness=1,
                         highlightbackground=edge, **kw)
        self._profil = profil_dir
        self._ec = None          # EdgeChrome (pywebview)
        self._chwnd = None       # hwnd kontrol WinForms
        self._on_ready = None
        self._jaga_job = None
        self._popup_unsub = False
        self._blank_ct = {}     # popup about:blank -> hitung siklus utk WM_CLOSE
        self._pw_stop = None    # pengawas playwright (mulai_pengawas)
        self._pw_thread = None
        # overlay placeholder (tampil sebelum halaman siap)
        self._overlay = tk.Frame(self, bg=bg)
        self._overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._stage_widget = None    # kartu status (set_overlay)
        self._boot_anim_job = None   # job after spinner tutup boot
        self._nav_pending = None     # navigasi diminta thread lain
        self._bounce_lama = 0.0      # cooldown bounce rute lama
        self._dialog_aktif = False   # dialog dalam-app sedang menempati area
        self.bind("<Configure>", self._on_resize)

    # ------------------------------------------------------------- API
    def webview_hidup(self):
        """True kalau kontrol WebView2 native sudah ada (untuk memilih
        dialog dalam-app vs jendela terpisah)."""
        return bool(self._chwnd)

    def lepas_untuk_dialog(self):
        """Siapkan area untuk dialog DALAM APP. WebView2 = HWND native:
        widget Tk tidak bisa menembus ke atasnya (airspace), jadi selagi
        dialog tampil kontrolnya DISEMBUNYIKAN sebentar - halaman, sesi
        login & posisi scroll tetap hidup, begitu dialog tertutup
        webview muncul lagi persis seperti semula."""
        self._dialog_aktif = True
        if self._chwnd:
            try:
                user32.ShowWindow(self._chwnd, 0)   # SW_HIDE
            except Exception:
                pass
        self._overlay.place(relx=0, rely=0, relwidth=1, relheight=1)

    def pasang_setelah_dialog(self):
        """Kembalikan webview setelah dialog dalam-app selesai."""
        self._overlay.place_forget()
        self._dialog_aktif = False
        if self._chwnd:
            try:
                # SW_SHOWNA: tampil TANPA mencuri fokus dari user
                user32.ShowWindow(self._chwnd, 8)
            except Exception:
                pass
            self.after_idle(self._pas_ukuran)

    # ----------------------------------------------- ganti akun edclub
    @staticmethod
    def _cdp_cookie(kerja_cookie):
        """Koneksi CDP pendek utk operasi cookie (clear/add) di thread
        apa pun. Return (ok, pesan). Port = estate.DEBUG_PORT (webview
        dinyalakan dgn port itu - lihat App saat boot)."""
        try:
            from engine import state as estate
            port = estate.DEBUG_PORT
        except Exception:
            port = 9222
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                br = p.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{port}", timeout=15000)
                try:
                    for ctx in br.contexts:
                        kerja_cookie(ctx)
                finally:
                    br.close()
            return True, "ok"
        except Exception as ex:
            return False, str(ex)[:150]

    def akun_ganti(self, nama, selesai=None):
        """Pasang sesi akun 'nama' ke webview (hapus cookie lama -> add
        cookie akun -> tulis sesi aktif). Thread belakang; selesai(ok,
        pesan) dipanggil dari thread itu - pemanggil yang marshal ke UI
        (pola _ui_queue)."""
        def kerja():
            cookies = _akun_cookies(nama)
            if not cookies:
                if selesai:
                    selesai(False, "akun tidak ditemukan")
                return
            ok, pesan = self._cdp_cookie(lambda ctx: (
                ctx.clear_cookies(), ctx.add_cookies(cookies)))
            if ok:
                _sesi_tulis(cookies)
                _akun_aktif_set(nama)
                self._akun_swap_at = time.time()
                pesan = "sesi dimuat"
            if selesai:
                selesai(ok, pesan)
        import threading as _th
        _th.Thread(target=kerja, daemon=True).start()

    def akun_keluar(self, selesai=None):
        """Keluar bersih utk TAMBAH akun: hapus semua cookie webview +
        file sesi aktif (biar boot tak restore akun lama). Thread belakang."""
        def kerja():
            ok, pesan = self._cdp_cookie(lambda ctx: ctx.clear_cookies())
            if ok:
                try:
                    os.remove(_sesi_path())
                except Exception:
                    pass
                try:
                    os.remove(os.path.join(_dir_akun(), "aktif.json"))
                except Exception:
                    pass
                self._akun_swap_at = time.time()
                pesan = "sesi dibersihkan"
            if selesai:
                selesai(ok, pesan)
        import threading as _th
        _th.Thread(target=kerja, daemon=True).start()

    # --------------------------------------------------- pengawas halaman
    def mulai_pengawas(self, port):
        """Thread pengawas (playwright murni-python): pasang NO_POPUP_JS +
        _LOGIN_REDIRECT_JS utk SEMUA dokumen, dan tiap ~2 dtk evaluasi
        pengarah halaman (anon -> /signin, error -> course/3).

        INI SATU-SATUNYA jalur suntikan yang TERBUKTI jalan: add_init
        script/evaluate via playwright sudah diverifikasi live, sedangkan
        AddScript/ExecuteScriptAsync pythonnet SUNG (script tak pernah
        jalan, tak pernah raise - dulu OAuth cuma hidup selagi sesi bot,
        klik Google app-idle memunculkan popup sungguhan)."""
        import threading
        self._pw_stop = threading.Event()
        self._pw_thread = threading.Thread(
            target=self._pengawas, args=(port,), daemon=True)
        self._pw_thread.start()

    def hentikan_pengawas(self):
        try:
            self._pw_stop.set()
        except Exception:
            pass

    def _pengawas(self, port):
        """SUPERVISOR pengawas: nyalakan thread pelaksana (runner) yg
        memiliki koneksi playwright, awasi detak jantungnya. evaluate
        playwright TIDAK PUNYA timeout - renderer macet/sibuk (halaman
        google berat, callback COOP) bisa menggantungkan runner
        SELAMANYA: dulu seluruh pengawas mati diam tanpa log & relay
        OAuth tak pernah jalan (live). Sekarang: runner gantung ->
        ditinggal (daemon), koneksi baru dibuat di thread segar; state
        relay (kode dsb.) dipertahankan."""
        import threading
        stop = self._pw_stop
        while not stop.is_set():
            jantung = [time.time()]
            selesai = threading.Event()

            def jalankan():
                try:
                    self._pengawas_loop(port, stop, jantung)
                except Exception as ex:
                    if not stop.is_set():
                        try:
                            from .theme import LOG_FILE
                            with open(LOG_FILE, "a", encoding="utf-8") as f:
                                f.write(f"[WEBVIEW2] pengawas putus: {ex!r}"[:120]
                                        + "\n")
                        except Exception:
                            pass
                selesai.set()

            th = threading.Thread(target=jalankan, daemon=True)
            th.start()
            # tunggu runner selesai; kalau detak jantung berhenti >15 dtk
            # = runner menggantung di evaluate -> abaikan & sambung ulang
            while not stop.is_set() and not selesai.wait(2.0):
                if time.time() - jantung[0] > 15.0:
                    try:
                        from .theme import LOG_FILE
                        with open(LOG_FILE, "a", encoding="utf-8") as f:
                            f.write("[WEBVIEW2] pengawas menggantung - "
                                    "sambung ulang koneksi baru...\n")
                    except Exception:
                        pass
                    break
            if not selesai.wait(5.0):
                pass        # runner lama ditinggal (daemon thread)
            time.sleep(1.0)

    def _pengawas_loop(self, port, stop, jantung):
        def catat(pesan):
            """Langsung ke bot.log (mode append, tutup langsung): print
            stdout bisa tak sampai ke log karena launch.py memotong file
            dgn 'w' sementara engine membuka pegangan kedua - hidup-mati
            watcher HARUS terlihat di log untuk diagnosa."""
            try:
                from .theme import LOG_FILE
                with open(LOG_FILE, "a", encoding="utf-8") as f:
                    f.write("[WEBVIEW2] " + pesan + "\n")
            except Exception:
                pass

        try:
            from playwright.sync_api import sync_playwright
            from engine.browser import NO_POPUP_JS, _DUR_FIX_JS
        except Exception as ex:
            catat(f"pengawas gagal import: {ex!r}")
            return
        pw = None
        try:
            pw = sync_playwright().start()
            # tunggu CDP webview hidup (buka() baru saja selesai)
            browser = None
            for _ in range(60):
                if stop.is_set():
                    return
                try:
                    browser = pw.chromium.connect_over_cdp(
                        f"http://localhost:{port}")
                    break
                except Exception:
                    time.sleep(0.5)
            if browser is None:
                catat("pengawas: CDP tak tersambung")
                return
            # init script utk SEMUA dokumen mendatang (stub window.open,
            # pengarah /signin, dan relay OAuth - semua di dalam halaman,
            # tahan banting: jalan walau thread pengawas hang/mati)
            for ctx in browser.contexts:
                try:
                    ctx.add_init_script(NO_POPUP_JS)
                    ctx.add_init_script(_DUR_FIX_JS)
                    ctx.add_init_script(_LOGIN_REDIRECT_JS)
                    ctx.add_init_script(_OAUTH_RELAY_PAGE_JS)
                except Exception:
                    pass
            wrap = "() => {" + _LOGIN_REDIRECT_JS + "}"
            url_terakhir = ""
            callback_sejak = {}      # code callback -> waktu pertama terlihat
            kode_coba = set()        # code yang sudah dicoba relai manual
            eval_gagal = 0
            kosong = 0
            jantung[0] = time.time()
            catat("pengawas tersambung - init script terpasang")
            # ---- PULIHKAN SESI LOGIN: cookie edclub dari sesi lalu.
            # edclub menandai cookie login (rt dll.) sebagai COOKIE SESI
            # - WebView2 membuangnya tiap app keluar = login Google
            # berulang tiap buka app (keluhan user). Pasang balik
            # sebagai cookie PERSISTEN lalu boot ulang halaman: SPA
            # membaca cookie saat boot = langsung login, persis hasil
            # relay OAuth. Sesi berbasis cookie terbukti dari bundle
            # SPA: semua fetch API pakai credentials:"include" dgn
            # auth() kosong.
            # PENTING: koneksi CDP-nya harus level HALAMAN - sesi
            # browser-level Storage.getCookies membaca konteks DEFAULT
            # yang KOSONG saat connect_over_cdp (cookie webview tak
            # kelihatan - sesi page-level terbukti melihat rt dll.).
            perlu_boot = False
            sesi_sid = None

            def _cdp_dapat():
                try:
                    for c in browser.contexts:
                        if c.pages:
                            s = c.new_cdp_session(c.pages[0])
                            s.send("Network.enable")
                            return s
                except Exception:
                    pass
                return None

            cdp = _cdp_dapat()
            if cdp is None and not stop.is_set():
                # halaman webview kadang baru terdaftar - tunggu sebentar
                for _ in range(20):
                    if stop.is_set():
                        break
                    time.sleep(0.5)
                    cdp = _cdp_dapat()
                    if cdp is not None:
                        break
            tersimpan = _sesi_muat()
            if cdp is None and tersimpan:
                catat("pulihkan sesi DILEWATI - koneksi CDP tak siap")
            if cdp is not None and tersimpan:
                try:
                    kini = time.time()
                    for c in tersimpan:
                        q = {"name": c["name"], "value": c["value"],
                             "domain": c["domain"],
                             "path": c.get("path", "/"),
                             "secure": bool(c.get("secure", True)),
                             "httpOnly": bool(c.get("httpOnly", True)),
                             "expires": kini + 180 * 86400}
                        if c.get("sameSite"):
                            q["sameSite"] = c["sameSite"]
                        cdp.send("Network.setCookie", q)
                    perlu_boot = True
                    catat(f"sesi edclub dipulihkan ({len(tersimpan)} "
                          "cookie)")
                except Exception as ex:
                    catat(f"pulihkan sesi gagal: {ex!r}"[:100])
            while not stop.is_set():
                selesai_loop = time.time() + 2.0
                while not stop.is_set() and time.time() < selesai_loop:
                    time.sleep(0.25)
                jantung[0] = time.time()
                # ---- TANGKAP SESI: cookie login berotasi (rt ganti
                # tiap refresh) - simpan tiap berubah supaya app
                # BERIKUTNYA bisa login sendiri.
                if cdp is None:
                    cdp = _cdp_dapat()      # sambungan lama putus -> baru
                if cdp is not None:
                    try:
                        ck = cdp.send("Network.getCookies").get(
                            "cookies", [])
                        milik = [c for c in ck
                                 if ("edclub" in c.get("domain", "")
                                     or "typingclub" in c.get("domain", ""))
                                 and not c.get("name", "")
                                 .startswith("__cf")]
                        sid = sorted((c["name"], c["value"])
                                     for c in milik)
                        # rotasi anon terjadi DI /signin (bounce) -
                        # jangan menimpa sesi tersimpan dgn kuki sampah
                        if sid and sid != sesi_sid \
                                and "/signin" not in (url_terakhir
                                                      or ""):
                            sesi_sid = sid
                            _sesi_tulis(milik)
                            catat(f"sesi edclub tersimpan "
                                  f"({len(milik)} cookie)")
                    except Exception:
                        # sesi halaman bisa mati (target ditutup) - coba
                        # buat koneksi baru di putaran berikutnya
                        cdp = None
                try:
                    pages = [p for c in browser.contexts for p in c.pages]
                except Exception:
                    pages = []
                if not pages:
                    # dulu diam: koneksi playwright bisa mati setengah
                    # (malam/r tidur, devtools webview restart) -> daftar
                    # halaman kosong selamanya, tanpa error = zombi. Sisi
                    # jembol: putus & sambung ulang (init script + rescue
                    # otomatis ikut terpasang ulang).
                    kosong += 1
                    if kosong in (5, 15):
                        catat(f"daftar halaman kosong ({kosong} putaran) - "
                              "koneksi mungkin mati")
                    if kosong >= 15:
                        catat("pengawas: koneksi mati (halaman tak terlihat)"
                              " - putus & sambung ulang")
                        return
                    continue
                kosong = 0
                for pg in pages:
                    if stop.is_set():
                        break
                    try:
                        u = pg.evaluate("() => location.href")
                    except Exception as ex:
                        # dulu except->continue diam: watcher jadi ZOMBI
                        # (eval gagal terus tanpa log & tanpa detak hang)
                        eval_gagal += 1
                        if eval_gagal in (1, 5, 20):
                            catat(f"eval halaman gagal ({eval_gagal}): "
                                  f"{repr(ex)[:60]}")
                        if eval_gagal >= 5:
                            catat("pengawas: sambungan macet - putus & "
                                  "sambung ulang koneksi baru")
                            return      # supervisor buat runner baru
                        continue
                    eval_gagal = 0
                    jantung[0] = time.time()
                    # ---- cover tahan-halaman: target tercapai / habis?
                    tahan = getattr(self, "_tahan", None)
                    if tahan:
                        pot, batas = tahan
                        if (pot in u) or (time.time() > batas):
                            self._tahan = None
                            self._boot_selesai = True
                            self._boot_cover = None
                    # ---- permintaan supervisor: cover utk pindah rute
                    # .play klasik (state.TAHAN_NAV diset sebelum goto)
                    try:
                        from engine import state as _est
                        tnav = getattr(_est, "TAHAN_NAV", None)
                        if tnav:
                            setattr(_est, "TAHAN_NAV", None)
                            self.tahan_halaman(tnav, 10.0)
                    except Exception:
                        pass
                    # ---- indikator login (permintaan user): sesi habis =
                    # halaman dilempar ke /signin / anon / lagi di Google.
                    # DEBOUNCE: boot bounce course<->signin bikin 'Login
                    # ulang' kedip sekali (keluhan user) - baru dianggap
                    # sungguhan setelah 3x berturut (~6 dtk).
                    perlu_raw = (("edclub" not in u)
                                 or ("/signin" in u)
                                 or ("accounts.google." in u))
                    self._login_streak = (getattr(self, "_login_streak", 0)
                                          + 1) if perlu_raw else 0
                    # transisi login selesai (True->False) = tahan halaman
                    # sampai daftar level login betul2 tampil - dulu user
                    # melihat kedipan /signin lagi lalu daftar level
                    if (not perlu_raw
                            and getattr(self, "_perlu_raw_lama", False)):
                        self.tahan_halaman("/student/", 12.0)
                    # halaman login di tengah proses OAuth (relay/
                    # auth_callback) = TRANSIEN - user melihat kedipan
                    # signin setelah login (keluhan user Nov 2026).
                    # Cover sampai /student/ benar2 mendarat. TAPI: user
                    # sedang aktif meng-klik halaman = jangan tutup
                    # (permintaan user: halaman salah tak boleh terlihat,
                    # tapi input user lebih penting).
                    if perlu_raw and ("oauth" in u or "relay" in u
                                      or "auth_callback" in u):
                        ua = self._user_aktif_pg(pg)
                        if ua is None or ua >= 5.0:
                            self.tahan_halaman("/student/", 15.0)
                    self._perlu_raw_lama = perlu_raw
                    self._perlu_login = perlu_raw and \
                        self._login_streak >= 3
                    # ---- AUTO-SIMPAN AKUN: nama profil edclub dipakai
                    # sbg identitas akun (permintaan user: 'recognise the
                    # name from the edclub profile'). Halaman student
                    # login + pill profil ada = simpan/refresh akun.
                    if not perlu_raw and "/student/" in u:
                        try:
                            nm = pg.evaluate(
                                """() => {
                                  const el = document.querySelector(
                                    'button [class*="truncate"]');
                                  return el ?
                                    (el.textContent || '').trim() : '';
                                }""")
                        except Exception:
                            nm = ""
                        if nm and len(nm) <= 40:
                            if nm != getattr(self, "_nama_profil", None):
                                self._nama_profil = nm
                            # JANGAN simpan di detik pertama setelah tukar
                            # akun: listener sesi belum menulis cookie akun
                            # baru -> cookie LAMA bisa tertulis atas nama
                            # akun baru (racun buku alamat).
                            if time.time() - getattr(
                                    self, "_akun_swap_at", 0.0) < 20:
                                continue
                            try:
                                cookies = json.load(open(
                                    _sesi_path(), encoding="utf-8"
                                    )).get("cookies") or []
                            except Exception:
                                cookies = []
                            if cookies:
                                akun_auto_simpan(nm, cookies)
                    nav = getattr(self, "_nav_pending", None)
                    if nav:
                        self._nav_pending = None
                        if "edclub" in u:
                            try:
                                pg.evaluate(
                                    "() => location.href = %r" % nav)
                                catat(f"arahkan: {nav[:80]}")
                            except Exception:
                                pass
                            continue
                    if u != url_terakhir:
                        url_terakhir = u
                        catat(f"halaman: {u[:100]}")
                    if getattr(self, "_boot_cover", None):
                        # tutup boot aktif: buka begitu daftar level
                        # tampil SUDAH LOGIN (pill profil ada), atau
                        # tunggu maksimal 45 dtk (sesi mati -> login
                        # manual seperti biasa)
                        selesai = False
                        try:
                            if "/student/" in u:
                                ada = pg.evaluate("""() => {
                                  const el = document.querySelector(
                                    'button [class*="truncate"]');
                                  return !!(el &&
                                    (el.textContent || '').trim());
                                }""")
                                selesai = bool(ada)
                        except Exception:
                            selesai = False
                        if not selesai and (
                                time.time() - self._boot_cover > 45):
                            selesai = True
                            catat("tutup boot: 45 dtk habis - "
                                  "sesi belum siap, tampilkan halaman")
                        if selesai:
                            self._boot_selesai = True
                            self._boot_cover = None
                            self._tahan = None   # jangan buka cover lagi
                    if (not getattr(self, "_boot_cover", None)
                            and "edclub.com" in u and _rute_lama(u)
                            and time.time() - getattr(
                                self, "_bounce_lama", 0.0) > 6.0):
                        # rute lama + bot tidak sedang memakai daftar
                        # (bangun peta/lompat via daftar = PETA_BANGUN)
                        peta = False
                        try:
                            from engine import state as _eng
                            peta = bool(getattr(_eng, "PETA_BANGUN", False))
                        except Exception:
                            peta = False
                        if not peta:
                            # RESTRIKSI USER (Nov 2026): user sedang
                            # memakai halaman (klik/klik dropdown < 8 dtk)
                            # = JANGAN memantulkan halaman - dulu halaman
                            # loncat saat dia memilih tanggal lahir dsb.
                            ua = self._user_aktif_pg(pg)
                            if ua is not None and ua < 8.0:
                                continue
                            self._bounce_lama = time.time()
                            # cover: kedipan UI lama -> UI baru jangan
                            # terlihat (permintaan user)
                            self.tahan_halaman("/student/course", 8.0)
                            try:
                                pg.evaluate("() => location.href = %r"
                                            % COURSE_URL)
                                catat("rute tampilan lama - balik ke "
                                      "UI baru (course/3)")
                            except Exception:
                                pass
                            continue
                    if perlu_boot and "edclub" in u:
                        # sesi sudah dipasang - boot ulang agar SPA
                        # membacanya (sekali, berhenti kalau berhasil)
                        try:
                            pg.evaluate("() => location.href = "
                                        "'https://www.edclub.com/student/'"
                                        "course/3'")
                            perlu_boot = False
                            jantung[0] = time.time()
                            continue
                        except Exception:
                            pass
                    if "auth_callback" in u:
                        # init script relay harusnya menjemput halaman ini
                        # dalam hitungan detik. Kalau >6 dtk masih di
                        # sini = tersesat (script tak jalan) -> selamatkan
                        # manual: bawa code ke /signin & tukar token di
                        # sana (fetch yang sama dengan SPA edclub).
                        mk = re.search(r"[?&]code=([^&]+)", u)
                        kode = mk.group(1) if mk else ""
                        if not kode or kode in kode_coba:
                            continue
                        callback_sejak.setdefault(kode, time.time())
                        if time.time() - callback_sejak[kode] > 6.0:
                            kode_coba.add(kode)
                            callback_sejak.pop(kode, None)
                            issuer = "google"
                            mi = re.search(r"[?&]iss=([^&]+)", u)
                            if mi:
                                dari = mi.group(1).lower()
                                if "clever" in dari:
                                    issuer = "clever"
                                elif "office" in dari or "microsoft" in dari:
                                    issuer = "office365"
                            catat("callback OAuth terdampar (init script "
                                  "tak jalan) - relay manual...")
                            hasil = ""
                            try:
                                try:
                                    pg.evaluate("() => location.href = "
                                                "'https://www.edclub.com/signin'")
                                except Exception:
                                    pass   # navigasi memusnahkan konteks
                                           # eval = wajar, bukan galat
                                # tunggu benar-benar sampai /signin (dulu
                                # langsung evaluate -> 'context destroyed'
                                # -> code terbakar sia-sia)
                                for _i in range(8):
                                    time.sleep(2)
                                    try:
                                        u2 = pg.evaluate(
                                            "() => location.href")
                                    except Exception:
                                        continue
                                    if "/signin" in u2:
                                        break
                                time.sleep(1.5)
                                jantung[0] = time.time()
                                hasil = pg.evaluate(
                                    _RELAY_LANGSUNG_JS,
                                    {"kode": kode, "issuer": issuer}) or ""
                            except Exception as ex:
                                hasil = f"err:{repr(ex)[:40]}"
                            jantung[0] = time.time()
                            if hasil == "ok":
                                catat("login OAuth diselamatkan (relay "
                                      "manual) - menuju daftar level...")
                                # boot pertama kadang bounce balik ke
                                # /signin: sesi server butuh beberapa
                                # detik & SPA perlu waktu re-login
                                # (refresh-tokens{domain} 200 terbukti)
                                # - pantau sabar 6x5 dtk, kembali ke
                                # course/3 selama masih di /signin
                                for _i in range(6):
                                    time.sleep(5)
                                    try:
                                        u3 = pg.evaluate(
                                            "() => location.href")
                                    except Exception:
                                        continue
                                    if "/signin" in u3:
                                        catat("boot masih ke /signin - "
                                              "coba masuk lagi...")
                                        try:
                                            pg.evaluate(
                                                "() => location.href = "
                                                "'https://www.edclub.com/'"
                                                "student/course/3'")
                                        except Exception:
                                            pass
                                        continue
                                    catat("halaman: "
                                          f"{u3[:80]} - login bertahan")
                                    break
                            else:
                                catat(f"relay manual: {hasil[:60]}")
                        continue
                    if "edclub" not in u or "signin" in u:
                        continue
                    try:
                        pg.evaluate(wrap)   # navigasi kalau anon/error
                        jantung[0] = time.time()
                    except Exception:
                        pass
        except Exception as ex:
            if not stop.is_set():
                catat(f"pengawas mati: {ex!r}")
        finally:
            try:
                if pw is not None:
                    pw.stop()
            except Exception:
                pass
    def set_overlay(self, widget):
        self._stage_widget = widget
        widget.place(in_=self._overlay, relx=0.5, rely=0.5, anchor="center")

    def _boot_anim(self):
        """Spinner + teks 'Menyiapkan edclub...' di overlay tutup boot.
        after() murni Tk (thread UI) - dibatalkan saat tutup dibuka."""
        try:
            warna = self._overlay.cget("bg")
            cv = tk.Canvas(self._overlay, width=84, height=84, bg=warna,
                           highlightthickness=0)
            lbl = tk.Label(self._overlay, text="Menyiapkan edclub\u2026",
                           font=("Segoe UI", 12), fg="#9aa6b8", bg=warna)
            cv.place(relx=0.5, rely=0.44, anchor="center")
            lbl.place(relx=0.5, rely=0.56, anchor="center")
            N, C = 8, 42
            dots = []
            for i in range(N):
                a = 2.0 * math.pi * i / N
                x = C + 30.0 * math.cos(a)
                y = C + 30.0 * math.sin(a)
                dots.append(cv.create_oval(x - 4, y - 4, x + 4, y + 4,
                                           fill="#26314a", width=0))
            fase = {"i": 0}

            def tik():
                if self._boot_anim_job is None:
                    return      # sudah dibatalkan/dibuka
                fase["i"] = (fase["i"] + 1) % N
                for j, item in enumerate(dots):
                    langkah = (j - fase["i"]) % N
                    if langkah == 0:
                        wrn = "#3b82f6"      # titik aktif terang
                    elif langkah == 1:
                        wrn = "#1d4ed8"      # ekor
                    else:
                        g = 38 + max(0, 20 - 3 * langkah)
                        wrn = f"#{g:02x}{g:02x}{g:02x}"
                    cv.itemconfigure(item, fill=wrn)
                self._boot_anim_job = self.after(90, tik)

            self._boot_anim_job = self.after(90, tik)
        except Exception:
            pass

    def ke_url(self, url):
        """Minta watcher mengarahkan halaman utama embed ke url. Aman
        antar-thread: cuma set flag, watcher yang mengeksekusi (callback
        .NET -> Python dilarang keras - GIL crash)."""
        self._nav_pending = url

    def set_on_ready(self, cb):
        self._on_ready = cb

    def buka(self, port, url, warna="#141519"):
        """Buat WebView2 dengan port debug + navigasi ke url.
        HARUS dipanggil di thread UI (CLR STA) setelah jendela tampil."""
        try:
            import webview
            # popup/target=_blank (OAuth Google dkk): jangan buka di browser
            # OS - navigasi halaman utama saja (tetap di dalam app, tanpa
            # jendela melayang; alur redirect OAuth tetap selesai di sini)
            try:
                webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = False
            except Exception:
                pass
            from webview.platforms.edgechromium import EdgeChrome
            from webview.window import Window
            from System.Windows.Forms import Control
            webview.settings["REMOTE_DEBUGGING_PORT"] = port
            control = Control()
            window = Window(
                "typingbot", "1", url=None, html=None, js_api=None,
                width=max(self.winfo_width(), 400),
                height=max(self.winfo_height(), 300), x=None, y=None,
                resizable=True, fullscreen=False, min_size=(200, 100),
                hidden=False, frameless=False, easy_drag=True,
                minimized=False, on_top=False, confirm_close=False,
                background_color=warna, transparent=False,
                text_select=True, localization=None, zoomable=True,
                draggable=True, vibrancy=False)
            os.makedirs(self._profil, exist_ok=True)
            ec = EdgeChrome(control, window, self._profil)
            self._ec = ec
            self._chwnd = int(str(control.Handle))
            user32.SetParent(self._chwnd, self.winfo_id())
            self._pas_ukuran()
            # TUTUP BOOT (permintaan user: kilat 'belum login' saat buka
            # app membingungkan): kalau ada sesi tersimpan, webview
            # DISEMBUNYIKAN + overlay tertutup sampai pengawas melihat
            # pill profil (login sukses) - lalu app terbuka LANGSUNG di
            # daftar level sudah login. Timeout 45 dtk: sesi memang mati,
            # tampilkan seperti biasa (user login manual).
            if os.path.exists(_sesi_path()):
                self._boot_cover = time.time()
                self._boot_selesai = False
                try:
                    user32.ShowWindow(self._chwnd, 0)   # SW_HIDE
                except Exception:
                    pass
                try:
                    # sembunyikan kartu status 'Siap' (set_overlay
                    # menaruhnya DI ATAS overlay - dulu ikut tampak:
                    # abu beda + 'Siap' saat boot, keluhan user jelek)
                    # lalu tampilkan spinner 'Menyiapkan edclub...'
                    st = self._stage_widget
                    if st is not None:
                        st.place_forget()
                    self._boot_anim()
                except Exception:
                    pass
            else:
                self._overlay.place_forget()
            # PENTING (stabilitas): lepas SEMUA handler event pywebview.
            # Handler itu callback Python dari thread .NET - kombinasi dgn
            # mainloop Tk memicu crash GIL (PyEval_RestoreThread) saat init
            # webview selesai. Interaksi .NET hanya lewat polling dari
            # thread Tk (lihat _jaga) - tanpa callback balik sama sekali.
            wv = ec.webview
            for ev_name, fn in (("CoreWebView2InitializationCompleted",
                                 "on_webview_ready"),
                                ("NavigationStarting", "on_navigation_start"),
                                ("NavigationCompleted",
                                 "on_navigation_completed"),
                                ("WebMessageReceived", "on_script_notify")):
                try:
                    getattr(wv, ev_name).__isub__(getattr(ec, fn))
                except Exception:
                    pass
            # popup (Google/Clever OAuth): handler popup pywebview akan
            # dicabut di _jaga begitu CoreWebView2 siap - popup WebView2
            # asli lalu kita adopsi ke dalam app
            ec.load_url(url)
            self._jaga()
            return True
        except Exception as ex:
            print(f"[WEBVIEW2] gagal dibuat ({str(ex)[:100]}) - pakai "
                  "browser eksternal.")
            self._ec = None
            return False

    def _core_ready(self, sender, _args):
        """TIDAK DIPAKAI: callback .NET -> Python dari thread asing
        memicu crash GIL. Penanganan init dilakukan lewat polling _jaga."""

    def _user_aktif_pg(self, pg):
        """Detik sejak input user terakhir di halaman (min lintas frame).
        None = tak diketahui - PERLAKUKAN sbg user aktif (jangan ganggu:
        bug live teman user Nov 2026: dropdown tanggal lahir tertutup
        sendiri + layar kehitaman - pengawas memantul/menutup halaman
        TEPAT saat user sedang memakainya)."""
        try:
            from engine.jstemplates import USER_WATCH_JS
        except Exception:
            return None
        best = None
        try:
            for fr in pg.frames:
                try:
                    v = fr.evaluate("() => {" + USER_WATCH_JS + "}")
                except Exception:
                    continue
                if isinstance(v, (int, float)) and (best is None or v < best):
                    best = v
        except Exception:
            return None
        return best

    def tahan_halaman(self, potongan, maks=8.0):
        """Cover 'tahan halaman': sembunyikan kedipan navigasi OTOMATIS
        (rute lama -> UI baru, pindah .play klasik, selesai login) -
        permintaan user: kedipan halaman salah tak boleh terlihat.
        Thread-aman (cuma set attr); _jaga (thread UI) membuka tutupnya
        dan membuka webview balik saat potongan muncul / waktu habis."""
        self._tahan = (potongan, time.time() + maks)

    def _jaga(self):
        """Polling dari thread Tk (tanpa callback .NET -> Python):
        1. begitu CoreWebView2 ada: cabut handler popup pywebview (yang
           membuka link di browser OS / menimpa halaman utama - penyebab
           dialog 'Get an app to open this link' saat login Google) dan
           suntik JS anti-popup (lihat _NO_POPUP_JS).
        2. adopsi jendela popup WebView2 (OAuth dll): jendela milik proses
           webview kita yang ber-owner ke kontrol utama -> jadi CHILD
           frame ini, penuh memenuhi area. Popup menutup dirinya sendiri
           saat OAuth selesai (relasi opener tetap utuh)."""
        # ---- cover tahan-halaman: buka bila diminta & belum terbuka
        tahan = getattr(self, "_tahan", None)
        if tahan and not getattr(self, "_boot_cover", None):
            pot, batas = tahan
            if time.time() <= batas and self._chwnd:
                self._boot_cover = time.time()
                self._boot_selesai = False
                try:
                    user32.ShowWindow(self._chwnd, 0)   # SW_HIDE
                    st = self._stage_widget
                    if st is not None:
                        st.place_forget()
                    self._boot_anim()
                except Exception:
                    pass
            else:
                self._tahan = None
        GW_OWNER = 4
        if getattr(self, "_boot_selesai", False):
            # buka tutup boot DI THREAD UI: tampilkan webview TANPA
            # mencuri fokus (SW_SHOWNA, sama seperti setelah dialog)
            self._boot_selesai = False
            if self._boot_anim_job:
                try:
                    self.after_cancel(self._boot_anim_job)
                except Exception:
                    pass
                self._boot_anim_job = None
            if self._dialog_aktif:
                # dialog dalam-app sedang membuka area: JANGAN betulkan
                # overlay & JANGAN nyalakan webview (live: failsafe tutup
                # boot 45 dtk menang balapan lawan lepas_untuk_dialog ->
                # webview muncul 'hitam basi' + strip piksel halaman lama
                # terlihat di bawah dialog, keluhan user). pasang_setelah
                # _dialog memulihkan semuanya saat dialog ditutup.
                pass
            else:
              try:
                for w in self._overlay.winfo_children():
                    w.destroy()
                # kartu status kembali persis seperti semula (dipakai
                # juga oleh overlay dialog dalam-app)
                st = self._stage_widget
                if st is not None:
                    st.place(in_=self._overlay, relx=0.5, rely=0.5,
                             anchor="center")
                self._overlay.place_forget()
              except Exception:
                pass
              if self._chwnd:
                try:
                    user32.ShowWindow(self._chwnd, 8)   # SW_SHOWNA
                except Exception:
                    pass
        if self._ec and not self._popup_unsub:
            try:
                core = self._ec.webview.CoreWebView2
                if core is not None:
                    core.NewWindowRequested -= self._ec.on_new_window_request
                    self._popup_unsub = True
                    # suntik pembasmi popup SEKALI (CoreWebView2 baru pasti
                    # ada di titik ini, panggilan dari thread Tk = aman).
                    try:
                        core.AddScriptToExecuteOnDocumentCreatedAsync(
                            _NO_POPUP_JS)
                    except Exception as ex:
                        print(f"[WEBVIEW2] AddScript anti-popup gagal: "
                              f"{ex!r} - pakai polling ExecuteScript.")
            except Exception:
                pass
        # anti-popup utk kasus app DIAM (belum Start - engine belum
        # terhubung & add_init_script engine belum terpasang): jalankan
        # JS-nya ke dokumen AKTIF tiap ~1.5 dtk (panggilan .NET dari
        # thread Tk = aman, bukan callback balik). Dokumen baru buta
        # anti-popup maksimal 1.5 dtk - user tak sempat klik Google
        # selah itu.
        if self._ec and self._popup_unsub:
            try:
                if time.time() - getattr(self, "_anti_ct", 0) > 1.5:
                    self._anti_ct = time.time()
                    core = self._ec.webview.CoreWebView2
                    if core is not None:
                        core.ExecuteScriptAsync(_NO_POPUP_JS)
            except Exception:
                pass
        # pengarah halaman awal: jalur ExecuteScriptAsync terbukti SUNG
        # (script tak pernah jalan via pythonnet, tak pernah error) -
        # pekerjaan ini dipindah ke PENGAWAS playwright (mulai_pengawas)
        # yg memakai add_init_script + evaluate murni-python: terbukti
        # jalan. Lihat _LOGIN_REDIRECT_JS di atas.
        temuan = []
        chwnd = self._chwnd
        # pid proses msedge kita: dari widget Chromium utama yang sudah
        # ditanam (anak chwnd). Popup WebView2 hidup di proses yang sama -
        # LIVE: popup Google ternyata TOP-LEVEL owner=0 (bukan owned
        # chwnd seperti duga lama) -> cek owner doang tak pernah cocok,
        # popup melayang di luar app selamanya (keluhan user).
        pid_kita = 0
        if chwnd:
            @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            def cari_anak(h, _l):
                buf = ctypes.create_unicode_buffer(64)
                user32.GetClassNameW(h, buf, 64)
                if buf.value == "Chrome_WidgetWin_1":
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
                    self._pid_utama = pid.value
                    return False
                return True
            try:
                self._pid_utama = getattr(self, "_pid_utama", 0)
                user32.EnumChildWindows(chwnd, cari_anak, 0)
                pid_kita = getattr(self, "_pid_utama", 0)
            except Exception:
                pid_kita = 0

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum_cb(hwnd, _l):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                buf = ctypes.create_unicode_buffer(64)
                user32.GetClassNameW(hwnd, buf, 64)
                if buf.value != "Chrome_WidgetWin_1":
                    return True
                # cocok: owned chwnd (kasus lama) ATAU satu proses msedge
                # dengan widget utama kita (popup WebView2, owner=0)
                cocok = user32.GetWindow(hwnd, GW_OWNER) == chwnd
                if not cocok and pid_kita:
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    cocok = pid.value == pid_kita
                if cocok:
                    temuan.append(hwnd)
            except Exception:
                pass
            return True

        user32.EnumWindows(enum_cb, 0)
        for hwnd in temuan:
            try:
                judul = ctypes.create_unicode_buffer(128)
                user32.GetWindowTextW(hwnd, judul, 128)
                if judul.value.strip().lower() in ("about:blank", ""):
                    # popup kosong sisa alur lama -> tutup, jangan numpuk
                    self._blank_ct[hwnd] = self._blank_ct.get(hwnd, 0) + 1
                    if self._blank_ct[hwnd] >= 4:
                        user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
                        self._blank_ct.pop(hwnd, None)
                    continue
                self._blank_ct.pop(hwnd, None)
                style = user32.GetWindowLongW(hwnd, GWL_STYLE)
                style &= ~(WS_CAPTION | WS_THICKFRAME)
                style |= WS_CHILD | WS_VISIBLE
                user32.SetWindowLongW(hwnd, GWL_STYLE, style)
                user32.SetParent(hwnd, self.winfo_id())
                user32.SetWindowPos(hwnd, 0, 0, 0,
                                    max(self.winfo_width(), 50),
                                    max(self.winfo_height(), 50),
                                    SWP_NOZORDER | SWP_NOACTIVATE |
                                    SWP_FRAMECHANGED)
            except Exception:
                pass
        if self._ec:
            self._jaga_job = self.after(400, self._jaga)

    def release(self):
        """Lepas WebView2 saat app ditutup (browser process ikut mati -
        profil dedikasi tetap tersimpan utk login berikutnya)."""
        ec, self._ec = self._ec, None
        if ec is None:
            return
        try:
            wv = getattr(ec, "webview", None)
            if wv is not None:
                wv.Dispose()
        except Exception:
            pass

    # ---------------------------------------------------------- internal
    def _pas_ukuran(self):
        if not self._chwnd:
            return
        try:
            user32.MoveWindow(self._chwnd, 0, 0,
                              max(self.winfo_width(), 50),
                              max(self.winfo_height(), 50), True)
        except Exception:
            pass

    def _on_resize(self, _ev=None):
        self.after_idle(self._pas_ukuran)
