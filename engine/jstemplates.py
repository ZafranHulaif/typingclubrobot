import re

"""Template JavaScript yang disuntikkan ke halaman edclub
(deteksi state, baca sisa teks, anti-pause, dsb.)."""




PLAYABLE_CHECK_JS = r"""
// Apakah halaman ini punya pekerjaan untuk bot?
const clr = document.querySelectorAll('span.token_unit._clr, ._clr > span.token_unit').length;
const boxed = document.querySelectorAll('.boxed-line .boxed-char').length;
const canvas = document.querySelectorAll('canvas').length;
const done = !!document.querySelector('.lesson-complete, [class*="score" i], [class*="result" i]');
return {clr: clr, boxed: boxed, canvas: canvas, done: done};
"""



# ---------------------------------------------------------------------------
# Deteksi state per frame
# ---------------------------------------------------------------------------

DETECT_JS = r"""
const out = {std: null, mini: null, canvases: document.querySelectorAll('canvas').length, core: false};

// Penting: teks lesson diambil Hanya dari token _clr (belum diketik).
// Token salah (_err berisi karakter salah yang di-inject edclub ke teks)
// tidak boleh ikut - kalau ikut, ekstraksi terkorupsi dan semua salah.
// Efek samping positif: ini otomatis menangani lesson yang sebagian sudah
// diketik dan baris baru yang muncul progresif (cukup re-ekstrak).
const stdEls = document.querySelectorAll('span.token_unit._clr, ._clr > span.token_unit');
if (stdEls.length > 0) {
    const result = [];
    for (const e of stdEls) {
        const txt = e.innerText || e.textContent;
        if (!txt) continue;
        if (txt.includes('↵') || txt.includes('\n')) result.push('\n');
        else if (txt.includes('↹') || txt.includes('\t')) result.push('\t');
        else {
            // Run whitespace (>=2 nbsp/spasi berurutan) = Satu unit
            // indentasi: tekan Tab Sekali di lesson Tab:
            // 1 Tab = 1 token run, err=0; spasi per-char = salah).
            // Run 1 = spasi biasa. (dulu: ambil karakter pertama saja ->
            // nbsp mentah terkirim, engine diam = bot nyangkut di level 87.)
            let run = 0;
            for (const ch of txt) {
                if (ch === '\u00A0' || ch === ' ') { run++; continue; }
                if (run === 1) result.push(' ');
                else if (run >= 2) result.push('\t');
                run = 0;
                result.push(ch);
            }
            if (run === 1) result.push(' ');
            else if (run >= 2) result.push('\t');
        }
    }
    const t = result.join('');
    if (t.replace(/\s/g, '').length > 0) out.std = t;
}

if (!out.std) {
    // Tutorial boxed: hanya ekstrak Run Pending (trailing run dengan tanda
    // class sama dengan karakter terakhir) - sama seperti _clr di lesson
    // standar. Re-entry mid-lesson melanjutkan dari sisa, bukan retype all.
    const tspans = Array.from(document.querySelectorAll('.boxed-line > span'))
        .filter(sp => sp.querySelector('.boxed-char'));
    if (tspans.length && tspans.length < 200) {
        const tsig = sp => {
            const ch = sp.querySelector('.boxed-char');
            let line = '';
            try { const l = sp.closest('.boxed-line'); line = l ? l.className : ''; } catch (e) {}
            return (line + '|' + sp.className + '|' + ch.className).trim();
        };
        const tsigs = tspans.map(tsig);
        const tlast = tsigs[tsigs.length - 1];
        let ti = tsigs.length - 1;
        while (ti >= 0 && tsigs[ti] === tlast) ti--;
        // sertakan run Pendek (<=2) sebelum trailing run = karakter Aktif
        // (di-highlight sendiri oleh situs asli; tanpa ini karakter aktif
        // terjatuh dari ekstraksi -> urutan ketikan bergeser satu = desync)
        let tstart = ti + 1;
        if (ti >= 0) {
            let tj = ti;
            while (tj >= 0 && tsigs[tj] === tsigs[ti]) tj--;
            if (ti - tj <= 2) tstart = tj + 1;
        }
        const chars = [];
        for (let k = tstart; k < tspans.length; k++) {
            let c = (tspans[k].querySelector('.boxed-char').textContent || '').slice(0, 1);
            if (c === '\u00a0' || c === ' ') c = ' ';
            else c = c.trim();
            if (c) chars.push(c);
        }
        if (chars.length) out.tut = {text: chars.join('')};
    }

    const letterSels = ['.letter:not(.correct):not(.typed)', 'span[class*="letter"]:not(.correct)'];
    for (const sel of letterSels) {
        const els = document.querySelectorAll(sel);
        const chars = [];
        for (const e of els) {
            if (!(e.offsetWidth > 0 || e.offsetHeight > 0)) continue;
            const t = (e.textContent || '').trim();
            if (t.length === 1) chars.push(t);
            if (chars.length >= 20) break;
        }
        if (chars.length >= 2) { out.mini = {text: chars.join(''), source: sel}; break; }
    }
    if (!out.mini) {
        const wordSels = ['.word:not(.completed):not(.done)', '.arcade-word', '.game-word',
                          'span[class*="word"]', 'div[class*="word"]'];
        outer_words:
        for (const sel of wordSels) {
            for (const e of document.querySelectorAll(sel)) {
                if (!(e.offsetWidth > 0 || e.offsetHeight > 0)) continue;
                const t = (e.innerText || e.textContent || '').trim();
                if (t && t.length < 20 && /^[a-zA-Z\s]+$/.test(t) && t.replace(/\s/g, '').length >= 2) {
                    out.mini = {text: t, source: sel};
                    break outer_words;
                }
            }
        }
    }
}

if (!out.std && !out.mini && !out.tut) {
    const targets = [];
    try { if (window.core) { out.core = true; targets.push(window.core); } } catch (e) {}
    outer_core:
    for (const t of targets) {
        try {
            for (const k of Object.keys(t)) {
                let v; try { v = t[k]; } catch (e) { continue; }
                if (typeof v === 'string' && v.length > 1 && v.length < 100 && /^[a-zA-Z\s]+$/.test(v)) {
                    out.mini = {text: v, source: 'core.' + k};
                    break outer_core;
                }
            }
        } catch (e) {}
    }
}
return out;
"""


