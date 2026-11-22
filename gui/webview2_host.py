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
import threading
import time
import tkinter as tk
from tkinter import ttk
from .theme import ACCENT

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
    // JANGAN sentuh halaman pendaftaran - dulu tombol 'Log in' di
    // header signup memicu lemparan balik ke /signin DI TENGAH user
    // mengisi form pendaftaran (keluhan user 15 Nov: adiknya harus
    // daftar di Chrome terpisah karena webview selalu mundur)
    if (p.indexOf('signup') >= 0) return;
    if (p.indexOf('register') >= 0) return;
    if (p.indexOf('join') >= 0) return;
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
    // niat = tombol yang diklik sebelum ke Google ('signup'/'signin',
    // dicatat listener klik di blok 4). Sekali pakai.
    var niat = '';
    try {
      niat = sessionStorage.getItem('tb_oauth_from') || '';
      sessionStorage.removeItem('tb_oauth_from');
    } catch (e) {}
    var tujuan = 'https://www.edclub.com/signin';
    function pesan(m) {
      try { sessionStorage.setItem('tb_oauth_msg', m); } catch (e) {}
    }
    // jejak utk bot.log (dibaca host v4 lewat sessionStorage tb_oauth_dbg)
    var jejak = ['niat=' + (niat || '-')];
    function pergi(u) {
      try {
        sessionStorage.setItem('tb_oauth_dbg', jejak.join(' ') + ' -> ' + u);
      } catch (e) {}
      location.replace(u);
    }
    (async () => {
      for (var i = 0; i < issuers.length; i++) {
        try {
          var r = await fetch(api + '/auth/resolve_oauth_token/',
            Object.assign({}, opt, {body: JSON.stringify(
              {issuer: issuers[i], code: rc, domain: 'www'})}));
          if (!r.ok) { jejak.push(issuers[i] + ':' + r.status); continue; }
          var d = await r.json();
          jejak.push(issuers[i] + ':200 user=' + !!(d && d.user) +
                     ' tpc=' + ((d && d.tpc_users) || []).length +
                     ' sign=' + !!(d && d.sign) +
                     ' konf=' + ((d && d.identity_confirmation_status) || '-'));
          var k = [];
          if (d && d.user) k.push(d.user);
          if (d && d.tpc_users) k.push(...d.tpc_users);
          var tok = null;
          for (var j = 0; j < k.length; j++)
            if (k[j] && k[j].login_token) { tok = k[j].login_token; break; }
          // AKUN GOOGLE TANPA AKUN EDCLUB (bundle live edclub, Nov
          // 2026: resolve balas 200 tanpa user -> /signin asli cuma
          // menampilkan 'User not found.', dan /signup memanggil
          // /website/create_tp_oauth_user/ {sign} -> login_token).
          // DULU: break -> balik ke /signin TANPA pesan = user baru
          // berputar signin -> google -> signin selamanya.
          if (!tok && !k.length && d &&
              !d.identity_confirmation_status) {
            if (niat === 'auto') {
              // login otomatis (bukan klik user): diam saja ke /signin
              tujuan = 'https://www.edclub.com/signin';
            } else if (niat === 'signup' && d.sign) {
              try {
                var rs = await fetch(
                  api + '/website/create_tp_oauth_user/',
                  Object.assign({}, opt, {body: JSON.stringify(
                    {sign: d.sign, locale: 'en_US'})}));
                var ds = rs.ok ? await rs.json() : null;
                if (ds && ds.login_token) tok = ds.login_token;
              } catch (e) {}
              if (!tok) {
                pesan('Akun baru gagal dibuat. Coba lagi ya.');
                tujuan = 'https://www.edclub.com/signup';
              }
            } else {
              pesan('Akun Google ini belum terdaftar di edclub. ' +
                    'Klik "Sign up with Google" di halaman ini ' +
                    'untuk membuat akun baru.');
              tujuan = 'https://www.edclub.com/signup';
            }
          }
          if (!tok && d && d.identity_confirmation_status) {
            pesan(d.identity_confirmation_status === 'sent'
              ? 'edclub mengirim link konfirmasi ke email akun ini. ' +
                'Buka emailnya dulu, lalu login lagi.'
              : 'Konfirmasi email belum selesai. Cek email akun ini ' +
                'atau coba lagi beberapa menit lagi.');
          }
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
          jejak.push('refresh=' + r2.status);
          if (r2.ok) {
            pergi('https://www.edclub.com/student/course/3');
            return;
          }
        } catch (e) {}
      }
      pergi(tujuan);
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
        // GUARD PILL (live 15 Nov): refresh-tokens yang ditembak di
        // sini BERLOBA dgn rotasi rt milik SPA edclub sendiri - rt
        // single-use, salah satu panggilan kalah = keluarga token
        // dicabut server = sesi mati beberapa detik setelah login
        // (log user: course/3 -> /signin berulang). Pill profil ada =
        // sedang login = JANGAN sentuh endpoint ini sama sekali.
        var _pill = document.querySelector('button [class*="truncate"]');
        if (_pill && (_pill.textContent || '').trim()) {
          coba3 = 0; return;
        }
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
  // 4) niat + pesan (hanya sampai sini di host edclub).
  //    a) catat tombol OAuth yang diklik: 'Sign up with ...' = user
  //       memang mau BUAT akun (blok 2 baru boleh membuatkan akun).
  //    b) tampilkan pesan titipan blok 2 (textContent, aman CSP).
  try {
    document.addEventListener('click', function (ev) {
      try {
        var el = ev.target;
        for (var i = 0; i < 6 && el; i++, el = el.parentElement) {
          var t = ((el.textContent || '') + '').toLowerCase();
          if (t.length > 60) break;
          var up = t.indexOf('sign up with') >= 0;
          if (up || t.indexOf('sign in with') >= 0) {
            sessionStorage.setItem('tb_oauth_from',
                                   up ? 'signup' : 'signin');
            return;
          }
        }
      } catch (e) {}
    }, true);
    var msg = sessionStorage.getItem('tb_oauth_msg') || '';
    if (msg && !rc) {
      sessionStorage.removeItem('tb_oauth_msg');
      var tampil = function () {
        try {
          var b = document.createElement('div');
          b.id = 'tb-oauth-msg';
          b.textContent = msg;
          b.style.cssText = 'position:fixed;top:12px;left:50%;' +
            'transform:translateX(-50%);z-index:2147483647;' +
            'max-width:520px;padding:12px 16px;border-radius:8px;' +
            'background:#1f2937;color:#fff;font:14px/1.4 system-ui,' +
            'sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.25);' +
            'cursor:pointer';
          b.addEventListener('click', function () { b.remove(); });
          document.body.appendChild(b);
          setTimeout(function () { try { b.remove(); } catch (e) {} },
                     20000);
        } catch (e) {}
      };
      if (document.body) tampil();
      else document.addEventListener('DOMContentLoaded', tampil);
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
# Marker klik OAuth: listener klik level dokumen; begitu user klik
# tombol Google, judul halaman di-set 'TB_OAUTH' - _jaga (thread UI,
# baca .NET DocumentTitle murah tiap tick) mengangkat cover instan
# tanpa nunggu tick pengawas. CSP-aman: cuma set document.title.
OAUTH_MARKER_JS = """
(function(){
  if (window.__tb_oauth_mark) return; window.__tb_oauth_mark = 1;
  document.addEventListener('click', function(ev){
    try {
      var el = ev.target;
      for (var i = 0; i < 6 && el; i++, el = el.parentElement) {
        var t = ((el.textContent || '') + '').toLowerCase();
        var h = (el.getAttribute && el.getAttribute('href')) || '';
        if (t.indexOf('sign in with google') >= 0 ||
            h.indexOf('accounts.google') >= 0) {
          document.title = 'TB_OAUTH';
          return;
        }
      }
    } catch (e) {}
  }, true);
})();
"""

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


def _akun_aktif_nama():
    """Nama akun aktif tersimpan (aktif.json), atau None."""
    try:
        with open(os.path.join(_dir_akun(), "aktif.json"),
                  encoding="utf-8") as f:
            return (json.load(f) or {}).get("nama")
    except Exception:
        return None


def _folder_profil_akun(nama):
    """Folder data WebView2 KHUSUS akun (jar terisolasi per akun).
    edclub menganggap tiap folder = browser berbeda, jadi login akun
    baru TIDAK mematikan tiket akun lain (penyebab 'harus login
    ulang' di cookie-swap lama - eksperimen live 18-19 Nov)."""
    try:
        from .theme import LOG_FILE
        base = os.path.dirname(LOG_FILE)
    except Exception:
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
    aman = re.sub(r'[<>:"/\\|?*]+', "_", str(nama or "akun")).strip()
    d = os.path.join(base, "profil-akun", aman or "akun")
    baru = not os.path.isdir(d)
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d, baru
    return d


_KUKI_IDENTITAS = ("pw_uuid", "connectId", "tb_lt", "_cc_id",
                   "_lc2_fpi", "_pubcid", "_sharedid")

# Tiket sesi EDCLUB yang BENAR-BENAR berarti login. Dulu cukup 'ada
# kuki apa saja': _cfuvid (Cloudflare, SET-COOKIE di SEMUA respons)
# lolos filter __cf* (prefix beda: _cfuvid vs __cf) -> sesi 'sampah'
# tersimpan -> auto-simpan menghidupkan 'aktif' akun lama padahal
# sesinya sudah bersih (+ Akun: pill 'Zafran H ✓ aktif' bangkit
# kembali, live 15 Nov).
_KUKI_AUTENTIK = ("tb_lt", "rt")


def sesi_bernilai(cookies):
    """True bila daftar kuki memuat tiket login edclub (tb_lt/rt).
    Kuki analitik/CDN saja = BUKAN sesi - jangan disimpan."""
    nama = {c.get("name", "") for c in (cookies or [])}
    return bool(nama & set(_KUKI_AUTENTIK))


def _kuki_ttd(cookies):
    """Sidik jari IDENTITAS akun: HANYA cookie stabil (pw_uuid,
    connectId, tb_lt, ...). Dulu hash SEMUA cookie: token berputar
    tiap login ('rt', '_cfuvid') membuat dua simpanan akun yang SAMA
    tak pernah terkenali = 'Akun 1' tetap ada (kasus nyata 12 Nov:
    rt & _cfuvid beda, 18 cookie lain identik)."""
    import hashlib
    pilih = {c.get("name"): c.get("value", "")
             for c in (cookies or []) if c.get("name") in _KUKI_IDENTITAS}
    if not pilih:
        pilih = {c.get("name", ""): c.get("value", "")
                 for c in (cookies or [])}
    pasang = sorted(f"{k}={v}" for k, v in pilih.items() if k)
    return hashlib.md5(";".join(pasang).encode(
        "utf-8", "ignore")).hexdigest()


def _akun_semua_meta():
    """[(nama, meta, pathfile)] untuk semua akun tersimpan."""
    d = _dir_akun()
    hasil = []
    try:
        for f in os.listdir(d):
            if not f.endswith(".json") or f == "aktif.json":
                continue
            try:
                with open(os.path.join(d, f), encoding="utf-8") as fh:
                    meta = json.load(fh)
                hasil.append((meta.get("nama") or "", meta,
                              os.path.join(d, f)))
            except Exception:
                continue
    except Exception:
        pass
    return hasil


def akun_bersih_dupe():
    """Buang entri duplikat temporer 'Akun N' yang sesinya SAMA dengan
    entri bernama asli (sisa build lama yg menyimpan tanpa nama profil
    - keluhan user Nov 2026: 'why is there an akun 1 on my list').
    aktif.json diarahkan ke si kembar bila ternyata menunjuk dupe.
    Dipanggil sekali saat app start; aman thd file rusak."""
    import re
    meta_all = _akun_semua_meta()

    # -- perapian nama spasi-ganda ('Zafran  H' -> 'Zafran H', hasil
    #    tangkapan pill edclub): ubah meta + nama file + aktif.json
    for nama, meta, pth in meta_all:
        bersih = re.sub(r"\s+", " ", (nama or "")).strip()
        if not nama or bersih == nama:
            continue
        pth_baru = os.path.join(os.path.dirname(pth),
                                "akun-" + "".join(
                                    ch for ch in bersih
                                    if ch.isalnum() or ch in " -_").strip()
                                + ".json")
        try:
            meta["nama"] = bersih
            with open(pth, "w", encoding="utf-8") as f:
                json.dump(meta, f)
            os.replace(pth, pth_baru)
            if akun_aktif_nama() == nama:
                _akun_aktif_set(bersih)
        except Exception:
            continue
    meta_all = _akun_semua_meta()

    for nama, meta, pth in meta_all:
        if not re.fullmatch(r"Akun \d+", nama or ""):
            continue
        ttd = _kuki_ttd(meta.get("cookies"))
        kembar = next(((n for n, m, _ in meta_all
                        if not re.fullmatch(r"Akun \d+", n or "")
                        and _kuki_ttd(m.get("cookies")) == ttd
                        and m.get("cookies"))), None)
        if not kembar:
            continue
        try:
            os.remove(pth)
        except Exception:
            continue
        try:
            if akun_aktif_nama() == nama:
                _akun_aktif_set(kembar)
        except Exception:
            pass


def simpan_akun(nama=None, cookies=None):
    """Daftarkan sesi sebagai akun tersimpan. TANPA nama = menolak
    (dulu bikin 'Akun 1'/'Akun 2' tak berarti - keluhan user Nov 2026).
    Sesi tanpa tiket login (tb_lt/rt) juga ditolak - kuki sampah CDN
    bukan sesi. Return nama terpakai, None kalau tak ada sesi/nama."""
    c = cookies or _sesi_muat()
    if not c or not (nama or "").strip():
        return None
    if not sesi_bernilai(c):
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
    Akun baru = dibuat; akun yang sudah ada = cookie-nya DISEGARKAN
    bila tiketnya berubah (fingerprint tb_lt/rt) ATAU file lebih tua
    30 menit - tiket edclub dirotasi server tiap pemakaian, jadi
    simpanan yang tidak ikut berubah = mati saat ganti akun (keluhan
    user 15 Nov: swap balik = kena relogin). Selalu set aktif. Thread
    pengawas aman (file saja)."""
    d = _dir_akun()
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        return False
    if not (nama or "").strip():
        # nama profil tak terbaca: JANGAN bikin entri tanpa nama (sisa
        # 'Akun 1' dulu) - coba lagi di gelombang pengawas berikutnya
        return False
    import re as _re
    nama = _re.sub(r"\s+", " ", nama).strip()
    aman = "".join(ch for ch in nama
                   if ch.isalnum() or ch in " -_.").strip() or "akun"
    pth = os.path.join(d, f"akun-{aman}.json")
    ttd = _kuki_ttd(cookies)
    try:
        lama = 0.0
        ttd_lama = ""
        if os.path.exists(pth):
            with open(pth, encoding="utf-8") as f:
                meta = json.load(f)
            lama = meta.get("waktu", 0)
            ttd_lama = meta.get("ttd", "")
        if ttd != ttd_lama or time.time() - lama > 1800:
            with open(pth, "w", encoding="utf-8") as f:
                json.dump({"nama": nama, "waktu": time.time(),
                           "ttd": ttd, "cookies": cookies}, f)
            # entri BARU: buang duplikat temporer 'Akun N' yg sesinya sama
            akun_bersih_dupe()
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


def _cover_log(pesan):
    """Log diagnostik siklus cover (cari [COVER] di bot.log)."""
    try:
        from .theme import LOG_FILE
        import time as _t
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("[COVER] " + _t.strftime("%H:%M:%S") + " "
                    + pesan + chr(10))
    except Exception:
        pass



class Wv2Host(tk.Frame):
    """Frame Tk yang menjadi permukaan halaman web (WebView2)."""

    def __init__(self, master, profil_dir, bg="#101116", edge="#2a2c33",
                 **kw):
        super().__init__(master, bg=bg, highlightthickness=1,
                         highlightbackground=edge, **kw)
        self._profil = profil_dir
        # multi-profil akun (19 Nov): kalau ada akun aktif tersimpan,
        # boot LANGSUNG di folder profil akun itu (jar terisolasi) -
        # sesi tiap akun menetap lintas restart, tidak mati saat
        # pindah akun. Login sekali per akun, seterusnya selamanya.
        try:
            _akun_boot = _akun_aktif_nama()
            if _akun_boot:
                self._profil = _folder_profil_akun(_akun_boot)[0]
        except Exception:
            pass
        # profil boot TANPA sesi (belum login / tiket mati) = tandai:
        # watcher membawa halaman logged-out ke /signin (dulu dibiarkan
        # menggantung di Typing Jungle logged-out - keluhan user 19 Nov)
        try:
            with open(_sesi_path(), encoding="utf-8") as f:
                _c = (json.load(f) or {}).get("cookies") or []
            if not any(c.get("name") in _KUKI_IDENTITAS for c in _c):
                self._perlu_login_paksa = True
        except Exception:
            pass
        self._ec = None          # EdgeChrome (pywebview)
        self._spare = None       # webview cadangan hangat (pre-warm)
        self._spare_port = 9333  # port CDP cadangan (putar 9333-9342)
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
        # identitas thread UI utk guard .NET langsung (ke_url): Navigate
        # HANYA dicoba dari thread yang sama dgn init Tk/CLR (STA) -
        # thread lain = cukup set flag, watcher urun
        self._ui_thr = threading.get_ident()
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
        _cover_log("dialog: sembunyikan webview")
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
        _cover_log("dialog selesai: tampilkan webview")
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
        """v3 MULTI-PROFIL (19 Nov): tiap akun = folder data WebView2
        sendiri (jar terisolasi) - edclub melihat browser berbeda
        sehingga tiket akun lama TIDAK dimatikan login baru (penyebab
        'harus login ulang' di era cookie-swap; eksperimen live 18-19
        Nov: tiket lama ditolak server setelah login baru di browser
        yang sama). Callback selesai(ok, pesan, folder) - folder harus
        dipakai UI thread utk ganti_profil (bongkar webview + buka
        ulang di folder akun)."""
        def kerja():
            folder, baru = _folder_profil_akun(nama)
            self._akun_pertama = bool(baru)
            cookies = _akun_cookies(nama) or []
            _akun_aktif_set(nama)
            self._nama_profil = None
            self._login_baru = False
            self._perlu_login_paksa = True
            self._akun_swap_at = time.time()
            self._lt_selamat = 0.0
            # SELALU daratkan di /signin: yang login -> edclub lempar
            # sendiri ke dashboard; yang belum = tepat di halaman login.
            # Dulu ke daftar level = nyangkut di Typing Jungle
            # logged-out lama tanpa arah (keluhan user 19 Nov)
            url = "https://www.edclub.com/signin"
            if selesai:
                selesai(True, "profil akun siap", folder, url)
            if cookies:
                threading.Thread(
                    target=self._impor_kuki_profil,
                    args=(cookies,), daemon=True).start()
        threading.Thread(target=kerja, daemon=True).start()

    def _bar_dan_persen(self, induk, warna, putih=False):
        """Bar maju + persen: dipakai cover boot & cover ganti akun -
        satu wajah, permintaan user 21 Nov ('loading bar that has
        progress, so they feel the progress')."""
        try:
            stl = ttk.Style(induk)
            try:
                stl.theme_use("clam")
            except Exception:
                pass
            trough = "#d7dade" if putih else "#232c42"
            fg_pct = "#3a4149" if putih else "#c7d2e8"
            stl.configure("pcv.Horizontal.TProgressbar",
                          troughcolor=trough, background=ACCENT,
                          bordercolor=warna, lightcolor=ACCENT,
                          darkcolor=ACCENT, thickness=10)
            bar = ttk.Progressbar(induk, maximum=100, value=6,
                                  style="pcv.Horizontal.TProgressbar",
                                  length=380)
            bar.place(relx=0.5, rely=0.565, anchor="center")
            pct = tk.Label(induk, text="6%",
                           font=("Segoe UI", 10, "bold"),
                           fg=fg_pct, bg=warna)
            pct.place(relx=0.5, rely=0.625, anchor="center")
            return bar, pct
        except Exception as ex:
            print(f"[PCV] loading bar gagal dibuat: {str(ex)[:80]}")
            return None, None

    def _pcv_log(self, pesan):
        """Print tahap cover dgn offset ms sejak cover buka - untuk
        bedah 'hitam panjang' (keluhan user 21 Nov, ganti kedua)."""
        try:
            t0 = getattr(self, "_pcv_t0", None)
            dt = int((time.time() - t0) * 1000) if t0 else 0
            print(f"[PCV +{dt}ms] {pesan}")
        except Exception:
            print(f"[PCV] {pesan}")

    def _pcv_buka(self, nama):
        self._pcv_t0 = time.time()
        self._pcv_log("cover buka")
        """Cover loading-screen profil: frame UKURAN PERSIS area webview
        (anak host, bukan master - dulu bordernya lebih besar dr
        webview, keluhan user 21 Nov) + LOADING BAR + persen. Warna =
        persis overlay boot (user suka; dulu #1b2130 kebiruan ditolak).
        Webview lama disembunyikan biar cover bersih. Cover ditutup
        _pcv_selesai (halaman tujuan siap) - target via _pcv_target."""
        try:
            self._pcv_tutup_cepat()
            warna = self._overlay.cget("bg")
            self._pcv_frame = tk.Frame(self, bg=warna,
                                       highlightthickness=1,
                                       highlightbackground="#2a2c33")
            self._pcv_frame.place(relx=0, rely=0,
                                  relwidth=1, relheight=1)
            self._pcv_frame.lift()
            lbl = tk.Label(self._pcv_frame, text="Memuat profil akun…",
                           font=("Segoe UI", 13, "bold"), fg="#e8eaf0",
                           bg=warna)
            lbl.place(relx=0.5, rely=0.36, anchor="center")
            nm = tk.Label(self._pcv_frame, text=nama,
                          font=("Segoe UI", 11),
                          fg="#4f8cff", bg=warna)
            nm.place(relx=0.5, rely=0.42, anchor="center")
            info = tk.Label(self._pcv_frame,
                            text="menyiapkan folder data…",
                            font=("Segoe UI", 10), fg="#9aa6b8",
                            bg=warna)
            info.place(relx=0.5, rely=0.48, anchor="center")
            bar, pct = self._bar_dan_persen(self._pcv_frame, warna)
            self._pcv_aktif = True
            self._pcv_widgets = (lbl, nm, info, bar, pct)
            self._pcv_val = 6.0
            self._pcv_target = 30.0
            self._pcv_selesai = False

            def tik():
                if self._pcv_job is None:
                    return
                langkah = 3.5 if self._pcv_selesai else 1.1
                if bar is not None:
                    if self._pcv_val < self._pcv_target:
                        self._pcv_val = min(self._pcv_target,
                                            self._pcv_val + langkah)
                    if self._pcv_selesai:
                        self._pcv_target = 100.0
                        self._pcv_val = min(100.0, self._pcv_val
                                            + langkah)
                    v = int(self._pcv_val)
                    try:
                        bar.configure(value=self._pcv_val)
                        pct.configure(text=f"{v}%")
                    except Exception:
                        pass
                    if self._pcv_selesai and self._pcv_val >= 99.4:
                        self._pcv_tutup()
                        return
                elif self._pcv_selesai:
                    self._pcv_tutup()
                    return
                self._pcv_job = self.after(70, tik)

            self._pcv_job = self.after(90, tik)
            self._pcv_info_set("menyiapkan folder data…")
            try:
                user32.ShowWindow(self._chwnd, 0)
            except Exception:
                pass
            self._pcv_ganti = True   # watcher dibisukan selama ganti
            # WATCHDOG 45 dtk: apa pun yang terjadi (watcher reconnect
            # setelah webview dibuat ulang, dll), cover SELALU menutup
            # dalam 45 dtk - tidak ada stuck tanpa akhir
            def _pcv_watchdog():
                if getattr(self, "_pcv_aktif", False):
                    print("[PCV] cover >45 dtk - tutup paksa")
                    self._pcv_selesai = True
            self.after(45000, _pcv_watchdog)
        except Exception:
            pass

    def _pcv_info_set(self, teks):
        w = getattr(self, "_pcv_widgets", ())
        if len(w) >= 3 and w[2] is not None:
            try:
                w[2].configure(text=teks)
            except Exception:
                pass

    def _pcv_target_set(self, nilai):
        self._pcv_target = float(nilai)

    def _pcv_tutup_cepat(self):
        if getattr(self, "_pcv_job", None):
            try:
                self.after_cancel(self._pcv_job)
            except Exception:
                pass
        self._pcv_job = None
        self._pcv_selesai = False
        self._pcv_val = 0.0
        self._pcv_target = 0.0
        fr = getattr(self, "_pcv_frame", None)
        if fr is not None:
            try:
                fr.destroy()
            except Exception:
                pass
        self._pcv_frame = None
        self._pcv_aktif = False
        self._pcv_ganti = False

    def _pcv_tutup(self):
        self._pcv_log("cover tutup - reveal webview")
        self._pcv_tutup_cepat()
        try:
            user32.ShowWindow(self._chwnd, 1)   # SW_SHOW
        except Exception:
            pass
        try:
            self._pas_ukuran()   # rapikan posisi/ukuran webview
        except Exception:
            pass
        # kick komposisi: reveal kedua + layout ulang - kalau frame
        # pertama renderer kalah balapan, ini memaksa gambar ulang
        self.after(400, self._reveal_ulang)

    def _reveal_ulang(self):
        try:
            user32.ShowWindow(self._chwnd, 1)   # SW_SHOW
        except Exception:
            pass
        try:
            self._pas_ukuran()
        except Exception:
            pass
        self._pcv_log("reveal ulang OK")

    def ganti_profil(self, folder, url, nama=""):
        """Ganti folder data WebView2 (jar per akun). Dijalankan sbg
        state machine after(): cover spinner + LOADING BAR bertahap
        tetap hidup & menutup halaman-perantara sampai tujuan siap
        (permintaan user 19 Nov). WAJIB thread UI (CLR STA)."""
        self._pcv_buka(nama or os.path.basename(folder))
        self._gp_ttl = ""
        self._gp_ct = 0
        self._profil = folder
        try:
            os.makedirs(folder, exist_ok=True)
        except Exception:
            pass
        sp = getattr(self, "_spare", None)
        if (sp is not None and sp.get("folder") == folder
                and sp.get("siap")):
            return self._ganti_spare(folder, url, nama, sp)
        self.after(80, lambda: self._gp_dispose(folder, url, nama))

    def _buang_ec(self, ec):
        """Buang webview (dipanggil belakangan, bukan di jalur kritis
        ganti akun) - Dispose tetap WAJIB thread UI (CLR STA)."""
        if ec is None:
            return
        try:
            ec.webview.Dispose()
        except Exception:
            pass

    def _ganti_spare(self, folder, url, nama, sp):
        """Tukar ke webview cadangan yang sudah hangat: tanpa siklus
        dispose->tunggu-port->bangun-baru yang bikin ganti akun terasa
        lambat saat cold start (keluhan user 21 Nov)."""
        self._pcv_log("tukar ke webview cadangan (hangat)")
        self._pcv_info_set("hampir selesai…")
        self._pcv_target_set(60)
        ec_lama = self._ec
        self._ec = sp["ec"]
        self._chwnd = sp["hwnd"]
        self._spare = None
        # webview baru = handler popup pywebview terpasang lagi ->
        # _jaga mencabut ulang (aturan v50)
        self._popup_unsub = False
        self._anti_ct = 0
        user32.SetParent(self._chwnd, self.winfo_id())
        self._pas_ukuran()
        try:
            user32.ShowWindow(self._chwnd, 0)   # tetap tersembunyi,
            # PCV cover yang membuka saat halaman siap
        except Exception:
            pass
        # port CDP milik proses cadangan -> pengawas & engine ikut ini
        try:
            from engine import state as estate
            estate.DEBUG_PORT = sp["port"]
        except Exception:
            pass
        try:
            self.hentikan_pengawas()
        except Exception:
            pass
        try:
            self.mulai_pengawas(sp["port"])
        except Exception:
            pass
        self.after(300, lambda: self._gp_nav(folder, url, nama, 0))
        # webview lama dibuang belakangan, cadangan baru dibangun utk
        # profil yang baru ditinggalkan (bolak-balik akun = selalu hangat)
        self.after(4000, lambda: self._buang_ec(ec_lama))
        self.after(15000, self._siapkan_cadangan)

    def _siapkan_cadangan(self):
        """Pre-warm webview cadangan utk profil akun LAIN yang paling
        akhir dipakai. Konstruksi EdgeChrome mahal (2-6 dtk) dikerjakan
        SAAT IDLE, bukan saat user nunggu ganti akun. Thread UI (CLR
        STA) - freeze singkat thread Tk tidak mengganggu webview
        (input/render webview di proses browser sendiri)."""
        if getattr(self, "_spare", None) is not None:
            return
        if self._ec is None:
            return
        try:
            akar = os.path.dirname(self._profil)
            kandidat = []
            for nm in os.listdir(akar):
                fol = os.path.join(akar, nm)
                if nm == os.path.basename(self._profil):
                    continue
                if not os.path.isdir(fol):
                    continue
                kandidat.append((os.path.getmtime(fol), fol))
            if not kandidat:
                return
            kandidat.sort(reverse=True)
            folder = kandidat[0][1]
            self._bikin_cadangan(
                folder, "https://www.edclub.com/student/course/3")
        except Exception as ex:
            print(f"[AKUN] pre-warm gagal: {str(ex)[:80]}")

    def _bikin_cadangan(self, folder, url):
        """Bangun EdgeChrome cadangan tersembunyi (tanpa mesin cover
        boot - cukup polos). Port CDP sendiri: satu port cuma bisa
        dipegang satu proses browser, port utama sedang dipakai."""
        import webview
        from webview.platforms.edgechromium import EdgeChrome
        from webview.window import Window
        from System.Windows.Forms import Control
        port = getattr(self, "_spare_port", 9333)
        self._spare_port = port + 1 if port < 9342 else 9333
        webview.settings["REMOTE_DEBUGGING_PORT"] = port
        control = Control()
        window = Window(
            "typingbot-spare", "1", url=None, html=None, js_api=None,
            width=800, height=600, x=None, y=None, resizable=True,
            fullscreen=False, min_size=(200, 100), hidden=False,
            frameless=False, easy_drag=True, minimized=False,
            on_top=False, confirm_close=False,
            background_color="#101116", transparent=False,
            text_select=True, localization=None, zoomable=True,
            draggable=True, vibrancy=False)
        os.makedirs(folder, exist_ok=True)
        ec = EdgeChrome(control, window, folder)
        hwnd = int(str(control.Handle))
        user32.SetParent(hwnd, self.winfo_id())
        try:
            from System.Drawing import ColorTranslator
            control.DefaultBackgroundColor =                 ColorTranslator.FromHtml("#101116")
        except Exception:
            pass
        # lepas SEMUA handler event pywebview (aturan anti-crash GIL)
        wv = ec.webview
        for ev_name, fn in (("CoreWebView2InitializationCompleted",
                             "on_webview_ready"),
                            ("NavigationStarting",
                             "on_navigation_start"),
                            ("NavigationCompleted",
                             "on_navigation_completed"),
                            ("WebMessageReceived",
                             "on_script_notify")):
            try:
                getattr(wv, ev_name).__isub__(getattr(ec, fn))
            except Exception:
                pass
        self._spare = {"ec": ec, "hwnd": hwnd, "folder": folder,
                       "port": port, "url": url, "siap": False}
        print(f"[AKUN] pre-warm webview cadangan mulai "
              f"({os.path.basename(folder)}, port {port})")
        self._cadangkan_tunggu(0)

    def _cadangkan_tunggu(self, coba):
        """Poll core cadangan (thread UI, after) -> suntik anti-popup
        + marker OAuth -> Navigate sekali. """
        sp = getattr(self, "_spare", None)
        if sp is None:
            return
        core = None
        try:
            core = sp["ec"].webview.CoreWebView2
        except Exception:
            core = None
        if core is None:
            if coba < 120:
                self.after(250, lambda: self._cadangkan_tunggu(coba + 1))
            else:
                self._spare = None
                print("[AKUN] pre-warm batal (core tak siap)")
            return
        if not sp.get("siap"):
            try:
                core.AddScriptToExecuteOnDocumentCreatedAsync(
                    _NO_POPUP_JS)
                core.AddScriptToExecuteOnDocumentCreatedAsync(
                    OAUTH_MARKER_JS)
                core.Navigate(sp["url"])
                sp["siap"] = True
                print("[AKUN] webview cadangan siap (hangat)")
            except Exception:
                self.after(500,
                           lambda: self._cadangkan_tunggu(coba + 1))

    def _gp_dispose(self, folder, url, nama):
        self._pcv_log("dispose webview lama")
        self._pcv_info_set("menutup browser lama…")
        self._pcv_target_set(35)
        ec = self._ec
        if ec is not None:
            try:
                ec.webview.Dispose()
            except Exception:
                pass
        self._ec = None
        try:
            user32.ShowWindow(self._chwnd, 0)
        except Exception:
            pass
        self.after(200, lambda: self._gp_port(folder, url, nama, 0))

    def _gp_port(self, folder, url, nama, coba):
        try:
            from engine import state as estate
            port = int(getattr(estate, "DEBUG_PORT", 9222) or 9222)
        except Exception:
            port = 9222
        hidup = False
        try:
            import urllib.request as _ur
            _ur.urlopen(f"http://127.0.0.1:{port}/json/version",
                        timeout=1).read()
            hidup = True
        except Exception:
            hidup = False
        self._pcv_log(f"cek port 9222 (coba {coba})")
        if hidup and coba < 20:
            self.after(400, lambda: self._gp_port(folder, url, nama,
                                                  coba + 1))
            return
        self._pcv_info_set("memuat edclub di profil akun…")
        self._pcv_target_set(60)
        try:
            # cover=True = webview dibuat tersembunyi (jalur boot
            # teruji): selama cover ganti akun TIDAK ADA yang menggambar
            # di atasnya (HWND > Tk) -> tanpa kedip, bar terlihat 100%
            self._pcv_log("buka webview baru (hidden)")
            self.buka(port, url, cover=True,
                       boot=False)
            self._pcv_log("buka selesai")
        except Exception as ex:
            print(f"[AKUN] ganti profil gagal: {str(ex)[:80]}")
        self.after(300, lambda: self._gp_nav(folder, url, nama, 0))

    def _gp_nav(self, folder, url, nama, coba):
        self._pcv_info_set("hampir selesai…")
        self._pcv_target_set(85)
        core = None
        try:
            core = self._ec.webview.CoreWebView2
        except Exception:
            core = None
        if core is None:
            if coba < 60:
                self.after(250, lambda: self._gp_nav(folder, url, nama,
                                                     coba + 1))
                return
            self._pcv_tutup()
            print("[AKUN] webview tidak siap - coba klik akun lagi.")
            return
        src = str(getattr(core, "Source", "") or "")
        self._pcv_log(f"nav coba {coba}: src={src[:60]}")
        _tujuan = (url or "").split("?")[0].rstrip("/")
        _cocok = _tujuan and _tujuan in src.rstrip("/")
        if _cocok:
            # cadangan hangat sudah di halaman tujuan: pastikan saja
            # suntikan terpasang (idempotent), JANGAN navigate ulang
            try:
                core.AddScriptToExecuteOnDocumentCreatedAsync(
                    _NO_POPUP_JS)
                core.AddScriptToExecuteOnDocumentCreatedAsync(
                    OAUTH_MARKER_JS)
                self._pcv_log("src sudah pas (cadangan hangat)")
            except Exception:
                pass
        if "about:blank" in src or src.strip() in ("", "about:blank")                 or not _cocok:
            try:
                # suntik anti-popup SEBELUM Navigate: dokumen signin
                # wajib lahir dgn stub window.open (dulu suntikan
                # nunggu tick _jaga setelah load_url -> dokumen signin
                # lahir telanjang -> klik Google jadi popup asli dgn
                # tombol X sendiri - keluhan user 21 Nov)
                core.AddScriptToExecuteOnDocumentCreatedAsync(
                    _NO_POPUP_JS)
                core.AddScriptToExecuteOnDocumentCreatedAsync(
                    OAUTH_MARKER_JS)
                core.Navigate(url)
                self._pcv_log("Navigate OK")
            except Exception as ex:
                self._pcv_log(f"Navigate GAGAL: {str(ex)[:80]}")
        self.after(1200, lambda: self._gp_pantau(nama, 0))

    def _gp_pantau(self, nama, n):
        """Pantau langsung webview (.NET, bukan CDP watcher): judul
        stabil 3x berturut = halaman hidup, lalu tahan cover ±1 dtk
        lagi biar SPA selesai render (dulu kedip putih-hitam-putih
        sempat terlihat, keluhan user 21 Nov). Habis dispose, koneksi
        CDP watcher bisa mati diam - pantauan .NET ini yang dipakai.
        Gerbang piksel (PrintWindow) sudah dicoba (v40) = rapuh di
        webview tersembunyi: 45 dtk watchdog + layar hitam."""
        siap = False
        try:
            core = self._ec.webview.CoreWebView2
            src = str(getattr(core, "Source", "") or "")
            ttl = str(getattr(core, "DocumentTitle", "") or "").strip()
            if "edclub" in src and ttl and "about:blank" not in src:
                if n % 10 == 0:
                    self._pcv_log(f"poll {n}: ttl={ttl[:40]}")
                if ttl == getattr(self, "_gp_ttl", None):
                    self._gp_ct = getattr(self, "_gp_ct", 0) + 1
                    if self._gp_ct >= 3:
                        siap = True
                else:
                    self._gp_ct = 0
                self._gp_ttl = ttl
        except Exception:
            pass
        if siap:
            def tamat():
                self._pcv_selesai = True
                self._pcv_log("gate siap - bar gas ke 100%")
            self._gp_selesai(nama)
            self.after(1000, tamat)
            return
        if n < 80:
            self.after(500, lambda: self._gp_pantau(nama, n + 1))
            return
        self.after(1500, lambda: self._gp_selesai(nama))

    def _gp_selesai(self, nama):
        # cover ditutup oleh _pcv_selesai (pill/login page terdeteksi
        # watcher) - di sini cukup jaring pengaman navigasi
        try:
            core = self._ec.webview.CoreWebView2
            src = str(getattr(core, "Source", "") or "")
            if "about:blank" in src or src.strip() in ("", "about:blank"):
                core.Navigate("https://www.edclub.com/student/course/3")
        except Exception:
            pass
        def paksa_tutup():
            # jaring: kalau watcher tak menandai selesai dalam 20 dtk
            # (edge case), rayap ke 100 lalu tutup tetap terjadi
            if getattr(self, "_pcv_aktif", False):
                self._pcv_selesai = True
        self.after(20000, paksa_tutup)
        print(f"[AKUN] profil '{nama}' aktif")


    def _impor_kuki_profil(self, cookies, percobaan=6):
        """Best effort: tanam kuki snapshot ke profil yang BARU
        dibuat (CDP port sibuk boot = ulang beberapa kali). Kalau
        tiketnya masih hidup = langsung masuk; kalau tidak, login
        sekali di halaman dan SESI ITU MENETAP di profilnya."""
        for i in range(percobaan):
            time.sleep(1.2 if i == 0 else 1.0)
            try:
                from engine import state as estate
                port = int(getattr(estate, "DEBUG_PORT", 9222) or 9222)
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    br = p.chromium.connect_over_cdp(
                        f"http://127.0.0.1:{port}", timeout=8000)
                    ctx = br.contexts[0] if br.contexts else None
                    if ctx is None:
                        br.close()
                        raise RuntimeError("tanpa konteks CDP")
                    ctx.add_cookies(cookies)
                    _tb = next((c.get("value") for c in cookies
                                if c.get("name") == "tb_lt"), None)
                    if _tb and ctx.pages:
                        pgx = ctx.pages[0]
                        try:
                            pgx.evaluate(
                                "(t) => { try { localStorage.setItem("
                                "'tb_lt', t); } catch (e) {} }", _tb)
                            pgx.reload()
                        except Exception:
                            pass
                    br.close()
                    print(f"[AKUN] kuki snapshot ditanam ke profil "
                          f"(percobaan {i + 1})")
                    return
            except Exception:
                continue
        print("[AKUN] impor kuki ke profil gagal - login sekali di "
              "halaman, sesi menetap di profil akun.")


    def akun_keluar(self, selesai=None):
        """Keluar bersih utk TAMBAH akun: hapus SEMUA cookie webview +
        tiket auto-login tb_lt (kuki & localStorage) + file sesi aktif
        (biar boot tak restore akun lama). Thread belakang.

        DULU ctx.clear_cookies() doang - TIDAK menyentuh jar WebView2
        (terbukti live 15 Nov: kuki identik sebelum/sesudah,
        ctx.cookies() = 0) -> /signin auto-login balik akun lama via
        tb_lt = '+ Akun' tak pernah benar-benar ganti akun (keluhan
        user). Kini: CDP level target (clearBrowserCookies +
        clearDataForOrigin) + kadaluarsakan tb_lt langsung di halaman."""
        def kerja():
            ok = False
            pesan = "gagal koneksi CDP"
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
                    for ctx in br.contexts:
                        try:
                            ctx.clear_cookies()
                        except Exception:
                            pass
                        for pg in ctx.pages:
                            try:
                                cds = ctx.new_cdp_session(pg)
                                cds.send("Network.clearBrowserCookies")
                                cds.send("Storage.clearDataForOrigin", {
                                    "origin": "https://www.edclub.com",
                                    "storageTypes":
                                        "local_storage,session_storage"})
                            except Exception:
                                pass
                            try:
                                pg.evaluate("""() => {
                                  document.cookie = 'tb_lt=; path=/;'
                                    + ' max-age=0';
                                  try { localStorage.removeItem('tb_lt'); }
                                  catch (e) {}
                                }""")
                            except Exception:
                                pass
                    br.close()
                    ok = True
                    pesan = "sesi dibersihkan"
            except Exception as e:
                pesan = str(e)[:80]
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
            # nama lama jangan tertahan di header setelah keluar; label
            # login menyala instan (keluhan user 15 Nov). Mode LOGIN
            # (bukan 'Login ulang'): akun yang mau di-login lewat + Akun
            # PASTI belum pernah di-login di mesin ini - user 15 Nov
            self._nama_profil = None
            self._perlu_login_paksa = True
            self._login_baru = True
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
        # LOG MASUK: dulu supervisor bisa mati BISU (thread mati sebelum
        # catat pertama = sesi '+ Akun tak jalan' tak terdiagnosis,
        # live 15 Nov: log tanpa satu baris pengawas pun)
        try:
            from .theme import LOG_FILE
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write("[WEBVIEW2] supervisor pengawas mulai\n")
        except Exception:
            pass
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
            # sesi zombie (sisa 2 cookie pelacak, tanpa cookie
            # identitas login) = jangan dipulihkan & jangan boot-redirect:
            # hasilnya cuma pantulin course->signin = kedip (12 Nov)
            if tersimpan and not any(
                    c.get("name") in _KUKI_IDENTITAS for c in tersimpan):
                catat(f"sesi simpanan tanpa identitas "
                      f"({len(tersimpan)} cookie) - lewati pulihkan")
                tersimpan = None
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
                        # NILAI guard: kuki tanpa tiket (tb_lt/rt) =
                        # bukan sesi (_cfuvid dsb. muncul terus dari
                        # CDN) - dulu menimpa sesi bagus dgn sampah
                        if (sid and sid != sesi_sid and sesi_bernilai(milik)
                                and "/signin" not in (url_terakhir
                                                      or "")):
                            sesi_sid = sid
                            _sesi_tulis(milik)
                            catat("sesi edclub tersimpan (%d kuki: %s)"
                                  % (len(milik), ",".join(sorted(
                                      c.get("name", "")
                                      for c in milik))))
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
                        cocok = pot in u
                        if pot == "accounts.google":
                            # butuh 2 tick beruntun: render pertama
                            # google masih pra-hidrasi (tema flip
                            # gelap->terang terlihat kalau cover
                            # diangkat telalu pagi - keluhan user 21 Nov)
                            if cocok:
                                self._oauth_tik = (getattr(self,
                                    "_oauth_tik", 0) + 1)
                                cocok = self._oauth_tik >= 2
                            else:
                                self._oauth_tik = 0
                        if cocok or (time.time() > batas):
                            self._oauth_tik = 0
                            self._tahan_putih = False
                            self._tahan = None
                            self._boot_selesai = True
                            self._boot_cover = None
                    # ---- boot cover: halaman LOGIN siap = angkat
                    # cover SEKETIKA (user langsung login - dulu cover
                    # menggantung 45 dtk di halaman login sambil nunggu
                    # pill profil yang tidak akan muncul di halaman
                    # login = 'stuck', keluhan user 19 Nov)
                    if getattr(self, "_boot_cover", None)                             and "/signin" in u:
                        try:
                            _login_siap = pg.evaluate(
                                "() => (document.body.innerText||'')"
                                ".includes('Login Individual Edition')")
                        except Exception:
                            _login_siap = False
                        if _login_siap:
                            self._boot_cover = None
                            self._boot_selesai = True
                            catat("[BOOT] halaman login siap - cover "
                                  "dibuka untuk login user")
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
                        _cover_log("login selesai -> tahan 12s")
                        self.tahan_halaman("/student/", 12.0)
                    # halaman login di tengah proses OAuth (relay/
                    # auth_callback) = TRANSIEN - user melihat kedipan
                    # signin setelah login (keluhan user Nov 2026).
                    # Cover sampai /student/ benar2 mendarat. TAPI: user
                    # sedang aktif meng-klik halaman = jangan tutup
                    # (permintaan user: halaman salah tak boleh terlihat,
                    # tapi input user lebih penting).
                    # DIHAPUS TOTAL (12 Nov 2026): cover "transien oauth"
                    # tak bisa dibedakan dr halaman login Google - Google
                    # MENEMPEL url callback edclub di dalam parameter
                    # continue-nya (encoded), jadi substring 'relay'/'
                    # auth_callback' tetap cocok di halaman identifier
                    # Google = kedip abu selagi user login. Kosmetik
                    # kedip sesudah login TAK LAYAK melawan form login
                    # yg harus terlihat. (Kedip pasca-login ditutup
                    # aturan transisi di bawah - itu cukup.)
                    if ("auth_callback" in u or "relay" in u):
                        self._oauth_cover_url = None
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
                        # rapikan spasi ganda dr tangkapan pill edclub
                        # ('Zafran  H' -> 'Zafran H'; dulu jadi nama
                        # simpanan lain = akun tampil 'tidak aktif'
                        # padahal sesinya sama - keluhan user 12 Nov)
                        nm = re.sub(r"\s+", " ", (nm or "")).strip()
                        if (getattr(self, "_pcv_aktif", False)
                                and not getattr(self, "_pcv_ganti",
                                                False)):
                            # cover profil: tandai halaman tujuan siap
                            # (pill profil = sudah login; /signin dgn
                            # form terender = halaman login siap)
                            if nm:
                                self._pcv_selesai = True
                            elif "/signin" in u:
                                try:
                                    _lpg = pg.evaluate(
                                        "() => (document.body.innerText"
                                        "||'').includes("
                                        "'Login Individual Edition')")
                                except Exception:
                                    _lpg = False
                                if _lpg:
                                    self._pcv_selesai = True
                        if nm and len(nm) <= 40:
                            if nm != getattr(self, "_nama_profil", None):
                                self._nama_profil = nm
                            # login ASLI terlihat (pill ada) = batal paksa
                            # login ASLI terlihat (pill ada) = batal paksa
                            # 'Login ulang' di header (dipasang saat + Akun
                            # / ganti akun; keluhan user 15 Nov: nama lama
                            # tertahan & lambat ganti) + mode login baru
                            # selesai (label balik ke 'Login ulang')
                            self._perlu_login_paksa = False
                            self._login_baru = False
                            # ---- JAGA tb_lt (akar 'harus relogin
                            # terus', live 15 Nov): SPA edclub MEMBUANG
                            # kuki tiket tb_lt saat boot (terbukti di
                            # log user: sesi tersimpan hanya '_cfuvid,
                            # rt'). rt kadaluarsa dengan diam = sesi
                            # mati TANPA cadangan = relogin. Simpanan
                            # akun ini punya tiket = suntikkan balik.
                            try:
                                _lt_ada = pg.evaluate(
                                    """() => !!(document.cookie.match(
                                        /(?:^|; )tb_lt=/)
                                      || localStorage.getItem('tb_lt'))""")
                            except Exception:
                                _lt_ada = True
                            if not _lt_ada:
                                for _n2, _m2, _p2 in _akun_semua_meta():
                                    if _n2 != nm:
                                        continue
                                    _lt = next(
                                        (c.get("value")
                                         for c in _m2.get("cookies", [])
                                         if c.get("name") == "tb_lt"),
                                        None)
                                    if _lt:
                                        try:
                                            _js = ("(t) => { document.cookie"
                                                   " = 'tb_lt=' +"
                                                   " encodeURIComponent(t)"
                                                   " + '; path=/;"
                                                   " max-age=31536000;"
                                                   " SameSite=Lax';"
                                                   " try { localStorage"
                                                   ".setItem('tb_lt', t)"
                                                   " } catch (e) {} }")
                                            pg.evaluate(_js, _lt)
                                            catat("tb_lt disuntik "
                                                  "balik (SPA "
                                                  "membuangnya)")
                                        except Exception:
                                            pass
                                    break
                            # JANGAN simpan di detik pertama setelah tukar
                            # akun: listener sesi belum menulis cookie akun
                            # baru -> cookie LAMA bisa tertulis atas nama
                            # akun baru (racun buku alamat). TANPA continue:
                            # dulu continue melompati sisa tick halaman ini
                            # (= nav_pending/back-button ikut tertahan 20
                            # dtk saat swap - keluhan 'delay quite long')
                            if time.time() - getattr(
                                    self, "_akun_swap_at", 0.0) >= 20:
                                try:
                                    cookies = json.load(open(
                                        _sesi_path(), encoding="utf-8"
                                        )).get("cookies") or []
                                except Exception:
                                    cookies = []
                                # sesi_bernilai: file berisi kuki sampah
                                # (_cfuvid) TIDAK boleh dianggap sesi hidup
                                if cookies and sesi_bernilai(cookies):
                                    akun_auto_simpan(nm, cookies)
                        else:
                            # TANPA pill di daftar/lesson: kalau MENETAP
                            # >8 dtk dalam 45 dtk pertama (profil belum
                            # login / tiket mati) -> /signin SEKALI -
                            # dulu dibiarkan menggantung logged-out
                            # ('midway redirecting', keluhan user 19 Nov)
                            if (not nm and "/signin" not in u
                                    and ("/course/" in u or "/lesson/" in u)
                                    and time.time() - getattr(
                                        self, "_boot_t", time.time()) < 45):
                                if not getattr(self, "_anon_sejak", 0.0):
                                    self._anon_sejak = time.time()
                                    catat("[BOOT] halaman tanpa pill "
                                          "- pantau 8 dtk")
                                elif (time.time() - self._anon_sejak > 8
                                      and time.time() - getattr(
                                          self, "_perlu_nav_t", 0) > 30):
                                    self._perlu_nav_t = time.time()
                                    self._anon_sejak = 0.0
                                    catat("[BOOT] daftar/lesson "
                                          "logged-out - ke /signin")
                                    try:
                                        self.ke_url(
                                            "https://www.edclub.com"
                                            "/signin")
                                    except Exception:
                                        pass
                            else:
                                self._anon_sejak = 0.0
                    elif perlu_raw and "/signin" in u and "edclub" in u.lower():
                        # ---- PENYELAMAT tb_lt DI /SIGNIN (pasangan jaga
                        # tb_lt di atas, live 15 Nov): pasca-swap / sesi
                        # mati, dokumen /signin membaca tiket SAAT LOAD
                        # (sebelum add_cookies restore) = lt0 kosong =
                        # fallback tiket TAK PERNAH menembak walau tiket
                        # ada di jar. Suntikkan tiket dari snapshot
                        # aktif + muat ulang: branch 3a baca ulang dan
                        # login sendiri tanpa user mengisi form.
                        if time.time() - getattr(
                                self, "_lt_selamat", 0.0) > 60:
                            try:
                                _lt_kosong = pg.evaluate(
                                    "() => !(document.cookie.match(/(?:^|; )"
                                    "tb_lt=/) || localStorage.getItem("
                                    "'tb_lt'))")
                            except Exception:
                                _lt_kosong = False
                            if _lt_kosong:
                                _nama2 = akun_aktif_nama()
                                for _n3, _m3, _p3 in _akun_semua_meta():
                                    if _n3 != _nama2:
                                        continue
                                    _lt3 = next(
                                        (c.get("value")
                                         for c in _m3.get("cookies", [])
                                         if c.get("name") == "tb_lt"),
                                        None)
                                    if _lt3:
                                        self._lt_selamat = time.time()
                                        try:
                                            pg.evaluate(
                                                "(t) => { document.cookie ="
                                                " 'tb_lt=' +"
                                                " encodeURIComponent(t) +"
                                                " '; path=/;"
                                                " max-age=31536000;"
                                                " SameSite=Lax';"
                                                " try { localStorage"
                                                ".setItem('tb_lt', t)"
                                                " } catch (e) {} }", _lt3)
                                        except Exception:
                                            pass
                                        try:
                                            pg.evaluate(
                                                "() => location.reload()")
                                            catat("tb_lt diselamatkan di"
                                                  " /signin - muat ulang")
                                        except Exception:
                                            pass
                                    break
                    # MODE HEMAT EFEK (bot jalan): matikan animasi,
                    # transisi & blur di SEMUA frame edclub - layar
                    # hasil/transisi halaman patah-patah di laptop
                    # kentang saat bot nyala (keluhan user 14 Nov).
                    # Bot berhenti = style dibuang, tampilan normal.
                    try:
                        from engine import state as _est
                        _perf = bool(getattr(_est, "BOT_JALAN", False))
                    except Exception:
                        _perf = False
                    try:
                        for f in pg.frames:
                            if _perf:
                                f.evaluate("""() => {
                                  if (!document.getElementById('tb-perf')) {
                                    const s = document.createElement('style');
                                    s.id = 'tb-perf';
                                    s.textContent = '*,*::before,*::after{' +
                                      'animation-duration:.001s!important;' +
                                      'animation-delay:0s!important;' +
                                      'transition-duration:0s!important;' +
                                      'transition-delay:0s!important;' +
                                      'scroll-behavior:auto!important}' +
                                      '*{backdrop-filter:none!important}';
                                    (document.documentElement ||
                                     document.body).appendChild(s);
                                  }
                                }""")
                            else:
                                f.evaluate("""() => {
                                  const s =
                                    document.getElementById('tb-perf');
                                  if (s) s.remove();
                                }""")
                    except Exception:
                        pass
                    # TOMBOL KEMBALI (permintaan user 15 Nov): hanya di
                    # halaman yang BISA bikin nyasar (signup/register +
                    # alur Google) - BUKAN halaman login utama (itu
                    # sudah 'rumah' alur login, tak ada gunanya back).
                    # Gaya = tombol bulat putih kiri-atas UI baru.
                    # PAKAI u (location.href hasil tick) BUKAN pg.url:
                    # metadata url playwright di sesi watcher basi ->
                    # _perlu selalu salah = tombol tak pernah muncul
                    # (bug live 15 Nov, log 'halaman: accounts.google'
                    # terbukti u benar).
                    try:
                        _u = (u or "").lower()
                        _perlu = (("edclub" in _u and any(
                            k in _u for k in ("signup", "register",
                                              "join")))
                                  or "accounts.google." in _u)
                        _sudah = getattr(self, "_back_on", False)
                        if _perlu and not _sudah:
                            catat(f"[BACK] pasang: {u[:50]}")
                            pg.main_frame.evaluate("""() => {
                              if (document.getElementById('tb-back')) return;
                              // CHEVRON SVG (bukan karakter font): glyph
                              // ‹ duduk rendah di dalam kotak hurufnya =
                              // 'a tiny bit more to the bottom' & hover
                              // scale melebar ke bawah-kanan (keluhan
                              // user 15 Nov). SVG = center sejati, scale
                              // simetris dari tengahnya sendiri.
                              const st = document.createElement('style');
                              st.id = 'tb-back-style';
                              st.textContent = [
                                '#tb-back{position:fixed;top:18px;'
                                + 'left:18px;z-index:2147483647;width:56px;'
                                + 'height:56px;border-radius:50%;border:none;'
                                + 'background:#fff;cursor:pointer;'
                                + 'display:flex;align-items:center;'
                                + 'justify-content:center;'
                                + 'box-shadow:0 2px 10px rgba(0,0,0,.22);'
                                + 'transition:background .15s,'
                                + 'box-shadow .15s;padding:0;}',
                                '#tb-back:hover{background:#f2f3f5;'
                                + 'box-shadow:0 3px 14px rgba(0,0,0,.3);}',
                                '#tb-back svg{display:block;'
                                + 'transform:scale(1);'
                                + 'transition:transform .18s;}',
                                '#tb-back:hover svg{'
                                + 'transform:scale(1.3);}',
                              ].join('');
                              (document.head || document.documentElement)
                                .appendChild(st);
                              const b = document.createElement('button');
                              b.id = 'tb-back';
                              b.title = 'Kembali';
                              b.setAttribute('aria-label', 'Kembali');
                              const NS =
                                'http://www.w3.org/2000/svg';
                              const sv = document.createElementNS(NS,
                                'svg');
                              sv.setAttribute('width', '26');
                              sv.setAttribute('height', '26');
                              sv.setAttribute('viewBox', '0 0 24 24');
                              const jln = document.createElementNS(NS,
                                'path');
                              jln.setAttribute('d',
                                'M14.5 5 L7.5 12 L14.5 19');
                              jln.setAttribute('fill', 'none');
                              jln.setAttribute('stroke', '#1f2126');
                              jln.setAttribute('stroke-width', '2.7');
                              jln.setAttribute('stroke-linecap',
                                'round');
                              jln.setAttribute('stroke-linejoin',
                                'round');
                              sv.appendChild(jln);
                              b.appendChild(sv);
                              b.onclick = () => history.back();
                              (document.body || document.documentElement)
                                .appendChild(b);
                            }""")
                            self._back_on = True
                            catat("[BACK] terpasang OK")
                        elif not _perlu and _sudah:
                            pg.main_frame.evaluate("""() => {
                              const b = document.getElementById('tb-back');
                              if (b) b.remove();
                              const st =
                                document.getElementById('tb-back-style');
                              if (st) st.remove();
                            }""")
                            self._back_on = False
                    except Exception as ex:
                        catat(f"[BACK] error: {repr(ex)[:70]}")
                    nav = getattr(self, "_nav_pending", None)
                    if nav:
                        self._nav_pending = None
                        # arahkan APAPUN halaman sekarang (dulu hanya
                        # kalau URL berisi 'edclub' - user duduk di
                        # accounts.google.com setelah login Google =
                        # nav '/signin' DIBUANG diam-diam, tombol '+
                        # Akun' kelihatan mati total, keluhan 12 Nov)
                        try:
                            pg.evaluate(
                                "() => location.href = %r" % nav)
                            catat(f"arahkan: {nav[:80]}")
                        except Exception as ex:
                            catat(f"arahkan gagal: {str(ex)[:80]}")
                        continue
                    if u != url_terakhir:
                        _sebelum = url_terakhir
                        url_terakhir = u
                        catat(f"halaman: {u[:100]}")
                        # COVER PUTIH post-login (permintaan user 15 Nov:
                        # 'they just need to see the login, put in their
                        # account, once they enter - bam, level list'):
                        # keluar dari /signin (form dikirim) = tutup
                        # proses auth_callback/relay/redirect dgn cover
                        # putih sampai daftar level tampil. Hitam terasa
                        # gagal, putih terasa loading.
                        # OAUTH HALUS (user 21 Nov): klik Google =
                        # cover gelap sampai form stabil; google ->
                        # google (identifier -> challenge) = cover juga
                        # (tiap dokumen google hidrasi gelap->terang);
                        # google -> callback/edclub = cover putih
                        # sampai edclub mendarat (dashboard sukses /
                        # login gagal utk retry)
                        _lu = (_sebelum or "").lower()
                        _nu = u.lower()
                        _gl_b = "accounts.google." in _lu
                        _gl_n = "accounts.google." in _nu
                        if _gl_n and not _gl_b:
                            self._oauth_tik = 0
                            self._tahan_putih = False
                            self._tahan = ("accounts.google",
                                           time.time() + 15)
                            catat("cover oauth naik (form google)")
                        elif _gl_b and _gl_n:
                            self._oauth_tik = 0
                            self._tahan_putih = False
                            self._tahan = ("accounts.google",
                                           time.time() + 12)
                            catat("cover oauth naik (langkah google)")
                        elif _gl_b and not _gl_n:
                            self._tahan_putih = True
                            self._tahan = ("edclub",
                                           time.time() + 60)
                            catat("cover putih oauth naik (callback)")
                        if (_sebelum and "/signin" in _sebelum
                                and "/signin" not in u
                                and "edclub" in u.lower()
                                and getattr(self, "_perlu_login", False)
                                and "accounts.google" not in u.lower()
                                and "auth_callback" not in u):
                            self._tahan = ("login-putih",
                                           time.time() + 30)
                            catat("cover putih post-login naik")
                    if getattr(self, "_boot_cover", None):
                        # tutup boot aktif: buka begitu daftar level
                        # tampil SUDAH LOGIN (pill profil ada), ATAU
                        # begitu halaman login tampil (user HARUS bisa
                        # melihat & mengisi form login - dulu cover
                        # nahan 45 dtk di atas halaman signin = layar
                        # abu, keluhan user 12 Nov: klik 'Masuk akun
                        # lain' dari popover -> abu 45 dtk), atau
                        # tunggu maksimal 45 dtk
                        selesai = False
                        try:
                            if "/signin" in u or "auth_callback" in u:
                                selesai = True
                            elif "/student/" in u:
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
                            _cover_log("bounce rute lama -> course/3")
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
        # kartu status tengah (Siap/Berjalan/dll) TIDAK ditaruh lagi:
        # state cukup lewat header; kartu lama menembus cover profil &
        # startup (keluhan user 19 Nov: 'remove all old states'). Widget
        # tetap disimpan demi kompatibilitas pemanggil lama.
        self._stage_widget = widget

    def _boot_anim(self):
        """LOADING BAR + persen 'Menyiapkan edclub…' di overlay tutup
        boot (permintaan user 21 Nov: spinner generik diganti bar yg
        merayap - satu wajah dgn cover ganti akun). after() murni Tk
        (thread UI) - dibatalkan saat overlay dibuka."""
        try:
            warna = self._overlay.cget("bg")
            # cover putih (transisi login) = teks & persen gelap
            putih = warna.lower() in ("#ffffff", "white",
                                      "systembuttonface")
            # bersihkan spinner/bar sisa panggilan sebelumnya
            for w in list(self._overlay.winfo_children()):
                if isinstance(w, (tk.Label, ttk.Progressbar)):
                    w.destroy()
            lbl = tk.Label(self._overlay, text="Menyiapkan edclub…",
                           font=("Segoe UI", 12),
                           fg="#5b6570" if putih else "#9aa6b8",
                           bg=warna)
            lbl.place(relx=0.5, rely=0.44, anchor="center")
            bar, pct = self._bar_dan_persen(self._overlay, warna, putih)
            val = {"v": 8.0}

            def tik():
                if self._boot_anim_job is None:
                    return      # sudah dibatalkan/dibuka
                # merayap ke 88% - 100% ditempuh saat halaman siap
                # (overlay ditutup watcher; widget ikut dihancurkan)
                if val["v"] < 88.0 and bar is not None:
                    val["v"] = min(88.0, val["v"] + 1.0)
                    try:
                        bar.configure(value=val["v"])
                        pct.configure(text=f"{int(val['v'])}%")
                    except Exception:
                        pass
                self._boot_anim_job = self.after(80, tik)

            self._boot_anim_job = self.after(100, tik)
        except Exception:
            pass

    def ke_url(self, url):
        """Arahkan halaman utama embed ke url. DUA jalur supaya '+ Akun'
        TIDAK MATI saat thread pengawas playwright bermasalah (live
        15 Nov: watcher tak pernah tersambung -> _nav_pending tak
        pernah dikonsumsi -> bersih-bersih cookie sukses tapi halaman
        tidak pindah = 'did nothing').
        1. LANGSUNG via .NET CoreWebView2.Navigate (panggilan
           Python->.NET dari thread UI = aman; BUKAN ExecuteScriptAsync
           yg terbukti sung). Bisa gagal saat webview belum siap.
        2. FLAG _nav_pending utk pengawas (cadangan; navigasi ganda ke
           URL sama = tak berbahaya)."""
        self._nav_pending = url
        if threading.current_thread().ident != getattr(self, "_ui_thr", None):
            return      # bukan thread UI - hanya flag, watcher urun
        try:
            core = self._ec.webview.CoreWebView2
            if core is not None:
                core.Navigate(url)
                self._nav_pending = None      # tidak perlu dijual ke watcher
                _cover_log(f"nav langsung: {url[:60]}")
        except Exception as ex:
            _cover_log(f"nav langsung gagal ({repr(ex)[:40]}) - watcher "
                       "urun")

    def set_on_ready(self, cb):
        self._on_ready = cb

    def buka(self, port, url, warna="#141519", cover=True,
             boot=True):
        """cover=False = jangan sembunyikan webview saat boot
        (dipakai ganti akun: user HARUS melihat halaman login
        kalau profil akunnya masih kosong)."""
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
            # webview baru = handler popup pywebview TERPASANG LAGI di
            # core baru. Reset penanda supaya _jaga mencabut ulang +
            # menyuntik anti-popup (dulu cuma dicabut di webview
            # pertama: klik Google setelah ganti akun lolos ke Edge
            # eksternal - keluhan user 21 Nov).
            self._popup_unsub = False
            self._anti_ct = 0
            try:
                # latar kontrol = warna app: masa warm-up renderer
                # (setelah reveal) menyatu, tidak tampak hitam
                from System.Drawing import ColorTranslator
                control.DefaultBackgroundColor =                     ColorTranslator.FromHtml("#101116")
            except Exception:
                pass
            self._chwnd = int(str(control.Handle))
            user32.SetParent(self._chwnd, self.winfo_id())
            self._pas_ukuran()
            self._mulai_detak_kondisi()
            # TUTUP BOOT (permintaan user: kilat 'belum login' saat buka
            # app membingungkan): kalau ada sesi tersimpan, webview
            # DISEMBUNYIKAN + overlay tertutup sampai pengawas melihat
            # pill profil (login sukses) - lalu app terbuka LANGSUNG di
            # daftar level sudah login. Timeout 45 dtk: sesi memang mati,
            # tampilkan seperti biasa (user login manual).
            ada_identitas = False
            if cover:
                try:
                    with open(_sesi_path(), encoding="utf-8") as f:
                        _c = (json.load(f) or {}).get("cookies") or []
                    ada_identitas = any(c.get("name") in _KUKI_IDENTITAS
                                        for c in _c)
                except Exception:
                    ada_identitas = os.path.exists(_sesi_path())
            if (cover and boot and os.path.exists(_sesi_path())
                    and ada_identitas):
                _cover_log("boot naik (sesi ada cookie identitas)")
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
            elif cover and not boot:
                # HANYA ganti akun; startup tanpa sesi
                # (boot=True) harus tetap tampil utk
                # login manual
                # ganti akun (boot=False): sembunyikan webview saat
                # lahir SAJA - PCV cover yang mengurus reveal, tanpa
                # mesin boot-cover (dulu cabang boot ikut menyala saat
                # ganti akun: webview disembunyikan ulang + reveal
                # nunggu watcher boot yang lambat = hitam panjang)
                try:
                    user32.ShowWindow(self._chwnd, 0)   # SW_HIDE
                except Exception:
                    pass
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
            # pre-warm cadangan: bangun webview utk profil LAIN saat
            # app idle -> ganti akun nanti instan (cold start terasa
            # cepat, keluhan user 21 Nov)
            self.after(25000, self._siapkan_cadangan)
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
        import traceback as _tb
        f = _tb.extract_stack()[-2]
        _cover_log(f"tahan_halaman({potongan!r}, {maks}s) "
                   f"dari {os.path.basename(f.filename)}:{f.lineno}")
        self._tahan_log = f"{potongan!r}@{int(time.time())}"
        self._tahan = (potongan, time.time() + maks)

    def _mulai_detak_kondisi(self):
        """Log kondisi tampil/sembunyi tiap 10 dtk - diagnosa siklus
        abu/normal (keluhan user 12 Nov 2026). Cari [COVER] di bot.log."""
        try:
            from .theme import LOG_FILE as _lf
        except Exception:
            return
        if getattr(self, "_detak_on", False):
            return
        self._detak_on = True

        def detak():
            try:
                hwnd = bool(self._chwnd) and bool(
                    user32.IsWindowVisible(self._chwnd))
                ov = "y" if self._overlay.winfo_ismapped() else "n"
                tahan = getattr(self, "_tahan", None)
                _cover_log(f"kondisi hwnd={int(hwnd)} overlay={ov} "
                           f"cover={bool(getattr(self, '_boot_cover', None))} "
                           f"tahan={tahan[0] if tahan else None}")
            except Exception:
                pass
            self.after(10000, detak)
        self.after(10000, detak)

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
        # ---- marker klik OAuth: angkat cover INSTAN (thread UI) -
        # dulu nunggu tick pengawas = flip tema google sempat terlihat
        try:
            core_j = self._ec.webview.CoreWebView2
            if core_j is not None:
                ttl_j = str(getattr(core_j, "DocumentTitle", "") or "")
                src_j = str(getattr(core_j, "Source", "") or "").lower()
                if "edclub.com/signin" in src_j:
                    self._oauth_mark = True
                if (getattr(self, "_oauth_mark", False)
                        and ttl_j.startswith("TB_OAUTH")
                        and not getattr(self, "_tahan", None)
                        and "accounts.google." not in src_j):
                    self._oauth_mark = False
                    self._oauth_tik = 0
                    self._tahan_putih = False
                    self._tahan = ("accounts.google",
                                   time.time() + 15)
                    print("[PCV] cover oauth naik (klik google)")
        except Exception:
            pass
        # ---- LIFT CEPAT via .NET Source (user 21 Nov: cover kelabu
        # terasa lama - dulu lift nunggu tick pengawas playwright ~2 dtk
        # dan sering gagal eval di webview baru). _jaga tick 400ms:
        # google stabil 2 tick, edclub langsung.
        tahan_j = getattr(self, "_tahan", None)
        if tahan_j and not getattr(self, "_boot_cover", None):
            try:
                core_k = self._ec.webview.CoreWebView2
                src_k = str(getattr(core_k, "Source", "") or "").lower()
                pot_j = tahan_j[0]
                cocok_j = False
                if pot_j == "accounts.google":
                    if "accounts.google." in src_k:
                        self._oauth_tik_j = (getattr(self,
                            "_oauth_tik_j", 0) + 1)
                        cocok_j = self._oauth_tik_j >= 2
                    else:
                        self._oauth_tik_j = 0
                elif pot_j == "edclub":
                    cocok_j = "edclub." in src_k
                if cocok_j or time.time() > tahan_j[1]:
                    self._oauth_tik_j = 0
                    self._tahan_putih = False
                    self._tahan = None
                    self._boot_selesai = True
                    self._boot_cover = None
            except Exception:
                pass
        # ---- cover tahan-halaman: buka bila diminta & belum terbuka
        tahan = getattr(self, "_tahan", None)
        if tahan and not getattr(self, "_boot_cover", None):
            pot, batas = tahan
            if time.time() <= batas and self._chwnd:
                _cover_log(f"naik (tahan {pot!r} sisa {batas - time.time():.0f}s)")
                self._boot_cover = time.time()
                self._boot_selesai = False
                try:
                    # PUTIH = fasa callback OAuth / transisi login ->
                    # daftar level (terasa loading); gelap = app.
                    putih = (getattr(self, "_tahan_putih", False)
                             or str(pot).startswith("login"))
                    self._overlay.configure(
                        bg="#ffffff" if putih else "#141519")
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
        if getattr(self, "_boot_selesai", False) and                 getattr(self, "_pcv_aktif", False):
            # profil switch sedang berjalan (cover pcv aktif): buang
            # status boot lama & JANGAN sentuh overlay/webview - dulu
            # jalur ini menghancurkan cover + menyalakan webview di
            # tengah switch = kedip + kartu Siap nongol (live 19 Nov)
            self._boot_selesai = False
            self._boot_cover = None
        elif getattr(self, "_boot_selesai", False):
            _cover_log(f"buka (selesai/timeout; tahan terakhir="
                       f"{getattr(self, '_tahan_log', None)})")
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
            # FULL height: webview mengisi sisa window sampai bawah -
            # footer lama DIHAPUS total (keluhan user 19 Nov: strip
            # hitam di bawah webview)
            user32.MoveWindow(self._chwnd, 0, 0,
                              max(self.winfo_width(), 50),
                              max(self.winfo_height(), 50), True)
        except Exception:
            pass

    def _on_resize(self, _ev=None):
        self.after_idle(self._pas_ukuran)
