// Port engine/lessons/games.py: minigame DOM & Phaser (feed lewat core API).
part of '../engine.dart';

extension GamesLesson on Engine {
  Future<bool> handleMinigame(Frame frame, dynamic data) async {
    final t = now;
    final key = frame.url.isNotEmpty ? frame.url : frame.name;
    if (t - (st.lastFocusClick[key] ?? 0) > 30) {
      st.lastFocusClick[key] = t;
      await focusFrame(frame);
    }
    final text = data is Map ? '${data['text'] ?? ''}' : '';
    final src = data is Map ? '${data['source'] ?? '?'}' : '?';
    log("[Minigame/$src] Mengetik: '${text.length > 18 ? text.substring(0, 18) : text}'");
    if (!await typeChars(text, maxChars: 14)) return false;
    st.bump('mini');
    st.lastActionTime = now;
    await sleep(0.15);
    return true;
  }

  /// Modal premium di frame edclub: X ada -> klik mouse asli ('clicked');
  /// modal tanpa X -> Map info (mis. zombie); tak ada -> null.
  Future<Object?> premiumModalAction() async {
    for (final fr in await edclubFrames()) {
      final pm = await runJs(premiumModalJs, fr);
      if (pm is Map && _truthy(pm['hidden'])) {
        log('[Premium] modal tersembunyi (blokir CSS) - X diklik '
            'via JS, lanjut lesson berikutnya');
        return 'clicked';
      }
      if (pm is Map && pm['x'] != null) {
        try {
          await markBotClick();
          await page.mouse.click(pm['x'] as num, pm['y'] as num);
          log('[Premium] tombol X modal diklik - lanjut lesson berikutnya');
          return 'clicked';
        } catch (_) {}
      }
      if (_truthy(pm)) return pm;
    }
    return null;
  }

  /// Game beku berulang -> lewati level via tombol lanjut (klik asli).
  Future<bool> phaserTryAdvance() async {
    try {
      final loc = page
          .locator(".navbar-continue, a.navbar-continue, "
              "[data-testid='lesson-next-btn'], .a-btn.next, "
              '.btn-continue, .continue-button, .next-button')
          .first;
      if (await loc.count() > 0 && await loc.isVisible()) {
        await loc.click(timeout: 2);
        log('[Minigame/Phaser] game beku - level dilewati via tombol lanjut');
        st.phaserFreezeCount = 0;
        st.phaserFreezeClicked = false;
        return true;
      }
    } catch (_) {}
    for (final fr in await edclubFrames()) {
      final pt = await runJs(advanceTextBtnJs, fr);
      if (pt is Map) {
        try {
          await markBotClick();
          await page.mouse.click(pt['x'] as num, pt['y'] as num);
          log('[Minigame/Phaser] game beku - level dilewati via tombol berteks lanjut');
          st.phaserFreezeCount = 0;
          st.phaserFreezeClicked = false;
          return true;
        } catch (_) {}
      }
    }
    return false;
  }

  Future<bool> handlePhaserMinigame() async {
    // jembatan balon hidup = game milik jalur balon, jangan dobel feeder
    if (st.balloonBridgeFrame != null && now - st.balloonBridgeT < 4.0) return false;
    if (now < st.phaserCooldownUntil) return false;
    if (await premiumModalAction() == 'clicked') {
      st.lastActionTime = now;
      return true;
    }
    for (final fr in allFrames()) {
      var res = await runJs(phaserFeedJs, fr);
      if (res is! Map || !_truthy(res['fed'])) continue;
      log('[Minigame/Phaser] ${frameLabel(fr)}: memberi ketikan via core API...');
      var fedTotal = 1;
      var stalled = 0;
      var probed = false;
      var lastIdx = res['idx'];
      while (fedTotal < 150) {
        if (st.stop) break;
        await sleep(uniform(0.05, 0.11));
        res = await runJs(phaserFeedJs, fr);
        if (res is! Map || !_truthy(res['fed'])) break;
        final idx = res['idx'];
        if (idx == lastIdx) {
          stalled += 1;
          if (stalled >= 2 && await premiumModalAction() == 'clicked') {
            st.lastActionTime = now;
            return true;
          }
          if (stalled >= 4 && !probed) {
            // game multi-kata: coba huruf pertama tiap kata
            probed = true;
            dynamic info;
            try {
              info = await fr.evaluateWith('(arg) => {$phaserProbeJs}', null);
            } catch (_) {}
            var cands = (info is Map ? info['cands'] as List? : null) ?? const [];
            final wordsOk = info is Map && _truthy(info['words_ok']);
            if (!wordsOk) {
              log('[Minigame/Phaser] struktur words tidak dikenal '
                  '(bukan array char_list) - probe dilewati');
              cands = const [];
            } else {
              log('[Minigame/Phaser] kandidat multi-kata: $cands');
            }
            for (final cand in cands) {
              try {
                await fr.evaluateWith('(arg) => {$phaserProbeJs}', cand);
              } catch (_) {
                continue;
              }
              await sleep(0.3);
              final chk = await runJs(phaserCheckJs, fr);
              final newIdx = chk is Map ? chk['idx'] : null;
              if (newIdx != null && newIdx != idx) {
                log("[Minigame/Phaser] kata ditemukan via '$cand'");
                stalled = 0;
                lastIdx = newIdx;
                break;
              }
            }
          }
          if (stalled >= 8) {
            final urlNow = page.url;
            if (st.phaserFreezeUrl != urlNow) {
              st.phaserFreezeUrl = urlNow;
              st.phaserFreezeCount = 0;
              st.phaserFreezeClicked = false;
            }
            st.phaserFreezeCount += 1;
            if (!st.phaserFreezeClicked) {
              st.phaserFreezeClicked = true;
              try {
                final cv = fr.locator('canvas').first;
                if (await cv.count() > 0) {
                  await cv.click(timeout: 1.5);
                  log('[Minigame/Phaser] coba klik canvas (start game)');
                  await sleep(1.5);
                  final chk = await runJs(phaserCheckJs, fr);
                  if ((chk is Map ? chk['idx'] : null) != lastIdx) {
                    stalled = 0;
                    continue;
                  }
                }
              } catch (_) {}
            }
            if (st.phaserFreezeCount >= 2 && await premiumModalAction() == 'clicked') {
              st.lastActionTime = now;
              return true;
            }
            if (st.phaserFreezeCount >= 3) {
              if (await phaserTryAdvance()) {
                st.lastActionTime = now;
                return true;
              }
              if (await skipToNextLesson('minigame beku')) {
                st.lastActionTime = now;
                return true;
              }
            }
            log('[Minigame/Phaser] indeks tidak maju, jeda 6 detik '
                '(beku #${st.phaserFreezeCount})');
            st.phaserCooldownUntil = now + 6;
            break;
          }
        } else {
          stalled = 0;
          lastIdx = idx;
        }
        fedTotal += 1;
        st.lastActionTime = now;
      }
      st.bump('phaser', fedTotal);
      log('[Minigame/Phaser] $fedTotal karakter dikirim');
      st.lastActionTime = now;
      await sleep(0.4);
      return true;
    }
    return false;
  }
}