SCORE_JS = r"""
const t = (document.body ? document.body.innerText : '').toLowerCase();
if (t.includes('new key introduction')) return false;
if (/^type the[\s\S]{1,20}?\s+key/m.test(t.replace(/\u00a0/g, ' '))) return false;
if (t.includes('wpm') && (t.includes('accuracy') || t.includes('akurasi'))) return true;
const cont = document.querySelector('.navbar-continue');
return !!(cont && (cont.offsetWidth || cont.offsetHeight));
"""



# ---------------------------------------------------------------------------
# Penutup pop-up / iklan premium / achievement
# ---------------------------------------------------------------------------

OVERLAY_JS = r"""
const taken = [];
// Modal premium terlihat? Jangan klik tombol lanjut apa pun - di level
// premium klik "continue" edclub Membawa Tab ke Stripe Checkout
// .
const premModal = (() => {
    try {
        const dlgs = document.querySelectorAll('[class*="modal" i], [class*="popup" i], [class*="dialog" i], [role="dialog"]');
        for (const d of dlgs) {
            if (!(d.offsetWidth > 100 && d.offsetHeight > 80)) continue;
            const t = (d.innerText || '').toLowerCase();
            if (/premium|upgrade|subscription|subscribe|langganan|berlangganan|go pro|unlock all/.test(t)) return true;
        }
    } catch (e) {}
    return false;
})();
const visible = el => { try { return !!(el.offsetWidth || el.offsetHeight); } catch (e) { return false; } };
function doClick(el, why) { try { el.click(); taken.push(why); return true; } catch (e) { return false; } }

const CLOSE_TEXTS = ['x','×','✕','✖','close','tutup','no thanks','not now','maybe later','later',
                     'nanti saja','nanti','lewati','skip'];
const NEXT_TEXTS  = ['next','continue','lanjut','mulai','main','play','start','begin','selesai',
                     'claim','klaim','skip video','got it','ok','okay'];

const closeSels = ['.modal-close', '.close-btn', '.pop-close', 'button[class*="close" i]',
                   '[class*="modal"] [class*="close" i]', '[aria-label*="close" i]',
                   '[aria-label*="dismiss" i]', '[data-dismiss]', '[class*="dismiss" i]',
                   '[class*="achievement"] [class*="close" i]', 'svg[class*="close" i]',
                   '[class*="close" i][class*="icon" i]', '[class*="popup"] [class*="x" i]'];
outer1:
for (const sel of closeSels) {
    for (const el of document.querySelectorAll(sel)) {
        if (visible(el) && doClick(el, 'tutup:' + sel)) break outer1;
    }
}

if (taken.length === 0) {
    let introScreen = false;
    try {
        const bt = document.body ? document.body.innerText.toLowerCase() : '';
        introScreen = bt.includes('new key introduction') || /^type the[\s\S]{1,20}?\s+key/m.test(bt.replace(/\u00a0/g, ' '));
    } catch (e) {}
    if (!introScreen && !premModal) {
    const nextSels = ['.next-button', '.btn-continue', '.continue-button',
                      '[data-testid="lesson-next-btn"]', '.a-btn.next', '.navbar-continue'];
    outer2:
    for (const sel of nextSels) {
        for (const el of document.querySelectorAll(sel)) {
            if (visible(el) && doClick(el, 'lanjut:' + sel)) break outer2;
        }
    }
    }
}

if (!premModal) {
    const want = {};
    for (const t of NEXT_TEXTS) want[t] = true;
    outer3:
    for (const el of document.querySelectorAll('button, a, [role="button"], [class*="btn" i], [class*="button" i]')) {
        let txt = '';
        try { txt = (el.innerText || '').trim().toLowerCase(); } catch (e) {}
        if (!txt || txt.length > 14 || !want[txt] || !visible(el)) continue;
        try { if (el.closest('.typable, .token_unit, .boxed-typing-lines, .boxed-line, .TPGAME')) continue; } catch (e) {}
        // Jangan klik tombol "continue/next" di dalam kontainer premium/
        // upsell/checkout: itu CTA berbayar (pernah membawa bot ke Stripe
        // Checkout). Tombol lanjut yang sah ada di navbar, bukan di modal.
        try { if (el.closest('[class*="premium" i],[class*="upsell" i],[class*="paywall" i],[class*="checkout" i],[class*="stripe" i]')) continue; } catch (e) {}
        if (doClick(el, 'teks:"' + txt + '"')) break outer3;
    }
}

{
    const want = {};
    for (const t of CLOSE_TEXTS) want[t] = true;
    const MODAL_SEL = '[class*="modal" i],[class*="popup" i],[class*="dialog" i],[class*="overlay" i],[role="dialog"],[class*="premium" i],[class*="upsell" i],[class*="paywall" i],[class*="achiev" i],[class*="promo" i],[class*="banner" i]';
    outer3b:
    for (const el of document.querySelectorAll('button, a, span, div, [role="button"]')) {
        let txt = '';
        try { txt = (el.innerText || '').trim().toLowerCase(); } catch (e) {}
        if (!txt || txt.length > 18 || !want[txt] || !visible(el)) continue;
        try { if (el.closest('.typable, .token_unit, .boxed-typing-lines, .boxed-line, .TPGAME')) continue; } catch (e) {}
        let inModal = false;
        try { inModal = !!el.closest(MODAL_SEL); } catch (e) {}
        if (!inModal) continue;
        if (doClick(el, 'tutup-teks:"' + txt + '"')) break outer3b;
    }
}
return taken;
"""


