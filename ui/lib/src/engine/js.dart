// HASIL GENERATE oleh ui/tool/gen_js.py - JANGAN diedit tangan.
// Sumber: payload JS Python 3.5.x (spesifikasi), disalin verbatim.
// ignore_for_file: constant_identifier_names

/// engine/jstemplates.py :: PLAYABLE_CHECK_JS
const playableCheckJs = r'''
// Apakah halaman ini punya pekerjaan untuk bot?
const clr = document.querySelectorAll('span.token_unit._clr, ._clr > span.token_unit').length;
const boxed = document.querySelectorAll('.boxed-line .boxed-char').length;
const canvas = document.querySelectorAll('canvas').length;
const done = !!document.querySelector('.lesson-complete, [class*="score" i], [class*="result" i]');
return {clr: clr, boxed: boxed, canvas: canvas, done: done};
''';

/// engine/jstemplates.py :: DETECT_JS
const detectJs = r'''
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
    try { if (window.core) {
      out.core = true;
      // CORE NEW-LOOK (punya cur_char/record_keydown_time) = milik
      // jalur balon/tutorial - fallback teks TIDAK BOLEH menebak:
      // dulu menebak field 'on_error: block' sbg teks lesson =
      // mengetik kata 'block' selamanya di tutorial sekolah,
      // memakan semua siklus (live 19 Nov, Dewi M lesson 127)
      if (window.core.cur_char !== undefined ||
          window.core.record_keydown_time) return out;
      targets.push(window.core);
    } } catch (e) {}
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
''';

/// engine/jstemplates.py :: SCORE_JS
const scoreJs = r'''
const t = (document.body ? document.body.innerText : '').toLowerCase();
if (t.includes('new key introduction')) return false;
if (/^type the[\s\S]{1,20}?\s+key/m.test(t.replace(/\u00a0/g, ' '))) return false;
if (t.includes('wpm') && (t.includes('accuracy') || t.includes('akurasi'))) return true;
const cont = document.querySelector('.navbar-continue');
return !!(cont && (cont.offsetWidth || cont.offsetHeight));
''';

/// engine/jstemplates.py :: ADHIDE_JS
const adhideJs = r'''
// Sembunyikan IKLAN di layar hasil (slot #adslot_*). Tombolnya bertuliskan
// 'Hide ×' TANPA class/id apa pun - selektor tutup generik ([class*=x] dsb.)
// tidak menangkapnya, jadi dulu iklan menutupi hasil sampai auto-dismiss
// +-5 detik dan malah memicu eskalasi ESC+klik mouse. Klik JS biasa cukup
// (handler DOM sederhana; terverifikasi live: iframe iklan lenyap seketika).
const tutup = [];
for (const slot of document.querySelectorAll('[id^="adslot"]')) {
    if (getComputedStyle(slot).display === 'none') continue;
    const btn = [...slot.querySelectorAll('button, a, [role="button"], div, span')]
        .find(b => (b.textContent || '').trim().replace(/\s+/g, ' ') === 'Hide ×');
    if (btn && (btn.offsetWidth || btn.offsetHeight)) {
        try { btn.click(); tutup.push(slot.id); } catch (e) {}
    }
}
return tutup;
''';

/// engine/jstemplates.py :: EDMODAL_JS
const edmodalJs = r'''
// Tutup modal Premium Edition (upsell langganan). Muncul sendiri di
// layar hasil SETELAH iklan disembunyikan (Chrome/Edge) dan di level
// premium. Tombolnya .edmodal-x - DIV polos tanpa role/button sehingga
// selektor tutup generik ([class*=close] dst.) melewatkannya, dan ESC
// tidak menutupnya (live). Klik JS dulu; kalau masih ada, kembalikan
// titik tengah .edmodal-x supaya pemanggil mengklik mouse CDP.
const m = document.querySelector('.edmodal');
if (!m || getComputedStyle(m).display === 'none') return null;
const x = m.querySelector('.edmodal-x');
if (x) { try { x.click(); } catch (e) {} }
return 'dicoba';
''';

/// engine/jstemplates.py :: EDMODAL_CEK_JS
const edmodalCekJs = r'''
return (() => {
    const m = document.querySelector('.edmodal');
    if (!m || getComputedStyle(m).display === 'none') return null;
    const x = m.querySelector('.edmodal-x');
    const r = (x || m).getBoundingClientRect();
    return {x: r.left + r.width / 2, y: r.top + r.height / 2,
            ada_x: !!x};
})();
''';

/// engine/jstemplates.py :: BLOK_POPUP_JS
const blokPopupJs = r'''
// Pasang blokir CSS permanen: slot iklan layar hasil (#adslot_*) dan modal
// Premium (.edmodal) TIDAK PERNAH dirender. Dulu tiap selesai level bot
// menunggu iklan muncul -> klik Hide -> modal muncul -> klik X -> lanjut
// (terasa idle/beku beberapa detik per level di Chrome/Edge; Brave bebas
// iklan berkat Shields sehingga tak pernah kena). Penutup klik di atas
// tetap ada sebagai fallback; keduanya no-op saat display:none.
// Sekali per dokumen (penanda di <html>).
const d = document.documentElement;
if (d.dataset.edblok) return false;
d.dataset.edblok = '1';
const s = document.createElement('style');
s.id = 'edblok-style';
s.textContent = '.edmodal, [id^="adslot"] { display: none !important; }';
(document.head || d).appendChild(s);
return true;
''';

