// JS diagnosa tulisan tangan (bukan hasil gen_js.py).

/// Diagnosa (TB_KEYLOG, CI mac): rekam event tombol yang diterima tiap
/// frame ke window.__tbKeys (maks 400) utk dibandingkan dgn yang dikirim.
const keyLogJs = r"""
(() => {
  if (window.__tbKeys) return;
  const L = window.__tbKeys = [];
  const rec = (e) => {
    try {
      L.push([e.type.slice(0, 5), e.key, e.code, e.keyCode, e.repeat ? 1 : 0,
              e.isTrusted ? 1 : 0, e.defaultPrevented ? 1 : 0, e.data || '',
              (e.target && e.target.tagName) || '']);
      if (L.length > 400) L.splice(0, L.length - 400);
    } catch (x) {}
  };
  for (const t of ['keydown', 'keypress', 'keyup', 'beforeinput', 'input']) {
    window.addEventListener(t, rec, false);
  }
})();
""";
