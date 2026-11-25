// Ditulis tangan (bukan hasil gen_js.py): fitur v4 saja, tidak ada di 3.5.x.

/// Halaman & game tetap jalan saat app disembunyikan / diperkecil.
///
/// Jendela tersembunyi = browser menandai halaman 'hidden' dan berhenti
/// memanggil requestAnimationFrame. Game Phaser (Monster Attack dll)
/// berhenti total karena dua hal itu, jadi bot tak bisa memberi ketikan
/// dan level dilewati sebagai 'rusak' (uji live mac 4.0.8, level 94).
///
/// Dipasang di semua frame edclub (termasuk iframe game; bukan Cloudflare /
/// Google):
/// - document.hidden / visibilityState selalu 'terlihat', event
///   visibilitychange asli ditelan (game tidak masuk mode jeda);
/// - requestAnimationFrame: kalau halaman SUNGGUH tersembunyi, diganti
///   setTimeout ~60 fps; saat terlihat tetap rAF asli (tanpa beban).
const hiddenRunJs = r'''
(function(){
  try {
    if (window.__tb_vis) return;
    // hanya frame edclub (halaman, game *.edclub.app): pemeriksa bot
    // Cloudflare / Google tak boleh melihat document/rAF yang diubah
    if (!/(^|\.)(edclub\.com|edclub\.app|typingclub\.com)$/.test(location.hostname || '')) return;
    window.__tb_vis = 1;
    var proto = Document.prototype;
    var d = Object.getOwnPropertyDescriptor(proto, 'hidden');
    var asliHidden = d && d.get ? function(){ return d.get.call(document); }
                                : function(){ return false; };
    function pasang(nama, nilai) {
      try {
        Object.defineProperty(document, nama, {configurable: true, get: function(){ return nilai; }});
      } catch (e) {}
    }
    pasang('hidden', false);
    pasang('webkitHidden', false);
    pasang('visibilityState', 'visible');
    pasang('webkitVisibilityState', 'visible');
    // hanya event asli browser; event buatan antiPauseJs bot tetap lewat
    var telan = function(e){ if (e.isTrusted) e.stopImmediatePropagation(); };
    document.addEventListener('visibilitychange', telan, true);
    document.addEventListener('webkitvisibilitychange', telan, true);

    var raf = window.requestAnimationFrame;
    var caf = window.cancelAnimationFrame;
    if (typeof raf !== 'function') return;
    // id negatif = cadangan setTimeout (id rAF asli selalu positif)
    window.requestAnimationFrame = function(cb){
      if (!asliHidden()) return raf.call(window, cb);
      return -setTimeout(function(){ cb(performance.now()); }, 16);
    };
    window.cancelAnimationFrame = function(id){
      if (id < 0) clearTimeout(-id);
      else if (typeof caf === 'function') caf.call(window, id);
    };
  } catch (e) {}
})();
''';