/// engine/jstemplates.py :: BUKA_BLOK_JS
const bukaBlokJs = r'''
// Bongkar blokir CSS sesaat (kebalikan BLOK_POPUP_JS): modal premium
// yang diblokir display:none bisa TANPA tombol X - animasi tampilnya
// tidak pernah jalan sehingga X tak pernah dipasang (live: level
// premium di awal rentang terus di-skip). Setelah blokir dibongkar,
// modal tampil beneran dan jalur klik X yang terbukti bekerja.
// close_overlays memasang blokir lagi di iterasi berikutnya.
const st = document.getElementById('edblok-style');
const d = document.documentElement;
if (!st && !d.dataset.edblok) return false;
if (st) st.remove();
try { delete d.dataset.edblok; } catch (e) {}
d.removeAttribute('data-edblok');
return true;
''';

/// engine/jstemplates.py :: OVERLAY_JS
const overlayJs = r'''
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
''';

/// engine/jstemplates.py :: ESC_FALLBACK_JS
const escFallbackJs = r'''
const ev = new KeyboardEvent('keydown', {key: 'Escape', code: 'Escape', keyCode: 27,
                                          which: 27, bubbles: true, cancelable: true});
[window, document, document.body].forEach(t => { try { t.dispatchEvent(ev); } catch (e) {} });
return true;
''';

/// engine/jstemplates.py :: MODAL_HINT_JS
const modalHintJs = r'''
const dlgs = document.querySelectorAll('[class*="modal" i], [class*="popup" i], [class*="dialog" i], [role="dialog"]');
for (const d of dlgs) {
    if (!(d.offsetWidth > 100 && d.offsetHeight > 80)) continue;
    const t = (d.innerText || '').toLowerCase();
    const achievement = /achievement|badge unlocked|congratulation|selamat/.test(t);
    const premium = /premium|upgrade|subscription|subscribe|langganan|berlangganan|go pro|unlock all/.test(t);
    if (achievement || premium) return {achievement: achievement, premium: premium};
}
// Modal premium terblokir CSS (display:none) tetap dihitung: jalur
// 'layar gelap premium' (klik lanjut/skip urutan) harus jalan, bukan
// recovery penuh yang membawa bot keluar dari posisi.
const em = document.querySelector('.edmodal');
if (em) return {achievement: false, premium: true};
return null;
''';

/// engine/jstemplates.py :: PREMIUM_SKIP_JS
const premiumSkipJs = r'''
// Modal premium BARU (live 18 Nov): 'Upgrade to Pro to unlock lesson'
// (STEP 1 OF 2, kartu harga) - TIDAK punya .edmodal-x. Tombol ampuhnya
// 'Skip this lesson': satu klik = tutup modal DAN edclub lompat sendiri
// ke level berikutnya (live: 3013 -> 285 lanjot tanpa logika tambahan).
if (!/upgrade to pro|unlock this lesson/i.test(
    document.body.innerText || '')) return false;
const cari = Array.from(document.querySelectorAll('div'))
  .filter(d => /upgrade to pro|unlock this lesson/i.test(d.innerText || '')
       && d.children.length > 0
       && (d.innerText || '').length < 700);
const modal = cari[cari.length - 1];
if (!modal) return false;
const btn = Array.from(modal.querySelectorAll('button'))
  .find(b => /skip this lesson/i.test(b.innerText || ''));
if (!btn) return false;
btn.click();
return true;
''';

/// engine/jstemplates.py :: PREMIUM_MODAL_JS
const premiumModalJs = r'''
// Modal premium: return {x,y} = titik tombol X (edmodal-x) untuk klik
// mouse asli, atau {zombie:true} kalau modal fullscreen Tanpa X (iframe
// checkout Stripe sudah mengambil alih). di 2968: klik X
// -> edclub otomatis lanjut ke lesson berikutnya (perilaku yang sama
// dengan popup premium di akun teman: tutup = lanjut level).
// Catatan: Jangan blokir request Stripe - modal yang checkout-nya gagal
// termuat jadi zombie gelap menetap (ever terjadi: 'gelap' false alarm).
let modal = null;
// Modal Premium yang DIBLOKIR CSS (BLOK_POPUP_JS, display:none): rect-nya
// nol sehingga jalur klik mouse mustahil. X tetap bisa diklik via JS -
// handler edclub tetap menyala & lesson lanjut sendiri (perilaku
// terverifikasi live: tutup modal premium = lanjut level berikutnya).
const em = document.querySelector('.edmodal');
if (em && getComputedStyle(em).display === 'none') {
    const ex = em.querySelector('.edmodal-x, [class*="close" i], [aria-label*="close" i]');
    if (ex) { try { ex.click(); } catch (e) {} return {hidden: true}; }
    return null;
}
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
''';

