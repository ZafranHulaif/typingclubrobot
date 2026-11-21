// Port engine/lessons/intro.py: langkah intro "Type the f key" / "Press Enter".
part of '../engine.dart';

extension IntroLesson on Engine {
  /// Cadangan: klik mouse sungguhan tombol keyboard layar berlabel [key].
  Future<bool> _clickLabeledKey(String key) async {
    if (key.length != 1) return false;
    for (final fr in allFrames()) {
      try {
        final locs = fr.locator('[class*="key"], .keyboard *');
        final n = min(await locs.count(), 120);
        for (var i = 0; i < n; i++) {
          final el = locs.nth(i);
          final txt = (await el.innerText(timeout: 0.3)).trim();
          if (txt == key) {
            await el.click(timeout: 1.2);
            log("[Intro] klik tombol layar '$key' (cadangan)");
            return true;
          }
        }
      } catch (_) {
        continue;
      }
    }
    return false;
  }

  bool _sameIntro(dynamic a, dynamic b) =>
      a is Map && b is Map && a['key'] == b['key'] && a['type'] == b['type'];

  Future<bool> handleIntroSteps() async {
    if (st.introAttempts >= 8) return false;
    for (final fr in allFrames()) {
      dynamic res = await runJs(introJs, fr);
      if (res is! Map || res.isEmpty) continue;
      String? key = res['key'] as String?;
      if (res['type'] == 'type') {
        key = introKeyMap[key] ?? key;
        if (key == null || key.isEmpty || key.length > 12) continue;
      } else {
        key = 'Enter';
      }
      final sig = '${res['type']}|$key';
      if (sig != st.introSig) {
        st.introSig = sig;
        st.introAttempts = 0;
      }
      st.introAttempts += 1;
      // tunggu layar stabil dulu (menekan terlalu dini = keystroke hilang)
      final wait = st.introFlow ? 0.05 : 0.12;
      var stable = 0;
      for (var i = 0; i < 10; i++) {
        await sleep(wait);
        final cur = await runJs(introJs, fr);
        if (_truthy(cur) && _sameIntro(cur, res)) {
          stable += 1;
        } else {
          if (_truthy(cur)) res = cur;
          stable = 0;
        }
        if (stable >= 2) break;
      }
      await focusFrame(fr);
      log("[Intro] instruksi: ${res['type']} '$key' (coba ${st.introAttempts})");
      if (st.introAttempts >= 4 && st.introAttempts % 2 == 0) {
        await _clickLabeledKey(key);
      } else {
        try {
          if (key == 'Enter') {
            await page.keyboard.press('Enter');
          } else {
            await page.keyboard.type(key);
          }
        } catch (_) {
          return false;
        }
      }
      // tunggu instruksi berganti (poll 40 ms, maks 0.6 dtk)
      for (var i = 0; i < 15; i++) {
        await sleep(0.04);
        final cur = await runJs(introJs, fr);
        if (!_truthy(cur) || !_sameIntro(cur, res)) {
          st.bump('intro');
          st.introFlow = true;
          st.lastActionTime = now;
          return true;
        }
      }
      st.bump('intro');
      st.lastActionTime = now;
      return true;
    }
    st.introFlow = false;
    return false;
  }
}