ESC_FALLBACK_JS = r"""
const ev = new KeyboardEvent('keydown', {key: 'Escape', code: 'Escape', keyCode: 27,
                                          which: 27, bubbles: true, cancelable: true});
[window, document, document.body].forEach(t => { try { t.dispatchEvent(ev); } catch (e) {} });
return true;
"""


MODAL_HINT_JS = r"""
const dlgs = document.querySelectorAll('[class*="modal" i], [class*="popup" i], [class*="dialog" i], [role="dialog"]');
for (const d of dlgs) {
    if (!(d.offsetWidth > 100 && d.offsetHeight > 80)) continue;
    const t = (d.innerText || '').toLowerCase();
    const achievement = /achievement|badge unlocked|congratulation|selamat/.test(t);
    const premium = /premium|upgrade|subscription|subscribe|langganan|berlangganan|go pro|unlock all/.test(t);
    if (achievement || premium) return {achievement: achievement, premium: premium};
}
return null;
"""


PREMIUM_MODAL_JS = r"""
// Modal premium: return {x,y} = titik tombol X (edmodal-x) untuk klik
// mouse asli, atau {zombie:true} kalau modal fullscreen Tanpa X (iframe
// checkout Stripe sudah mengambil alih). di 2968: klik X
// -> edclub otomatis lanjut ke lesson berikutnya (perilaku yang sama
// dengan popup premium di akun teman: tutup = lanjut level).
// Catatan: Jangan blokir request Stripe - modal yang checkout-nya gagal
// termuat jadi zombie gelap menetap (ever terjadi: 'gelap' false alarm).
let modal = null;
for (const d of document.querySelectorAll('[class*="modal" i], [role="dialog"]')) {
    if (d.offsetWidth > 100 && d.offsetHeight > 80) { modal = d; break; }
}
if (!modal) return null;
let x = modal.querySelector('.edmodal-x');
if (!x) x = modal.querySelector('[class*="close" i], [aria-label*="close" i]');
if (x && (x.offsetWidth || x.offsetHeight)) {
    const r = x.getBoundingClientRect();
    const cx = r.left + r.width/2, cy = r.top + r.height/2;
    const top = document.elementFromPoint(cx, cy);
    if (top && (top === x || x.contains(top) || top.contains(x)) && !x.closest('iframe'))
        return {x: cx, y: cy};
}
for (const el of modal.querySelectorAll('span, div, a, button, i')) {
    if (!(el.offsetWidth || el.offsetHeight) || el.children.length > 1) continue;
    const t = (el.innerText || '').trim();
    if (t !== '\u00d7' && t !== '\u2715' && t.toLowerCase() !== 'x') continue;
    const r = el.getBoundingClientRect();
    if (r.width > 60 || r.height > 60) continue;
    const cx = r.left + r.width/2, cy = r.top + r.height/2;
    const top = document.elementFromPoint(cx, cy);
    if (top && (top === el || el.contains(top) || top.contains(el)) && !el.closest('iframe'))
        return {x: cx, y: cy};
}
for (const f of modal.querySelectorAll('iframe')) {
    if ((f.src || '').toLowerCase().includes('stripe')) return {zombie: true};
}
const mt = (modal.innerText || '').toLowerCase();
if (modal.offsetHeight > window.innerHeight * 0.5 &&
    /premium|upgrade|subscription|langganan|berlangganan|go pro|unlock all/.test(mt))
    return {zombie: true};
return null;
"""



