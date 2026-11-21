// HASIL GENERATE oleh ui/tool/gen_js.py - JANGAN diedit tangan.
// Sumber: payload JS Python 3.5.x (spesifikasi), disalin verbatim.
// JS yang di python ditulis di dalam fungsi (dicari lewat penanda unik).

/// engine/jsutil.py :: close_overlays_all_frames()
const closePointJs = r'''
// cari tombol tutup presisi + verifikasi tidak tertutup iframe
const cands = [];
for (const sel of ['[class*="popup" i] [class*="close" i]',
                   '[class*="modal" i] [class*="close" i]',
                   '[aria-label*="close" i]', '[data-dismiss]']) {
    for (const el of document.querySelectorAll(sel)) {
        if (!(el.offsetWidth || el.offsetHeight)) continue;
        const r = el.getBoundingClientRect();
        const cx = r.left + r.width/2, cy = r.top + r.height/2;
        const top = document.elementFromPoint(cx, cy);
        if (!top || (top !== el && !el.contains(top) && !top.contains(el))) continue;
        if (el.querySelector('iframe') || el.closest('iframe')) continue;
        cands.push({x: cx, y: cy});
    }
    if (cands.length) break;
}
window.__CLICKPT = cands.length ? cands[0] : null;
''';

/// engine/jsutil.py :: dump_debug_info()
const debugDumpJs = r'''
                return {
                    url: location.href.slice(0, 100),
                    canvases: document.querySelectorAll('canvas').length,
                    core: !!window.core,
                    gate: !!document.querySelector('button[data-testid="audio-activation-gate"]'),
                    didomi: !!document.getElementById('didomi-notice'),
                    birthday: !!document.querySelector('[role="dialog"] select[name="month"]'),
                    videos: document.querySelectorAll('video').length,
                    texts: (function(){
                        const out = [];
                        for (const s of document.querySelectorAll('span, div, p')) {
                            if (out.length >= 8) break;
                            const t = (s.innerText || '').trim();
                            if (t && t.length < 30 && s.children.length === 0 && s.offsetWidth > 0)
                                out.push(t.slice(0, 30));
                        }
                        return out;
                    })()
                };
            ''';

/// engine/typing_core.py :: focus_frame()
const focusFrameJs = r'''try{window.focus();if(document.body&&document.body.focus)document.body.focus();}catch(e){}''';

/// engine/lessons/games.py :: _phaser_try_advance()
const advanceTextBtnJs = r'''
const NX = ['next','continue','lanjut','mulai','selesai','skip','got it','ok'];
for (const el of document.querySelectorAll('button, a, [role="button"]')) {
    if (!(el.offsetWidth || el.offsetHeight)) continue;
    const txt = (el.innerText || '').trim().toLowerCase();
    if (!txt || txt.length > 14 || !NX.includes(txt)) continue;
    try { if (el.closest('[class*="premium" i],[class*="upsell" i],[class*="paywall" i],[class*="checkout" i],[class*="stripe" i]')) continue; } catch (e) {}
    const r = el.getBoundingClientRect();
    if (r.width < 25 || r.height < 12) continue;
    const cx = r.left + r.width/2, cy = r.top + r.height/2;
    const top = document.elementFromPoint(cx, cy);
    if (!top || (top !== el && !el.contains(top) && !top.contains(el))) continue;
    if (el.querySelector('iframe') || el.closest('iframe')) continue;
    return {x: cx, y: cy};
}
return null;
''';

/// engine/lessons/ocr.py :: try_balloon_core()
const readyStartJs = r'''
if (!/ready to start/i.test(document.body.innerText || ''))
  return false;
const el = Array.from(document.querySelectorAll('button'))
  .find(b => /^start\b/i.test((b.innerText || '').trim())
       && b.getBoundingClientRect().width > 30);
if (!el) return false;
el.click();
return true;
''';

/// engine/lessons/ocr.py :: try_balloon_core()
const canvasSkipJs = r'''
const c = document.querySelector('canvas');
if (c) { const r = c.getBoundingClientRect();
  const o = {bubbles: true, clientX: r.x + r.width / 2,
             clientY: r.y + r.height / 2};
  c.dispatchEvent(new MouseEvent('pointerdown', o));
  c.dispatchEvent(new MouseEvent('pointerup', o));
  c.dispatchEvent(new MouseEvent('click', o));
}''';

/// engine/lessons/ocr.py :: _core_bridge_frame()
const coreMainJs = r'''return !!(window.core || (window.Phaser && Phaser.GAMES && Phaser.GAMES.length));''';

/// engine/lessons/ocr.py :: _core_bridge_frame()
const coreIframeJs = r'''const h = String(location.href);if (!/phaser\d+|balloon/i.test(h)) return false;return !!(window.core || (window.Phaser && Phaser.GAMES && Phaser.GAMES.length));''';

