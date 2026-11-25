// Ditulis tangan (bukan hasil gen_js.py): macOS saja.

/// Sentinel login di macOS: WebKit tidak punya CDP Network, jadi respons
/// 401/403 API edclub dibaca dari dalam halaman (fetch + XHR dibungkus)
/// lalu dilapor lewat handler 'tbnet'. Peniru CDP (wk_cdp.dart) mengubahnya
/// jadi Network.responseReceived, sama dgn Windows, jadi mesin bot tahu
/// sesi edclub mati walau halamannya diam (lesson diketik tapi tak
/// tersimpan).
///
/// Hanya frame edclub/typingclub: frame Cloudflare & Google tidak
/// disentuh (pemeriksa bot mereka bisa curiga pada fetch yang dibungkus).
const netWatchJs = r'''
(function(){
  try {
    if (window.__tb_net) return;
    if (!/(^|\.)(edclub|typingclub)\.com$/.test(location.hostname || '')) return;
    var mh = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.tbnet;
    if (!mh) return;
    window.__tb_net = 1;
    function lapor(jenis, status, url) {
      if (status !== 401 && status !== 403) return;
      try { mh.postMessage({type: jenis, status: status, url: String(url || '')}); } catch (e) {}
    }
    var f = window.fetch;
    if (typeof f === 'function') {
      window.fetch = function(input) {
        var u = (input && input.url) || input;
        return f.apply(this, arguments).then(function(r){
          lapor('Fetch', r.status, r.url || u);
          return r;
        });
      };
    }
    var X = XMLHttpRequest.prototype, buka = X.open, kirim = X.send;
    X.open = function(m, u) { this.__tb_u = u; return buka.apply(this, arguments); };
    X.send = function() {
      var x = this;
      x.addEventListener('loadend', function(){ lapor('XHR', x.status, x.responseURL || x.__tb_u); });
      return kirim.apply(this, arguments);
    };
  } catch (e) {}
})();
''';