BADGE_STREAK_JS = r"""
// Popup badge streak / pencapaian (live 23:33, level 662): '.badgebg'
// overlay 320x320 tanpa tombol tutup, teksnya ('5 Day Streak...') ada di
// Elemen Saudara (.badge_text) bukan di dalamnya - jadi selector modal
// lama ([class*=modal/popup/dialog]) tidak pernah cocok. Penutup yang
// Terbukti live: tekan ESC sungguhan (CDP keyboard). Return true kalau
// badge terlihat.
const bg = document.querySelector('.badgebg');
if (bg && (bg.offsetWidth > 50 || bg.offsetHeight > 50)) return true;
return false;
"""



# ---------------------------------------------------------------------------
# Deteksi intervensi user asli.
#
# Event input CDP milik bot punya isTrusted=false; tangan user menghasilkan
# isTrusted=true (tidak bisa dipalsukan dari JS/CDP). Listener di tiap
# frame edclub mencatat timestamp event trusted terakhir -> bot tahu
# persis kapan user sedang memegang halaman, dan mundur sampai user diam.
# (kasus: user klik tombol pengaturan saat bot mengetik -> engine
# kehilangan fokus, ketikan berhenti dikonsumsi, dan bot salah mengira
# 'selesai tanpa layar skor' lalu menekan tombol lanjut.)
# ---------------------------------------------------------------------------

