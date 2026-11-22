// JS tulisan tangan (bukan hasil gen_js.py).

/// Fokuskan input ketik lesson kalau fokus masih di body (dipakai sebelum
/// menahan tombol di level 'tahan tombol').
const focusTypingInputJs = r'''
try {
  const a = document.activeElement;
  if (a && a !== document.body && (a.tagName === 'INPUT' || a.tagName === 'TEXTAREA')) return 'ada';
  const els = [...document.querySelectorAll('input, textarea')].filter((e) => {
    const t = (e.type || '').toLowerCase();
    return !['hidden', 'checkbox', 'radio', 'button', 'submit'].includes(t) && !e.disabled;
  });
  if (els.length !== 1) return 'tidak';
  els[0].focus();
  return 'fokus';
} catch (e) { return 'galat'; }
''';