/// engine/jstemplates.py :: BADGE_STREAK_JS
const badgeStreakJs = r'''
// Popup badge streak / pencapaian (live 23:33, level 662): '.badgebg'
// overlay 320x320 tanpa tombol tutup, teksnya ('5 Day Streak...') ada di
// Elemen Saudara (.badge_text) bukan di dalamnya - jadi selector modal
// lama ([class*=modal/popup/dialog]) tidak pernah cocok. Penutup yang
// Terbukti live: tekan ESC sungguhan (CDP keyboard). Return true kalau
// badge terlihat.
const bg = document.querySelector('.badgebg');
if (bg && (bg.offsetWidth > 50 || bg.offsetHeight > 50)) return true;
return false;
''';

/// engine/jstemplates.py :: USER_WATCH_JS
const userWatchJs = r'''
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
''';

/// engine/jstemplates.py :: ANTI_PAUSE_JS
const antiPauseJs = r'''
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
''';

/// engine/jstemplates.py :: QUIET_ALIVE_JS
const quietAliveJs = r'''
// Versi Tanpa Klik: hanya patch fokus + dispatch event. Aman dipakai
// berulang selama mengetik.
try { Document.prototype.hasFocus = function () { return true; }; } catch (e) {}
try { window.dispatchEvent(new Event('focus')); } catch (e) {}
try { document.dispatchEvent(new Event('focus')); } catch (e) {}
try { document.dispatchEvent(new Event('visibilitychange')); } catch (e) {}
return true;
''';

/// engine/jstemplates.py :: HOLD_LESSON_JS
const holdLessonJs = r'''
for (const el of document.querySelectorAll('div, span, p')) {
    const t = (el.innerText || '').trim();
    if (!t || t.length > 120 || !el.offsetWidth) continue;
    const m = t.match(/^hold (?:down )?(?:the )?([a-z])\s+key[\s\S]*typing/i);
    if (m) return {key: m[1], instr: t.replace(/\n/g, ' ')};
}
return null;
''';

/// engine/jstemplates.py :: READ_REMAINING_JS
const readRemainingJs = r'''
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
''';

/// engine/jstemplates.py :: ERR_COUNT_JS
const errCountJs = r'''
return document.querySelectorAll('span.token_unit._err').length;
''';

/// engine/jstemplates.py :: STATE_JS
const stateJs = r'''
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
''';

/// engine/jstemplates.py :: START_BANNER_JS
const startBannerJs = r'''
// Klik banner "Start Typing" Sekali di awal lesson (state pause awal).
// Jangan pernah mengklik apa pun saat sedang mengetik (bisa reset lesson!).
const b = document.querySelector('.drop-banner');
if (b && (b.offsetWidth || b.offsetHeight)) {
    try { b.click(); return 'klik'; } catch (e) {}
}
return null;
''';

/// engine/jstemplates.py :: TUT_REMAIN_JS
const tutRemainJs = r'''
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
''';

/// engine/jstemplates.py :: PHASER_FEED_JS
const phaserFeedJs = r'''
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
''';

/// engine/jstemplates.py :: PHASER_PROBE_JS
const phaserProbeJs = r'''
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
''';

/// engine/jstemplates.py :: PHASER_CHECK_JS
const phaserCheckJs = r'''
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
''';

/// engine/jstemplates.py :: HOLD_JS
const holdJs = r'''
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
''';

/// engine/jstemplates.py :: HOLD_KEY_MAP
const holdKeyMap = <String, String>{'space': ' ', 'space bar': ' ', 'spacebar': ' ', 'spasi': ' ', 'bar': ' ', 'shift': 'Shift', 'ctrl': 'Control', 'control': 'Control', 'alt': 'Alt', 'enter': 'Enter', 'return': 'Enter', 'tab': 'Tab', 'esc': 'Escape', 'escape': 'Escape', 'backspace': 'Backspace', 'delete': 'Delete', 'up': 'ArrowUp', 'down': 'ArrowDown', 'left': 'ArrowLeft', 'right': 'ArrowRight'};

/// engine/jstemplates.py :: SCREENKEY_JS
const screenkeyJs = r'''
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
''';

/// engine/jstemplates.py :: VIDEO_STATE_JS
const videoStateJs = r'''
const v = document.querySelector('video');
if (v) return {paused: !!(v.ended || v.paused), dur: v.duration || 0, cur: v.currentTime || 0};
// Pemain videojs belum termounting (level video baru dibuka dari daftar):
// splash tombol play besar menunggu klik pertama sebelum <video> ada.
const big = document.querySelector('.vjs-big-play-button');
if (big && (big.offsetWidth || big.offsetHeight)) return {splash: true};
return null;
''';

/// engine/jstemplates.py :: VIDEO_SKIP_JS
const videoSkipJs = r'''
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
''';