USER_WATCH_JS = r"""
if (!window.__tb_watch) {
  window.__tb_watch = 1;
  window.__tb_user = 0;      // timestamp aktivitas user terakhir
  window.__tb_ignore = 0;    // abaikan event sampai waktu ini (klik bot)
  var rec = function(e){
    if (!e || !e.isTrusted) return;
    var now = Date.now();
    if (window.__tb_ignore && now < window.__tb_ignore) return;
    window.__tb_user = now;
  };
  // Mouse/Scroll Saja: input CDP bot punya isTrusted=true (diinjeksi di
  // level browser, tidak bisa dibedakan dari user) - keydown Tidak boleh
  // dipantau karena bot sendiri mengetik. Klik mouse bot ditutupi
  // lewat __tb_ignore yang dipasang sebelum bot mengklik.
  ['mousedown','mouseup','wheel','touchstart','contextmenu'].forEach(
    function(n){ window.addEventListener(n, rec, true); });
  window.addEventListener('blur', function(){ window.__tb_user = Date.now(); });
}
return (Date.now() - (window.__tb_user || 0)) / 1000;
"""



# ---------------------------------------------------------------------------
# Anti-pause: edclub men-pause lesson saat window blur (banner "Start Typing").
# Solusi: paksa hasFocus() selalu true + dispatch event focus + klik banner.
# ---------------------------------------------------------------------------

ANTI_PAUSE_JS = r"""
try { Document.prototype.hasFocus = function () { return true; }; } catch (e) {}
try { window.dispatchEvent(new Event('focus')); } catch (e) {}
try { document.dispatchEvent(new Event('focus')); } catch (e) {}
try { document.dispatchEvent(new Event('visibilitychange')); } catch (e) {}
const b = document.querySelector('.drop-banner');
if (b && (b.offsetWidth || b.offsetHeight)) {
    try { b.click(); } catch (e) {}
    return 'banner';
}
return true;
"""



QUIET_ALIVE_JS = r"""
// Versi Tanpa Klik: hanya patch fokus + dispatch event. Aman dipakai
// berulang selama mengetik.
try { Document.prototype.hasFocus = function () { return true; }; } catch (e) {}
try { window.dispatchEvent(new Event('focus')); } catch (e) {}
try { document.dispatchEvent(new Event('focus')); } catch (e) {}
try { document.dispatchEvent(new Event('visibilitychange')); } catch (e) {}
return true;
"""



# ---------------------------------------------------------------------------
# Level standar (+ hold-key while typing)
# ---------------------------------------------------------------------------

HOLD_LESSON_JS = r"""
for (const el of document.querySelectorAll('div, span, p')) {
    const t = (el.innerText || '').trim();
    if (!t || t.length > 120 || !el.offsetWidth) continue;
    const m = t.match(/^hold (?:down )?(?:the )?([a-z])\s+key[\s\S]*typing/i);
    if (m) return {key: m[1], instr: t.replace(/\n/g, ' ')};
}
return null;
"""



# Baca sisa teks yang masih harus diketik (hanya token _clr, urutan DOM).
READ_REMAINING_JS = r"""
const els = document.querySelectorAll('span.token_unit._clr');
if (!els.length) return null;
const out = [];
for (const e of els) {
    const txt = e.innerText || e.textContent;
    if (!txt) continue;
    if (txt.includes('↵') || txt.includes('\n')) out.push('\n');
    else if (txt.includes('↹') || txt.includes('\t')) out.push('\t');
    else {
        let run = 0;
        for (const ch of txt) {
            if (ch === '\u00A0' || ch === ' ') { run++; continue; }
            if (run === 1) out.push(' ');
            else if (run >= 2) out.push('\t');
            run = 0;
            out.push(ch);
        }
        if (run === 1) out.push(' ');
        else if (run >= 2) out.push('\t');
    }
}
return out.join('');
"""



ERR_COUNT_JS = r"""
return document.querySelectorAll('span.token_unit._err').length;
"""