/// engine/lessons/ocr.py :: _probe_iframe()
const probeIframeJs = r'''
const o = {phaser: typeof window.Phaser !== 'undefined'};
try {
  const g = window.Phaser ? Phaser.GAMES[0] : null;
  if (g) {
    o.ver = Phaser.VERSION;
    const st = g.state.states[g.state.current];
    o.cur = g.state.current;
    o.stateKeys = st ? Object.keys(st).filter(k => !k.startsWith('_'))
      .filter(k => /balloon|char|word|key|core|input|text|cursor|glow/i.test(k))
      .slice(0, 30) : null;
    o.hasCore = st ? !!st.core : null;
    if (st && st.core) {
      o.coreKeys = Object.keys(st.core).slice(0, 25);
      o.curChar = st.core.cur_char ? String(st.core.cur_char.chr) : null;
    }
  }
} catch (e) { o.err = String(e).slice(0, 100); }
return o;
''';

/// engine/lessons/ocr.py :: _balloon_frame()
const phaserPresentJs = r'''return !!(window.Phaser && Phaser.GAMES && Phaser.GAMES.length);''';

/// engine/levels.py :: _baca_unlock_js()
const bacaUnlockJs = r'''() => {
        const parse = aria => { const m = (aria||'').match(/Lesson (\d+)/);
          return m ? parseInt(m[1], 10) : 0; };
        const out = [];
        const baru = [...document.querySelectorAll('a[aria-label^="Lesson "]')];
        if (baru.length) {
            for (const a of baru)
                if (!/is locked/i.test(a.getAttribute('aria-label')||'')) {
                    const n = parse(a.getAttribute('aria-label')); if (n) out.push(n);
                }
        } else {
            for (const r of document.querySelectorAll('div.box-container')) {
                if (!((r.className||'') + '').includes('is_unlocked')) continue;
                const m = (r.getAttribute('aria-label')||'').match(/Lesson (\d+)/);
                if (m) out.push(parseInt(m[1], 10));
            }
        }
        return out;
    }''';

/// engine/levels.py :: _goto_level_via_daftar_isi()
const cariBarisJs = r'''(n) => {
              const parse = aria => { const m = (aria||'').match(/Lesson (\d+)/);
                return m ? parseInt(m[1], 10) : 0; };
              const baru = [...document.querySelectorAll('a[aria-label^="Lesson "]')];
              const rows = baru.length ? baru
                : [...document.querySelectorAll('div.box-container')];
              for (let i = 0; i < rows.length; i++) {
                const aria = baru.length ? rows[i].getAttribute('aria-label')
                                         : (rows[i].getAttribute('aria-label')||'');
                if (parse(aria) === n) return i;
              }
              return -1;
            }''';

/// engine/levels.py :: _goto_level_via_daftar_isi()
const scrollBawahJs = r'''() => window.scrollTo(0, document.body.scrollHeight)''';

/// engine/levels.py :: _lesson_hidup()
const lessonHidupJs = r'''() => ({c: document.querySelectorAll('canvas').length,v: !!document.querySelector('video'),b: document.body ? document.body.innerText.length : 0,u: location.href})''';

/// engine/levels.py :: _gate_atau_mulai()
const gateAtauMulaiJs = r'''() => !!document.querySelector(
                    'button[data-testid="audio-activation-gate"]')
                 || /sound can only play once you start/i
                    .test(document.body.innerText)''';

/// engine/levels.py :: _klik_baris_js()
const klikBarisJs = r'''(i) => {
  const baru = [...document.querySelectorAll('a[aria-label^="Lesson "]')];
  const rows = baru.length ? baru
    : [...document.querySelectorAll('div.box-container')];
  const r = rows[i];
  if (!r) return false;
  const klik = (!baru.length && r.querySelector('div.lsn_name')) || r;
  klik.click();
  return true;
}''';

/// engine/levels.py :: _level_label()
const levelLabelJs = r'''
const t = document.body ? document.body.innerText.slice(0, 400) : '';
const m = t.match(/Lesson\s+(\d+)/);
return m ? m[1] : null;
''';

/// engine/levels.py :: build_level_map()
const barisLabelJs = r'''(i) => {
                  const baru = [...document.querySelectorAll(
                    'a[aria-label^="Lesson "]')];
                  const rows = baru.length ? baru
                    : [...document.querySelectorAll('div.box-container')];
                  return rows[i] ? (rows[i].getAttribute('aria-label') || '') : '';
                }''';

/// engine/levels.py :: build_level_map()
const jumlahBarisJs = r'''() => document.querySelectorAll('a[aria-label^="Lesson "], div.box-container').length''';

/// engine/recovery.py :: recover_and_restart_lesson()
const mediaPlayingJs = r'''const v = document.querySelector('video,audio');return !!(v && !v.paused && !v.ended && v.currentTime > 0);''';

/// engine/recovery.py :: recover_and_restart_lesson()
const recoveryListClickJs = r'''
            () => {
                const rows = document.querySelectorAll('div.box-container.is_unlocked:not(.has_progress)');
                for (const r of rows) {
                    const nm = r.querySelector('div.lsn_name');
                    if (nm) { nm.click(); return (nm.innerText||'').trim(); }
                }
                const any = document.querySelector('div.lsn_name');
                if (any) { any.click(); return '(pertama) ' + (any.innerText||'').trim(); }
                return null;
            }
            ''';