/// engine/jstemplates.py :: DIDOMI_JS
const didomiJs = r'''
// Banner consent Didomi (#didomi-host) menutupi halaman & menelan klik
// apa pun di bawahnya (live: klik gerbang audio ditolak - 'didomi-host
// intercepts pointer events'). Klik 'Agree and close'; consent
// tersimpan di cookie jadi jarang muncul lagi.
const b = document.getElementById('didomi-notice-agree-button');
if (b && (b.offsetWidth || b.offsetHeight)) { b.click(); return 'agree'; }
const n = document.getElementById('didomi-notice');
if (!n) return null;
const alt = [...n.querySelectorAll('button')].find(x =>
  /agree|accept/i.test(x.id + ' ' + (x.innerText || '')));
if (alt) { alt.click(); return 'alternatif'; }
return null;
''';

/// engine/jstemplates.py :: AUDIO_GATE_JS
const audioGateJs = r'''
// Gerbang audio 'Ready to start?': menahan mount player lesson sampai
// ada gesture user (AudioContext - warning console Chrome). Kliknya
// PAKE locator CDP (trusted), bukan JS click - deteksi di sini saja.
const b = document.querySelector('button[data-testid="audio-activation-gate"]');
return !!(b && (b.offsetWidth || b.offsetHeight));
''';

/// engine/jstemplates.py :: BIRTHDAY_JS
const birthdayJs = r'''
// Modal 'When is your birthday?' (sekali per akun): menahan lesson
// sampai diisi. Deteksi field bulan+tahun khas modal ini di dialog.
const dlg = document.querySelector('[role="dialog"]');
if (!dlg) return false;
return !!(dlg.querySelector('select[name="month"]') &&
          dlg.querySelector('input[name="year"]'));
''';

/// engine/jstemplates.py :: SPA_SKIP_JS
const spaSkipJs = r'''
// Tombol 'Skip' footer lesson UI baru (kanan bawah, teks PERSIS 'Skip'
// - bukan link aksesibilitas 'Skip to main content' di atas). Daftar
// pelajaran lama (.game) tak merender baris div.box-container lagi,
// jadi tombol edclub sendiri ini pengganti klik baris daftar.
for (const e of document.querySelectorAll('button, a, [role="button"]')) {
    const t = (e.innerText || '').trim();
    if (t !== 'Skip' || !(e.offsetWidth || e.offsetHeight)) continue;
    const r = e.getBoundingClientRect();
    if (r.y < 200 || r.width < 30) continue;   // footer saja
    return {x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2)};
}
return null;
''';

/// engine/jstemplates.py :: INTRO_JS
const introJs = r'''
for (const el of document.querySelectorAll('div, span, p')) {
    const t = (el.innerText || '').trim();
    if (!t || t.length > 90 || !el.offsetWidth) continue;
    const m = t.match(/^type the\s+([\s\S]+?)\s+key/i);
    if (m) return {type: 'type', key: m[1].trim().toLowerCase()};
    if (/^press enter/i.test(t)) return {type: 'enter'};
}
return null;
''';

/// engine/jstemplates.py :: INTRO_KEY_MAP
const introKeyMap = <String, String>{'space': ' ', 'space bar': ' ', 'spacebar': ' ', 'spasi': ' ', 'bar': ' ', 'enter': 'Enter'};

/// engine/jstemplates.py :: SESI_PATH_RE (pola regex; re.I=True)
const sesiPathRe = r'''(session|login|logout|/me\b|/me/|progress|student)''';
const sesiPathReIgnoreCase = true;

/// engine/jstemplates.py :: PROFILE_CHECK_JS
const profileCheckJs = r'''
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
// 4. UI baru (course/3, 2026+): marker lama sudah TIDAK ADA (live:
// profile-name=false, dropdown=0 padahal login) - nama user kini
// hidup di tombol pill kanan-atas (BUTTON.group > SPAN truncate,
// 'Zafran H'). Deteksi: tombol/link terlihat dgn teks mirip nama
// orang (2+ kata kapital, bukan label UI dikenal).
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
// sinyal 4: tombol nama-user di UI baru. Urutan SETELAH cek 'out'
// supaya halaman anon dgn tombol 'Sign in' tetap terbaca 'out'.
const tombol = [...document.querySelectorAll('button, [role="button"], a')];
for (const b of tombol) {
    if (!b.offsetParent) continue;
    const t = (b.textContent || '').replace(/\s+/g, ' ').trim();
    if (!t || t.length > 30) continue;
    if (/log ?(in|out)|sign ?(in|up|out)|masuk|daftar|get started|help/i.test(t)) continue;
    // nama mirip orang: minimal 2 kata, tiap kata diawali kapital
    // ('Zafran H' ok; 'Dashboard'/'Lessons' satu kata = tidak)
    if (!/^[A-Z][A-Za-z''.\-]+( [A-Z][A-Za-z''.\-]{0,19}){1,3}$/.test(t)) continue;
    if (UI_TOGGLE.test(t)) continue;
    return 'in';
}
return null;
''';

