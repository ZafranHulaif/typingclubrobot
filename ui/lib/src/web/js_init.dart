// HASIL GENERATE oleh ui/tool/gen_js.py - JANGAN diedit tangan.
// Sumber: payload JS Python 3.5.x (spesifikasi), disalin verbatim.

/// engine/browser.py :: NO_POPUP_JS
const noPopupJs = r'''
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
''';

/// engine/browser.py :: _DUR_FIX_JS
const durFixJs = r'''
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
''';

/// gui/webview2_host.py :: _LOGIN_REDIRECT_JS
const loginRedirectJs = r'''
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
''';

/// gui/webview2_host.py :: _OAUTH_RELAY_PAGE_JS
const oauthRelayPageJs = r'''
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
''';

/// gui/webview2_host.py :: OAUTH_MARKER_JS
const oauthMarkerJs = r'''
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
''';
