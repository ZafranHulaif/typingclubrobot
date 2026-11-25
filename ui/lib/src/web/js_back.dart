// Ditulis tangan (bukan hasil gen_js.py): fitur v4 saja, tidak ada di 3.5.x.

/// Tombol kembali di halaman login pihak ketiga (Google / Clever /
/// Microsoft). App tidak punya address bar, jadi user yang salah klik
/// "Sign in with ..." tidak tahu cara balik. Tombol bulat gaya edclub di
/// pojok kiri atas -> balik ke halaman edclub asalnya (/signin, atau
/// /signup kalau tadi klik "Sign up with ...").
///
/// Catatan: halaman Google pakai Trusted Types + CSP ketat, jadi tanpa
/// innerHTML dan tanpa atribut style (style lewat CSSOM boleh).
const authBackJs = r'''
(function(){
  try {
    if (window.top !== window) return;
    var h = (location.hostname || '').toLowerCase();

    // A) balik di edclub: /signin?tb_back=1 -> halaman asal klik OAuth
    //    (tb_oauth_from dicatat listener klik di skrip relay, origin edclub)
    if (/(^|\.)edclub\.com$/.test(h)) {
      var q = new URLSearchParams(location.search);
      if (q.get('tb_back') !== '1') return;
      var dari = '';
      try {
        dari = sessionStorage.getItem('tb_oauth_from') || '';
        sessionStorage.removeItem('tb_oauth_from');
      } catch (e) {}
      if (dari === 'signup') {
        location.replace('https://www.edclub.com/signup');
        return;
      }
      try { history.replaceState(null, '', location.pathname); } catch (e) {}
      return;
    }

    // B) tombol di halaman login pihak ketiga
    var auth = /(^|\.)accounts\.google\.com$/.test(h) ||
               /(^|\.)clever\.com$/.test(h) ||
               /(^|\.)login\.(microsoftonline|live|microsoft)\.com$/.test(h) ||
               /(^|\.)account\.live\.com$/.test(h);
    if (!auth) return;
    if (window.__tb_back) return;
    window.__tb_back = 1;

    var NS = 'http://www.w3.org/2000/svg';
    function gaya(el, s) {
      for (var k in s) el.style.setProperty(k, s[k], 'important');
    }
    function buat() {
      var b = document.createElement('button');
      b.id = 'tb-back';
      b.type = 'button';
      b.title = 'Kembali ke halaman login edclub';
      b.setAttribute('aria-label', 'Kembali ke halaman login edclub');
      gaya(b, {
        'position': 'fixed', 'top': '16px', 'left': '16px',
        'z-index': '2147483647', 'width': '44px', 'height': '44px',
        'margin': '0', 'padding': '0', 'border-radius': '50%',
        'border': '1px solid #e5e7eb', 'background': '#ffffff',
        'box-shadow': '0 1px 3px rgba(17,24,39,.12)',
        'display': 'flex', 'align-items': 'center',
        'justify-content': 'center', 'cursor': 'pointer',
        'transition': 'background-color .15s ease, transform .1s ease',
        'outline': 'none', 'box-sizing': 'border-box'
      });
      var svg = document.createElementNS(NS, 'svg');
      svg.setAttribute('width', '22');
      svg.setAttribute('height', '22');
      svg.setAttribute('viewBox', '0 0 24 24');
      svg.setAttribute('fill', 'none');
      svg.setAttribute('stroke', '#374151');
      svg.setAttribute('stroke-width', '2.25');
      svg.setAttribute('stroke-linecap', 'round');
      svg.setAttribute('stroke-linejoin', 'round');
      svg.setAttribute('aria-hidden', 'true');
      var p = document.createElementNS(NS, 'path');
      p.setAttribute('d', 'M19 12H5M11 18l-6-6 6-6');
      svg.appendChild(p);
      b.appendChild(svg);
      b.addEventListener('mouseenter', function(){ gaya(b, {'background': '#f3f4f6'}); });
      b.addEventListener('mouseleave', function(){ gaya(b, {'background': '#ffffff', 'transform': 'none'}); });
      b.addEventListener('mousedown', function(){ gaya(b, {'transform': 'scale(.96)'}); });
      b.addEventListener('mouseup', function(){ gaya(b, {'transform': 'none'}); });
      b.addEventListener('focus', function(){ gaya(b, {'box-shadow': '0 0 0 3px rgba(59,130,246,.35)'}); });
      b.addEventListener('blur', function(){ gaya(b, {'box-shadow': '0 1px 3px rgba(17,24,39,.12)'}); });
      b.addEventListener('click', function(ev){
        ev.preventDefault();
        ev.stopPropagation();
        location.href = 'https://www.edclub.com/signin?tb_back=1';
      }, true);
      return b;
    }
    var tombol = null;
    function pasang() {
      try {
        if (!document.body) return;
        if (!tombol) tombol = buat();
        if (!tombol.isConnected) document.body.appendChild(tombol);
      } catch (e) {}
    }
    if (document.body) pasang();
    else document.addEventListener('DOMContentLoaded', pasang);
    // halaman login Google/Microsoft = SPA, body bisa dirender ulang
    setInterval(pasang, 1000);
  } catch (e) {}
})();
''';
