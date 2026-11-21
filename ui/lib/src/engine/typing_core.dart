// Port engine/typing_core.py: mesin ketik CDP (jeda, burst, verifikasi),
// deteksi user asli, anti-pause, layar skor.
part of 'engine.dart';

extension TypingCore on Engine {
  /// Lepas modifier yang mungkin nyangkut (sisa Shift dari lesson hold).
  Future<void> clearModifiers() async {
    for (final k in const ['Shift', 'Control', 'Alt', 'Meta']) {
      try {
        await page.keyboard.up(k);
      } catch (_) {}
    }
  }

  /// Jeda per karakter dari target WPM (1 kata = 5 karakter), dikurangi
  /// overhead verifikasi terukur (maks 65% jeda ideal, sisa min 30%).
  double charDelay({bool slow = false, int? wpmCap}) {
    var wpm = st.speedWpm <= 0 ? 400 : st.speedWpm;
    if (wpmCap != null && wpm > wpmCap) wpm = wpmCap;
    if (slow) {
      st.lastCharDelay = uniform(0.14, 0.24);
      return st.lastCharDelay;
    }
    final ideal = 12.0 / wpm;
    final overhead = min(st.loopOverhead, ideal * 0.65);
    final base = max(ideal - overhead, ideal * 0.30);
    st.lastCharDelay = base * uniform(0.85, 1.15);
    return st.lastCharDelay;
  }

  /// Halaman bukan lesson lagi saat mengetik (user ambil alih / webview
  /// ditutup).
  bool lessonGone() {
    if (page.closed) return true;
    final url = page.url;
    return url.isNotEmpty && !url.contains('.play') && !url.contains('/lesson/');
  }

  /// Ketik beberapa karakter dgn pacing internal (tanpa verifikasi di
  /// sela). Overhead CDP per tombol diukur (EMA) lalu dikurangi dari jeda
  /// supaya laju akhir = target.
  Future<bool> typeBurst(String text, {int? wpm}) async {
    try {
      final w = wpm ?? (st.speedWpm > 0 ? st.speedWpm : 140);
      final idealMs = 12000.0 / w;
      final oh = st.burstOverheadMs;
      final ms = max(idealMs - oh, 8.0);
      final kbd = page.keyboard;
      var seg = StringBuffer();
      var nkey = 0;
      final t0 = now;
      Future<void> flush() async {
        if (seg.isEmpty) return;
        final s = seg.toString();
        await kbd.type(s, delayMs: ms);
        nkey += s.length;
        seg = StringBuffer();
      }

      for (final ch in text.split('')) {
        if (ch == '\t') {
          // type() tidak mengirim Tab utk '\t': tekan eksplisit
          await flush();
          await kbd.press('Tab');
          nkey += 1;
          await sleep(ms / 1000.0);
        } else {
          seg.write(ch); // '\n' -> Enter oleh type()
        }
      }
      await flush();
      if (nkey >= 4) {
        final lewat = (now - t0) * 1000.0;
        final ohBaru = min(max(lewat / nkey - ms, 0.0), 45.0);
        st.burstOverheadMs = 0.6 * oh + 0.4 * ohBaru;
      }
      return true;
    } catch (_) {
      return false;
    }
  }

  /// Ketik per karakter dgn jeda [charDelay]. Berhenti kalau STOP atau
  /// halaman bukan lesson lagi.
  Future<bool> typeChars(String text,
      {int? maxChars, bool slow = false, int? wpmCap}) async {
    final t = maxChars == null || maxChars >= text.length
        ? text
        : text.substring(0, maxChars);
    for (final ch in t.split('')) {
      if (st.stop) return false;
      if (lessonGone()) {
        st.statusUrl = page.url;
        log(page.closed
            ? '[BOT] Browser ditutup saat mengetik - berhenti'
            : '[USER] kamu pindah halaman - bot berhenti mengetik');
        return false;
      }
      try {
        if (ch == '\n') {
          await page.keyboard.press('Enter');
          await sleep(0.03 + 0.02 * rnd.nextDouble());
        } else if (ch == '\t') {
          await page.keyboard.press('Tab');
          await sleep(charDelay(slow: slow, wpmCap: wpmCap));
        } else {
          // spasi wajib type() (keypress/input penuh), bukan press()
          await page.keyboard.type(ch);
          await sleep(charDelay(slow: slow, wpmCap: wpmCap));
        }
      } catch (_) {
        return false;
      }
    }
    return true;
  }

  /// Panggil SEBELUM klik mouse CDP bot: jangan dihitung aktivitas user.
  Future<void> markBotClick([Frame? frame, int ms = 900]) async {
    await runJs('window.__tb_ignore = Date.now() + $ms; return 1;',
        frame ?? page.mainFrame);
  }

