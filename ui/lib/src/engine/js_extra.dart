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

/// <video> yang bukan isi level video (hiasan/latar: loop, kecil, atau
/// tak terlihat). Di WebKit mac halaman atas game balon punya <video>
/// seperti itu: dulu dilompati terus tiap putaran (log uji live 12:08,
/// 69x) dan game cuma dapat 14 huruf dalam 3 menit. Hasil: null = video
/// sungguhan / tidak ada video; selain itu = alasan diabaikan.
const videoHiasanJs = r'''
const v = document.querySelector('video');
if (!v) return null;
const r = v.getBoundingClientRect();
const luas = r.width * r.height;
if (v.loop) return 'loop ' + Math.round(r.width) + 'x' + Math.round(r.height);
if (!luas || luas < 40000) return 'kecil ' + Math.round(r.width) + 'x' + Math.round(r.height);
const cs = getComputedStyle(v);
if (cs.visibility === 'hidden' || cs.display === 'none' || +cs.opacity === 0) return 'tersembunyi';
return null;
''';