/// engine/jstemplates.py :: PROBE_FETCH_LOGIN_JS
const probeFetchLoginJs = r'''
// Cek status login TANPA navigasi & TANPA tab baru: fetch same-origin ke
// dashboard dari tab aktif, lalu baca penanda dari HTML mentahnya.
// 'out' pasti kalau server me-redirect fetch ke halaman signin (terverifikasi
// live: /sportal/ logout diarahkan ke /signin). 'in' hanya kalau nama profil
// sudah ada di HTML mentah (dashboard kadang merender navbar logout dulu lalu
// diganti client-side -> kembalikan '' = belum jelas, caller boleh fallback).
async () => {
  try {
    const r = await fetch('/sportal/', {credentials: 'include'});
    const u = (r.url || '').toLowerCase();
    if (/signin|\/login|signup/.test(u)) return 'out';
    const t = await r.text();
    const d = new DOMParser().parseFromString(t, 'text/html');
    const el = d.querySelector('.profile-name');
    if (el) {
      const x = (el.textContent || '').trim();
      if (x && !/sign|log\s*in/i.test(x)) return 'in';
      return 'out';
    }
    const UI_TOGGLE = /^(courses?|english|save progress|more|help|settings?|language|lessons?|programs?|typing jungle|espa\S*|\d+)$/i;
    const tog = d.querySelectorAll('li.dropdown > a.dropdown-toggle');
    for (const a of tog) {
      const t2 = (a.textContent || '').replace(/\s+/g, ' ').trim();
      if (!t2 || t2.length > 40) continue;
      if (/log ?(in|out)|sign ?(in|up|out)/i.test(t2)) return 'out';
      if (UI_TOGGLE.test(t2)) continue;
      return 'in';
    }
    return '';
  } catch (e) { return ''; }
}
''';

/// engine/levels.py :: _KLIK_LANJUT_JS
const klikLanjutJs = r'''() => {
    const t = [...document.querySelectorAll('button, .btn, [role=button]')];
    const b = t.find(x => /continue|lanjut|skip anyway/i.test(x.textContent || '')
                        && x.offsetParent !== null);
    if (b) { b.click(); return true; }
    return false;
}''';

/// engine/levels.py :: _DAFTAR_JS
const daftarJs = r'''(arg) => {
  const parse = aria => { const m = (aria||'').match(/Lesson (\\d+)/);
    return m ? parseInt(m[1], 10) : 0; };
  const rows = [];
  const baru = [...document.querySelectorAll('a[aria-label^="Lesson "]')];
  if (baru.length) {
    for (const a of baru) {
      const aria = a.getAttribute('aria-label') || '';
      rows.push({no: parse(aria), locked: /is locked/i.test(aria)});
    }
  } else {
    for (const r of document.querySelectorAll('div.box-container')) {
      const aria = r.getAttribute('aria-label') || '';
      rows.push({no: parse(aria),
                 locked: !((r.className||'') + '').includes('is_unlocked')});
    }
  }
  let awal = arg.awal || 0;
  if (arg.cari > 0) {
    for (let i = 0; i < rows.length; i++) {
      if (rows[i].no === arg.cari) { awal = Math.max(awal, i + 1); break; }
    }
  }
  let terkunci = -1;
  for (let i = awal; i < rows.length; i++) {
    if (arg.cari > 0 && rows[i].no && rows[i].no < arg.cari) continue;
    if (!rows[i].locked) return i;
    if (terkunci < 0) terkunci = i;
  }
  return terkunci;   // -1 = tidak ada baris setelah posisi ini
}''';

/// engine/lessons/ocr.py :: BALLOON_BRIDGE_JS
const balloonBridgeJs = r'''
const c = (typeof window.core !== 'undefined') ? window.core :
  ((window.Phaser && Phaser.GAMES && Phaser.GAMES.length &&
    Phaser.GAMES[0].state) ?
   Phaser.GAMES[0].state.states[Phaser.GAMES[0].state.current].core : null);
if (!c) return null;
if (c.has_ended) return {ended: true};
if (c.paused) { try { c.paused = false; } catch (e) {} }
const cur = c.cur_char ? String(c.cur_char.chr) : '';
if (!cur) return {wait: true, idx: c.cur_char_index,
                  mulai: !c.has_started};
if ('FEED') {
    // ARGUMEN WAKTU WAJIB (live 15 Nov malam, game yeti varian
    // baru): panggilan 1-argumen TIDAK mengkonsumsi huruf - game
    // mentok 'Type SPACE to begin' selamanya. performance.now()
    // terbukti diterima (huruf terkonsumsi, live).
    c.record_keydown_time(cur, 109);  // 109ms/huruf = 110wpm terukur
    return {fed: true, idx: c.cur_char_index};
}
return {chr: cur, idx: c.cur_char_index, ended: false};
''';