  /// User asli aktif dalam [batas] detik terakhir? (cache 0.5 dtk)
  Future<bool> userActive([double batas = 2.0]) async {
    final t = now;
    if (t - st.userWatchT < 0.5) return st.userWatchElapsed < batas;
    st.userWatchT = t;
    var terbaik = 1e9;
    try {
      for (final fr in await edclubFrames()) {
        final v = await runJs(userWatchJs, fr);
        if (v is num && v < terbaik) terbaik = v.toDouble();
      }
    } catch (_) {}
    st.userWatchElapsed = terbaik;
    return terbaik < batas;
  }

  /// User sedang menjelajah di luar lesson: tunggu; > 2 menit -> UI
  /// menanyakan lanjut/stop.
  Future<void> waitForUser(String url) async {
    if (st.waitUserUrl != url) {
      st.waitUserUrl = url;
      st.waitUserT = now;
      log('[USER] kamu sedang memakai browser bot - bot menunggu '
          '(lanjut otomatis begitu kamu diam / buka lesson)');
    } else if (now - st.waitUserT > 120 && !st.askNextLevel) {
      st.askNextLevel = true;
    }
    await sleep(0.5);
  }

  void userIdleAgain(String url) {
    if (st.waitUserUrl.isNotEmpty) {
      st.waitUserUrl = '';
      st.waitUserT = 0;
      st.askNextLevel = false;
      log('[USER] halaman tenang - bot lanjut bekerja.');
    }
  }

  /// Enter utk menu skor: maks 3x per 6 dtk, lalu jeda 15 dtk.
  Future<bool> pressEnterGuarded() async {
    final t = now;
    st.enterTimes.removeWhere((x) => !(t - x < 6));
    if (st.enterTimes.length >= 3) {
      log('[Skor] Enter berulang tanpa efek, jeda 15 detik');
      st.enterTimes
        ..clear()
        ..add(t + 15);
      return false;
    }
    if (st.enterTimes.isNotEmpty && st.enterTimes.first > t) return false;
    st.enterTimes.add(t);
    try {
      await page.keyboard.press('Enter');
      return true;
    } catch (_) {
      return false;
    }
  }

  /// Layar skor: Enter dulu; kalau berulang tanpa efek, klik tombol
  /// lanjut dgn mouse CDP sungguhan.
  Future<bool> advanceScoreScreen() async {
    if (await pressEnterGuarded()) {
      log('[Skor] Enter ditekan');
      return true;
    }
    for (final sel in const [
      '.navbar-continue',
      'a.navbar-continue',
      '.lesson-complete button.btn-primary',
      'button.continue',
    ]) {
      try {
        final loc = page.locator(sel);
        if (await loc.count() == 0) continue;
        await markBotClick();
        await loc.first.click(timeout: 1.5);
        log('[Skor] klik lanjut via mouse: $sel');
        return true;
      } catch (_) {
        continue;
      }
    }
    return false;
  }

  /// Fokus internal frame (window.focus + body.focus), TANPA klik.
  Future<void> focusFrame(Frame frame) => runJs(focusFrameJs, frame);

  /// Anti-pause di semua frame. True kalau banner diklik.
  Future<bool> keepAliveFrames() async {
    var clicked = false;
    for (final fr in await edclubFrames()) {
      if (await runJs(antiPauseJs, fr) == 'banner') clicked = true;
    }
    return clicked;
  }

  Future<void> keepAliveQuiet(Frame frame) => runJs(quietAliveJs, frame);

  /// ESC hanya kalau modal achievement/premium betul2 tampil.
  Future<void> escModalsOnly(Frame frame) async {
    final hint = await runJs(modalHintJs, frame);
    if (hint is Map && (_truthy(hint['achievement']) || _truthy(hint['premium']))) {
      await runJs(escFallbackJs, frame);
      log('[Pop-up] modal ditutup via ESC saat mengetik '
          '(${_truthy(hint['achievement']) ? 'achievement' : 'premium'})');
    }
  }

  /// Sisa teks lesson (token pending). null = tak ada token.
  Future<String?> readRemaining(Frame frame) async {
    final r = await runJs(readRemainingJs, frame);
    return r is String ? r : null;
  }

  Future<int?> countErrors(Frame frame) async {
    final n = await runJs(errCountJs, frame);
    return n is num ? n.toInt() : null;
  }

  /// (sisa, jumlah salah) dalam satu evaluate.
  Future<(String?, int?)> readState(Frame frame) async {
    final r = await runJs(stateJs, frame);
    if (r is! List || r.length != 2) return (null, null);
    return (r[0] is String ? r[0] as String : null, r[1] is num ? (r[1] as num).toInt() : null);
  }
}