STATE_JS = r"""
// Satu roundtrip untuk loop ketik: sisa teks (_clr) + jumlah salah (_err).
const out = [];
for (const e of document.querySelectorAll('span.token_unit._clr')) {
    const txt = e.innerText || e.textContent;
    if (!txt) continue;
    if (txt.includes('\u21b5') || txt.includes('\n')) out.push('\n');
    else if (txt.includes('\u21b9') || txt.includes('\t')) out.push('\t');
    else {
        let run = 0;
        for (const ch of txt) {
            if (ch === '\u00a0' || ch === ' ') { run++; continue; }
            if (run === 1) out.push(' ');
            else if (run >= 2) out.push('\t');
            run = 0;
            out.push(ch);
        }
        if (run === 1) out.push(' ');
        else if (run >= 2) out.push('\t');
    }
}
const err = document.querySelectorAll('span.token_unit._err').length;
return [out.join(''), err];
"""



START_BANNER_JS = r"""
// Klik banner "Start Typing" Sekali di awal lesson (state pause awal).
// Jangan pernah mengklik apa pun saat sedang mengetik (bisa reset lesson!).
const b = document.querySelector('.drop-banner');
if (b && (b.offsetWidth || b.offsetHeight)) {
    try { b.click(); return 'klik'; } catch (e) {}
}
return null;
"""



# sisa teks tutorial boxed, tanpa mengenal nama class edclub:
# engine boxed pasti menandai karakter selesai lewat class (di span, di
# .boxed-char, atau di .boxed-line induknya). Trik: gabungkan semua class
# tiap karakter jadi "tanda", lalu ambil run terakhir yang tandanya sama
# dengan tanda karakter terakhir (= run karakter yang masih pending).
# Ditambah info tanda: kalau semua karakter satu tanda & beda dari tanda
# pending yang dikenal -> layar sudah selesai (jangan type ulang!).
TUT_REMAIN_JS = r"""
const spans = Array.from(document.querySelectorAll('.boxed-line > span'))
    .filter(sp => sp.querySelector('.boxed-char'));
if (!spans.length) return null;
function sig(sp) {
    const ch = sp.querySelector('.boxed-char');
    let line = '';
    try { const l = sp.closest('.boxed-line'); line = l ? l.className : ''; } catch (e) {}
    return (line + '|' + sp.className + '|' + ch.className).trim();
}
const sigs = spans.map(sig);
const lastSig = sigs[sigs.length - 1];
let i = sigs.length - 1;
while (i >= 0 && sigs[i] === lastSig) i--;
// sertakan run Pendek (<=2) sebelum trailing run = karakter Aktif
// (di-highlight sendiri oleh situs asli; tanpa ini karakter aktif
// terjatuh dari ekstraksi -> urutan ketikan bergeser satu = desync)
let start = i + 1;
if (i >= 0) {
    let j = i;
    while (j >= 0 && sigs[j] === sigs[i]) j--;
    if (i - j <= 2) start = j + 1;
}
const chars = [];
for (let k = start; k < spans.length; k++) {
    let c = (spans[k].querySelector('.boxed-char').textContent || '').slice(0, 1);
    if (c === '\u00a0' || c === ' ') c = ' ';
    else c = c.trim();
    if (c) chars.push(c);
}
return {rem: chars.join(''), total: spans.length,
        firstSig: sigs[0], lastSig: lastSig,
        allSame: sigs.every(s => s === lastSig)};
"""



# ---------------------------------------------------------------------------
# Minigame Phaser (core.record_keydown_time) - sudah tanpa fokus sejak awal
# ---------------------------------------------------------------------------

PHASER_FEED_JS = r"""
const gs = [];
for (const g of (window.Phaser ? Phaser.GAMES : [])) {
    try {
        const st = g.state.states[g.state.current];
        if (st && st.core && typeof st.core.record_keydown_time === 'function') gs.push({g: g, st: st});
    } catch (e) {}
}
if (!gs.length) return null;
const pick = gs[gs.length - 1];
if (pick.g.paused) { try { pick.g.paused = false; } catch (e) {} }
const c = pick.st.core;
if (c.has_ended || !c.cur_char) return {fed: false, ended: !!c.has_ended};
const chr = c.cur_char.chr;
if (chr === undefined || chr === null || chr === '' || chr === '<-') {
    return {fed: false, ended: false};
}
c.record_keydown_time(chr);
return {fed: true, chr: chr, idx: c.cur_char_index, ended: !!c.has_ended};
"""


