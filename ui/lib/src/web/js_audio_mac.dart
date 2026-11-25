// Ditulis tangan (bukan hasil gen_js.py): macOS saja, diagnosa.

/// Catat AudioContext yang dibuat halaman edclub (window.__tb_aud) supaya
/// app bisa melapor keadaannya ke bot.log ('running' = suara jalan,
/// 'suspended' = WebKit menahan suara). Uji Mac mini: tak ada suara.
/// Proxy = prototype & instanceof tetap asli.
const audioWatchJs = r'''
(function(){
  try {
    if (window.__tb_aud) return;
    if (!/(^|\.)(edclub\.com|edclub\.app|typingclub\.com)$/.test(location.hostname || '')) return;
    window.__tb_aud = [];
    ['AudioContext', 'webkitAudioContext'].forEach(function(n){
      var A = window[n];
      if (typeof A !== 'function') return;
      window[n] = new Proxy(A, {construct: function(t, args, nt){
        var c = Reflect.construct(t, args, nt);
        try { window.__tb_aud.push(c); } catch (e) {}
        return c;
      }});
    });
  } catch (e) {}
})();
''';

/// Ringkasan keadaan suara halaman utama utk bot.log.
const audioStateJs = r'''
(() => {
  const ac = (window.__tb_aud || []).map(c => c.state);
  const m = [...document.querySelectorAll('audio,video')].map(e =>
      (e.tagName[0] + (e.muted ? 'M' : '') + (e.paused ? 'P' : '>') + Math.round(e.volume * 10)));
  return 'konteks=[' + ac.join(',') + '] media=[' + m.join(',') + ']';
})()
''';
