// Port engine/recovery.py: pulihkan halaman macet/kosong. Mode WebView2
// cuma punya SATU halaman: "tab baru" 3.5.x = halaman yang sama.
part of 'engine.dart';

extension Recovery on Engine {
  /// 3.5.x pindah ke tab lain yang punya kerjaan; di app native cuma ada
  /// satu halaman, jadi tidak pernah pindah.
  Future<bool> switchToPlayableTab() async => false;

  /// UTAMA: reload halaman yang sama. Level yang 3x dipulihkan tetap mati
  /// = rusak -> lewati sesuai urutan daftar.
  Future<bool> recoverAndRestartLesson() async {
    st.lastRecovery = now;
    // video/intro masih diputar = bukan halaman mati
    try {
      for (final f in allFrames()) {
        if (_truthy(await runJs(mediaPlayingJs, f))) {
          log('[RECOVERY] media masih diputar - reload ditunda');
          st.lastActionTime = now;
          return false;
        }
      }
    } catch (_) {}
    final target = (st.lastUrl.contains('.play') || st.lastUrl.contains('/lesson/'))
        ? st.lastUrl
        : null;
    if (target != null) {
      final n = (st.recoveryCounts[target] ?? 0) + 1;
      st.recoveryCounts[target] = n;
      if (n >= 3) {
        return skipToNextLesson('recovery berulang, level rusak');
      }
      try {
        await page.reload(timeout: 25);
        log('[RECOVERY] reload tab yang sama: ${tail(target)}');
        _resetTyping();
        st.lastUrl = lessonPlayUrl(page.url);
        st.lastActionTime = now;
        return true;
      } catch (e) {
        log('[RECOVERY] reload gagal (${_cut('$e', 60)}) - muat ulang lewat alamat');
      }
      try {
        await page.goto(lessonRouteUrl(target), timeout: 25);
        log('[RECOVERY] muat ulang lesson yang sama: ${tail(target)}');
      } catch (e) {
        log('[RECOVERY] gagal muat ulang: ${_cut('$e', 80)}');
        return false;
      }
      return _finishRecovery();
    }
    log('[RECOVERY] Halaman macet/kosong, membuka ulang...');
    // rentang aktif: kembali ke level sesi, bukan level terdepan akun
    var lanjut = 0;
    if (st.rangeReady && (st.levelStart > 1 || st.levelEnd > 0)) {
      lanjut = max(st.levelStart, st.rangeMaxSeen);
    }
    if (lanjut > 0 && levels.map.containsKey('$lanjut')) {
      try {
        await page.goto(levels.urlFor(lanjut), timeout: 25);
        log('[RECOVERY] kembali ke level $lanjut sesi ini');
        await _finishRecovery();
        return true;
      } catch (e) {
        log('[RECOVERY] gagal kembali ke level $lanjut (${_cut('$e', 60)}) - coba daftar');
      }
    }
    try {
      await page.goto(listUrl, timeout: 20);
    } catch (e) {
      log('[RECOVERY] gagal buka daftar: ${_cut('$e', 80)}');
      return false;
    }
    try {
      await page.waitForSelector('div.lsn_name', timeout: 15);
    } catch (_) {}
    dynamic clicked;
    try {
      clicked = await page.evaluate(recoveryListClickJs);
    } catch (_) {}
    if (!_truthy(clicked)) {
      log('[RECOVERY] baris pelajaran tidak ditemukan');
      return false;
    }
    log('[RECOVERY] membuka pelajaran: $clicked');
    return _finishRecovery();
  }

  void _resetTyping() {
    st.lastTypedText = '';
    st.stdLastRem = null;
    st.stdAttempts = 0;
  }

  Future<bool> _finishRecovery() async {
    for (var i = 0; i < 15; i++) {
      await sleep(1.0);
      if (lessonPlayUrl(page.url).contains('.play') || st.stop) break;
    }
    st.lastTypedText = '';
    st.lastUrl = lessonPlayUrl(page.url);
    st.lastActionTime = now;
    return true;
  }
}

String _cut(String s, int n) => s.length > n ? s.substring(0, n) : s;