# Game multi-kata (pilih kata bebas): coba kandidat char dari semua kata
# yang belum selesai, bukan hanya cur_char yang berurutan.
PHASER_PROBE_JS = r"""
const gs = [];
for (const g of (window.Phaser ? Phaser.GAMES : [])) {
    try {
        const st = g.state.states[g.state.current];
        if (st && st.core && typeof st.core.record_keydown_time === 'function') gs.push({g: g, st: st});
    } catch (e) {}
}
if (!gs.length) return null;
const pick = gs[gs.length - 1];
if (pick.g.paused) { try { pick.g.paused = false; } catch (e) {} }
const c = pick.st.core;
if (c.has_ended) return {fed: false, ended: true};
const want = arg;
if (want) {
    c.record_keydown_time(want);
    return {fed: true, chr: want, idx: c.cur_char_index, word: c.cur_word_index,
            ended: !!c.has_ended};
}
// kumpulkan kandidat: huruf pertama tiap kata yang belum selesai
const cands = [];
let words_ok = false;
try {
    if (c.words && typeof c.words.length === 'number') {
        words_ok = true;
        for (const w of c.words) {
            if (!w || !w.char_list || w.completed) continue;
            const ch = w.char_list[w.index || 0] || w.char_list[0];
            if (ch && cands.indexOf(ch) < 0) cands.push(ch);
        }
    }
} catch (e) {}
if (!cands.length && c.cur_char) cands.push(c.cur_char.chr);
return {fed: false, cands: cands.slice(0, 8), words_ok: words_ok, idx: c.cur_char_index,
        word: c.cur_word_index, ended: false};
"""


# cek state tanpa memberi ketikan
PHASER_CHECK_JS = r"""
const gs = [];
for (const g of (window.Phaser ? Phaser.GAMES : [])) {
    try {
        const st = g.state.states[g.state.current];
        if (st && st.core) gs.push(st.core);
    } catch (e) {}
}
if (!gs.length) return null;
const c = gs[gs.length - 1];
return {idx: c.cur_char_index, word: c.cur_word_index, ended: !!c.has_ended};
"""



# ---------------------------------------------------------------------------
# Level "hold key" (instruksi murni, tanpa teks lesson)
# ---------------------------------------------------------------------------

HOLD_JS = r"""
const txt = (document.body ? document.body.innerText : '').toLowerCase();
if (!txt || txt.length > 400) return null;
const pats = [
    /press and hold (?:the )?(?:left |right )?([a-z]+(?: [a-z]+)?)/,
    /hold (?:down )?(?:the )?(?:left |right )?([a-z]+(?: [a-z]+)?)/,
    /tahan (?:tombol )?([a-z]+)/
];
for (const p of pats) {
    const m = txt.match(p);
    if (m) return {key: m[1], raw: m[0]};
}
return null;
"""


HOLD_KEY_MAP = {
    "space": " ", "space bar": " ", "spacebar": " ", "spasi": " ",
    "bar": " ", "shift": "Shift", "ctrl": "Control", "control": "Control", "alt": "Alt",
    "enter": "Enter", "return": "Enter", "tab": "Tab", "esc": "Escape", "escape": "Escape",
    "backspace": "Backspace", "delete": "Delete", "up": "ArrowUp", "down": "ArrowDown",
    "left": "ArrowLeft", "right": "ArrowRight",
}



# ---------------------------------------------------------------------------
# Keyboard layar (klik tombol highlight)
# ---------------------------------------------------------------------------

SCREENKEY_JS = r"""
const sels = ['[class*="key"][class*="highlight"]', '[class*="key"][class*="active"]',
              '.key.highlight', '.keyboard .next'];
for (const sel of sels) {
    for (const el of document.querySelectorAll(sel)) {
        if (!(el.offsetWidth || el.offsetHeight)) continue;
        const t = (el.innerText || el.textContent || '').trim().slice(0, 4);
        // Wajib berlabel: elemen "aktif" Tanpa teks bukan tombol keyboard -
        // pernah diklik dan menavigasi bot ke halaman daftar level.
        if (!t || t.length > 2) continue;
        try { el.click(); } catch (e) {}
        return {key: t, sel: sel};
    }
}
return null;
"""