/// engine/lessons/ocr.py :: BALLOON_FEED_JS
const balloonFeedJs = r'''
const c = (typeof window.core !== 'undefined') ? window.core :
  ((window.Phaser && Phaser.GAMES && Phaser.GAMES.length &&
    Phaser.GAMES[0].state) ?
   Phaser.GAMES[0].state.states[Phaser.GAMES[0].state.current].core : null);
if (!c) return null;
if (c.has_ended) return {ended: true};
if (c.paused) { try { c.paused = false; } catch (e) {} }
if (!c.has_started) {
    // reset stat: duration sisa usia halaman (performance.now)
    // pernah dikira jeda = membengkak = wpm hancur (18 Nov)
    try { c.reset_stats(); } catch (e) {}
    // Dua varian mulai (live 15 Nov): (a) huruf-pertama - cur_char
    // sudah diisi (balloon valley, yeti 'b'...) = feed huruf itu;
    // (b) spasi - cur null (yeti 2970) = ketuk spasi. PENTING:
    // record(' ') TIDAK memulai varian spasi, dan event document
    //-lah yang didengar listener game (bukan window)
    // VARIAN BARU EDCLUB (live 15 Nov malam): setelah spasi
    // has_started TETAP false (huruf pertama langsung siap) -
    // dulu bila di sini = rantai mati 'Type SPACE' selamanya.
    // Kini: cuma tunggu bila cur_char memang belum ada.
    const c0 = c.cur_char ? String(c.cur_char.chr) : '';
    if (!c0) {
        document.dispatchEvent(new KeyboardEvent('keydown',
          {key: ' ', code: 'Space', keyCode: 32, which: 32,
           bubbles: true, cancelable: true}));
        setTimeout(() => document.dispatchEvent(new KeyboardEvent('keyup',
          {key: ' ', code: 'Space', keyCode: 32, which: 32,
           bubbles: true})), 40);
        if (!c.cur_char) return {fed: false, idx: -1, wait: true};
    }
}
let fed = '';
const t0 = Date.now();
return new Promise((selesai) => {
    const berhenti = () => selesai(
        fed ? {fed: true, idx: c.cur_char_index, huruf: fed} :
              {fed: false, idx: c.cur_char_index});
    const langkah = () => {
        if (c.has_ended || Date.now() - t0 > 3500) { berhenti(); return; }
        const cur = c.cur_char ? String(c.cur_char.chr) : '';
        if (!cur) { berhenti(); return; }
        const sebelum = c.cur_char_index;
        // dua argumen: lihat catatan di atas (varian baru wajib waktu)
        c.record_keydown_time(cur, 109);  // 109ms/huruf = 110wpm terukur
        // VARIAN BARU mengkonsumsi ASINKRON (tick game sendiri) - dulu
        // idx dicek seketika = selalu 'belum dikonsumsi' = rantai
        // berhenti tiap huruf & feeder lama ikut nyerang. Kini tunggu
        // maks 8x60ms sampai idx maju.
        let nunggu = 0;
        const cek = () => {
            if (c.cur_char_index !== sebelum) {
                fed += cur;
                setTimeout(langkah, 60);
                return;
            }
            if (++nunggu > 8 || c.has_ended) { berhenti(); return; }
            setTimeout(cek, 60);
        };
        cek();
    };
    langkah();
});
''';

/// engine/lessons/ocr.py :: _MAJU_LABEL
const majuLabel = r'''['next', 'move on', 'continue', 'lanjut', 'lanjutkan', 'play next', 'next level', 'keep going', 'done']''';

/// engine/lessons/ocr.py :: _MAJU_DASAR
const majuDasar = r'''
const maju = __LABEL__;
const cocok = (el) => {
  const t = (el.innerText || '').trim().toLowerCase();
  if (t && maju.some(w => t.includes(w))) return true;
  const a = ((el.getAttribute('aria-label') || '') + ' ' +
             (el.getAttribute('title') || '')).toLowerCase();
  return !!a && maju.some(w => a.includes(w));
};
for (const el of document.querySelectorAll('button, a, [role=button]')) {
  if (!cocok(el)) continue;
  const r = el.getBoundingClientRect();
  if (r.width < 30 || r.height < 12) continue;
  __AKSI__
}
return null;
''';

/// engine/lessons/ocr.py :: _CARI_ULANG_JS
const cariUlangJs = r'''
const ulang = ['try again', 'press enter', '→'];
for (const w of ulang) {
  for (const el of document.querySelectorAll('button, a, [role=button]')) {
    const t = (el.innerText || '').trim().toLowerCase();
    if (!t.includes(w)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 30) continue;
    el.click();
    return t;
  }
}
return null;
''';