# ---------------------------------------------------------------------------
# Level video: klik play (CDP click = user gesture valid), 16x, seek akhir
# ---------------------------------------------------------------------------

VIDEO_STATE_JS = r"""
const v = document.querySelector('video');
if (!v) return null;
return {paused: !!(v.ended || v.paused), dur: v.duration || 0, cur: v.currentTime || 0};
"""


VIDEO_SKIP_JS = r"""
const v = document.querySelector('video');
if (!v) return false;
try { v.muted = true; } catch (e) {}
// cukup Lompat ke akhir + play supaya event 'ended' menyala - tidak perlu
// playbackRate 16x (skip instan, tanpa percepatan yang menonta video)
try { const p = v.play(); if (p && p.catch) p.catch(() => {}); } catch (e) {}
try {
    if (v.duration && isFinite(v.duration) && v.duration > 2) {
        v.currentTime = Math.max(0, v.duration - 0.4);
    }
} catch (e) {}
return true;
"""



# ---------------------------------------------------------------------------
# Langkah intro "Type the f key" / "Press Enter"
# ---------------------------------------------------------------------------

INTRO_JS = r"""
for (const el of document.querySelectorAll('div, span, p')) {
    const t = (el.innerText || '').trim();
    if (!t || t.length > 90 || !el.offsetWidth) continue;
    const m = t.match(/^type the\s+([\s\S]+?)\s+key/i);
    if (m) return {type: 'type', key: m[1].trim().toLowerCase()};
    if (/^press enter/i.test(t)) return {type: 'enter'};
}
return null;
"""


INTRO_KEY_MAP = {"space": " ", "space bar": " ", "spacebar": " ", "spasi": " ",
                 "bar": " ", "enter": "Enter"}


# Path API yang 401-nya pasti berarti sesi mati (penyimpanan progress,
# data murid, sesi). Endpoint lain (mis. premium/entitlement) balas 401
# untuk akun gratis yang sedang login - : satu 401 seperti
# itu pernah memunculkan popup 'belum login' padahal user login.
SESI_PATH_RE = re.compile(r"(session|login|logout|/me\b|/me/|progress|student)",
                          re.I)



PROFILE_CHECK_JS = r"""
// Status login dari DOM. Sinyal live terverifikasi (akun Individual &
// portal sportal - sesi edclub Tidak disimpan di cookie, auth memakai
// header 'Authorization: Token' dari storage internal browser):
// 1..profile-name berisi nama user -> LOGIN (pasti).
// 2. li.dropdown > a.dropdown-toggle Bernama Orang di navbar -> LOGIN.
// (live: dashboard sportal & daftar.game menampilkan 'Zafran Hulaif'
// sebagai toggle; toggle UI lain = Courses/English/Save Progress/
// Typing Jungle - dikecualikan lewat daftar hitam + label bahasa).
// 3. Tautan 'Log in / Sign up' di header -> Logout (terverifikasi di
// halaman daftar.game logout).
const el = document.querySelector('.profile-name');
if (el) {
    const t = (el.textContent || '').trim();
    if (t && !/sign|log\s*in/i.test(t)) return 'in';
    return 'out';
}
const UI_TOGGLE = /^(courses?|english|save progress|more|help|settings?|language|lessons?|programs?|typing jungle|espa\S*|\d+)$/i;
const tog = document.querySelectorAll('li.dropdown > a.dropdown-toggle');
for (const a of tog) {
    if (a.querySelector('.selected-language-label')) continue;
    const t = (a.textContent || '').replace(/\s+/g, ' ').trim();
    if (!t || t.length > 40) continue;
    if (/log ?(in|out)|sign ?(in|up|out)/i.test(t)) continue;
    if (UI_TOGGLE.test(t)) continue;
    return 'in';
}
const adaLogin = [...document.querySelectorAll('a, button')].some(e =>
    /^(log in|login|sign in|sign up|signup|masuk|daftar)$/i
    .test((e.textContent || '').trim()));
if (adaLogin) return 'out';
return null;
"""