/// level_data.py :: PETA (level -> id lesson kursus program-3)
const levelPeta = <int, int>{
  1: 116, 2: 117, 3: 118, 4: 119, 5: 120, 6: 121, 7: 122, 8: 2937,
  9: 124, 10: 125, 11: 126, 12: 127, 13: 128, 14: 129, 15: 2938, 16: 131,
  17: 132, 18: 133, 19: 134, 20: 4613, 21: 136, 22: 137, 23: 2940, 24: 140,
  25: 4615, 26: 142, 27: 143, 28: 4632, 29: 145, 30: 146, 31: 147, 32: 148,
  33: 149, 34: 2941, 35: 151, 36: 4616, 37: 153, 38: 2942, 39: 155, 40: 4633,
  41: 2943, 42: 158, 43: 4634, 44: 2944, 45: 2945, 46: 162, 47: 163, 48: 164,
  49: 165, 50: 2946, 51: 2947, 52: 168, 53: 4635, 54: 2948, 55: 2949, 56: 2950,
  57: 171, 58: 4636, 59: 173, 60: 2951, 61: 2952, 62: 2953, 63: 175, 64: 176,
  65: 4637, 66: 178, 67: 2954, 68: 2955, 69: 179, 70: 4638, 71: 181, 72: 2956,
  73: 2957, 74: 2958, 75: 183, 76: 4639, 77: 185, 78: 186, 79: 187, 80: 188,
  81: 189, 82: 2959, 83: 2960, 84: 2961, 85: 2962, 86: 191, 87: 192, 88: 8812,
  89: 194, 90: 195, 91: 196, 92: 197, 93: 2963, 94: 2964, 95: 199, 96: 200,
  97: 201, 98: 202, 99: 2965, 100: 2966, 101: 204, 102: 205, 103: 206, 104: 207,
  105: 2967, 106: 2968, 107: 209, 108: 210, 109: 211, 110: 212, 111: 2969, 112: 2970,
  113: 214, 114: 215, 115: 216, 116: 217, 117: 2971, 118: 2972, 119: 219, 120: 220,
  121: 221, 122: 2973, 123: 2974, 124: 2975, 125: 224, 126: 8813, 127: 2976, 128: 2977,
  129: 2978, 130: 2979, 131: 2980, 132: 2981, 133: 2982, 134: 2983, 135: 2984, 136: 2985,
  137: 8814, 138: 16716, 139: 226, 140: 227, 141: 228, 142: 229, 143: 2986, 144: 231,
  145: 2987, 146: 233, 147: 234, 148: 235, 149: 236, 150: 2988, 151: 2989, 152: 2990,
  153: 239, 154: 2991, 155: 241, 156: 242, 157: 2992, 158: 244, 159: 2993, 160: 246,
  161: 247, 162: 248, 163: 249, 164: 250, 165: 251, 166: 2994, 167: 253, 168: 254,
  169: 255, 170: 256, 171: 257, 172: 258, 173: 2995, 174: 260, 175: 261, 176: 262,
  177: 2996, 178: 263, 179: 264, 180: 265, 181: 2997, 182: 267, 183: 268, 184: 269,
  185: 270, 186: 271, 187: 272, 188: 3267, 189: 3268, 190: 3269, 191: 8815, 192: 3002,
  193: 3003, 194: 3004, 195: 3005, 196: 3006, 197: 3007, 198: 3008, 199: 3009, 200: 3010,
  201: 3011, 202: 8816, 203: 4950, 204: 276, 205: 277, 206: 278, 207: 3012, 208: 280,
  209: 281, 210: 282, 211: 283, 212: 3013, 213: 285, 214: 286, 215: 287, 216: 288,
  217: 3014, 218: 290, 219: 291, 220: 292, 221: 293, 222: 3015, 223: 295, 224: 296,
  225: 297, 226: 298, 227: 3016, 228: 300, 229: 301, 230: 302, 231: 303, 232: 3017,
  233: 8817, 234: 3018, 235: 3019, 236: 3020, 237: 3021, 238: 3022, 239: 3023, 240: 3024,
  241: 3025, 242: 3026, 243: 3027, 244: 8818, 245: 306, 246: 307, 247: 308, 248: 309,
  249: 310, 250: 311, 251: 312, 252: 313, 253: 314, 254: 315, 255: 316, 256: 317,
  257: 318, 258: 319, 259: 3028, 260: 3029, 261: 322, 262: 323, 263: 324, 264: 325,
  265: 326, 266: 327, 267: 328, 268: 329, 269: 330, 270: 331, 271: 332, 272: 333,
  273: 334, 274: 3030, 275: 3031, 276: 3032, 277: 3033, 278: 3034, 279: 3035, 280: 3036,
  281: 3037, 282: 3038, 283: 3039, 284: 3040, 285: 8819, 286: 337, 287: 338, 288: 339,
  289: 340, 290: 3041, 291: 342, 292: 343, 293: 344, 294: 345, 295: 3042, 296: 347,
  297: 348, 298: 349, 299: 350, 300: 3043, 301: 352, 302: 353, 303: 354, 304: 355,
  305: 3044, 306: 357, 307: 358, 308: 359, 309: 360, 310: 3045, 311: 362, 312: 363,
  313: 364, 314: 365, 315: 3046, 316: 8820, 317: 368, 318: 369, 319: 370, 320: 371,
  321: 372, 322: 373, 323: 374, 324: 375, 325: 376, 326: 377, 327: 378, 328: 379,
  329: 380, 330: 381, 331: 382, 332: 3047, 333: 384, 334: 385, 335: 386, 336: 387,
  337: 388, 338: 389, 339: 390, 340: 391, 341: 392, 342: 393, 343: 394, 344: 395,
  345: 396, 346: 397, 347: 3048, 348: 3049, 349: 3050, 350: 3051, 351: 3052, 352: 3053,
  353: 3054, 354: 3055, 355: 3056, 356: 3057, 357: 8821, 358: 399, 359: 3270, 360: 401,
  361: 402, 362: 3058, 363: 404, 364: 405, 365: 406, 366: 407, 367: 3059, 368: 409,
  369: 410, 370: 411, 371: 412, 372: 3060, 373: 414, 374: 415, 375: 416, 376: 417,
  377: 3061, 378: 419, 379: 420, 380: 421, 381: 422, 382: 3062, 383: 424, 384: 425,
  385: 426, 386: 427, 387: 3063, 388: 8822, 389: 430, 390: 431, 391: 432, 392: 433,
  393: 434, 394: 435, 395: 436, 396: 437, 397: 438, 398: 439, 399: 440, 400: 441,
  401: 442, 402: 443, 403: 444, 404: 445, 405: 446, 406: 447, 407: 448, 408: 449,
  409: 450, 410: 451, 411: 452, 412: 453, 413: 3064, 414: 455, 415: 456, 416: 457,
  417: 458, 418: 459, 419: 3065, 420: 3066, 421: 3067, 422: 3068, 423: 3069, 424: 3070,
  425: 3071, 426: 3072, 427: 3073, 428: 3074, 429: 8823, 430: 461, 431: 462, 432: 463,
  433: 464, 434: 3075, 435: 466, 436: 467, 437: 468, 438: 469, 439: 3076, 440: 4611,
  441: 472, 442: 473, 443: 474, 444: 3077, 445: 476, 446: 477, 447: 478, 448: 3078,
  449: 3079, 450: 481, 451: 482, 452: 483, 453: 484, 454: 3080, 455: 486, 456: 487,
  457: 488, 458: 489, 459: 3081, 460: 8824, 461: 3271, 462: 493, 463: 494, 464: 495,
  465: 3083, 466: 3084, 467: 498, 468: 499, 469: 500, 470: 3085, 471: 3086, 472: 503,
  473: 3087, 474: 3088, 475: 3089, 476: 3090, 477: 508, 478: 3091, 479: 3092, 480: 3093,
  481: 512, 482: 513, 483: 514, 484: 515, 485: 3094, 486: 3095, 487: 518, 488: 519,
  489: 520, 490: 3096, 491: 8825, 492: 523, 493: 524, 494: 525, 495: 526, 496: 3097,
  497: 3098, 498: 3099, 499: 530, 500: 531, 501: 3100, 502: 533, 503: 534, 504: 535,
  505: 3101, 506: 3102, 507: 3103, 508: 538, 509: 3104, 510: 540, 511: 541, 512: 3105,
  513: 543, 514: 544, 515: 545, 516: 546, 517: 3106, 518: 3107, 519: 549, 520: 550,
  521: 551, 522: 3108, 523: 3109, 524: 8826, 525: 3110, 526: 3111, 527: 3112, 528: 3113,
  529: 3114, 530: 3115, 531: 3116, 532: 3117, 533: 3118, 534: 3119, 535: 3120, 536: 3121,
  537: 3122, 538: 3123, 539: 3124, 540: 3125, 541: 3126, 542: 3127, 543: 3128, 544: 3129,
  545: 3130, 546: 3131, 547: 3132, 548: 3133, 549: 4612, 550: 3135, 551: 3136, 552: 3137,
  553: 3138, 554: 3139, 555: 3140, 556: 3141, 557: 8827, 558: 3142, 559: 3143, 560: 3144,
  561: 3145, 562: 3146, 563: 3147, 564: 3148, 565: 3149, 566: 3150, 567: 3151, 568: 3152,
  569: 3153, 570: 3154, 571: 3155, 572: 3156, 573: 3157, 574: 3158, 575: 3159, 576: 3160,
  577: 3161, 578: 3162, 579: 3163, 580: 3164, 581: 3165, 582: 3166, 583: 3167, 584: 3168,
  585: 3169, 586: 3170, 587: 3171, 588: 3172, 589: 3173, 590: 8828, 591: 3175, 592: 3176,
  593: 3177, 594: 3178, 595: 3179, 596: 3180, 597: 3181, 598: 3182, 599: 3183, 600: 3184,
  601: 3185, 602: 3186, 603: 3187, 604: 3188, 605: 3189, 606: 3190, 607: 3191, 608: 3192,
  609: 3193, 610: 3194, 611: 3195, 612: 3196, 613: 3197, 614: 3198, 615: 3199, 616: 3200,
  617: 3201, 618: 3202, 619: 3203, 620: 3204, 621: 8829, 622: 3206, 623: 3207, 624: 3208,
  625: 3209, 626: 3210, 627: 3211, 628: 3212, 629: 3213, 630: 3214, 631: 3215, 632: 3216,
  633: 3217, 634: 3218, 635: 3219, 636: 3220, 637: 3221, 638: 3222, 639: 3223, 640: 3224,
  641: 3225, 642: 3226, 643: 3227, 644: 3228, 645: 3229, 646: 3230, 647: 3231, 648: 3232,
  649: 3233, 650: 3234, 651: 3235, 652: 8830, 653: 3237, 654: 3238, 655: 3239, 656: 3240,
  657: 3241, 658: 3242, 659: 3243, 660: 3244, 661: 3245, 662: 3246, 663: 3247, 664: 3248,
  665: 3249, 666: 3250, 667: 3251, 668: 3252, 669: 3253, 670: 3254, 671: 3255, 672: 3256,
  673: 3257, 674: 3258, 675: 3259, 676: 3260, 677: 3261, 678: 3262, 679: 3263, 680: 3264,
  681: 3265, 682: 3266, 683: 8831, 684: 8832, 685: 52748,
};
