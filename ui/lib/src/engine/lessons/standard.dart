// Port engine/lessons/standard.py: level ketik standar, verifikasi per
// burst (tidak boleh salah; salah -> mundur & ketik ulang pelan).
part of '../engine.dart';

extension StandardLesson on Engine {
  Future<bool> handleStandard(Frame frame, dynamic text) async {
    // level terkunci premium: modal menutupi lesson -> lewati
    for (final fr in allFrames()) {
      final hint = await runJs(modalHintJs, fr);
      if (hint is Map && _truthy(hint['premium'])) {
        log('[Premium] level terkunci premium - lewati via tombol lanjut');
        try {
          await markBotClick();
          await page.locator('.navbar-continue, a.navbar-continue').first.click(timeout: 2.5);
        } catch (_) {}
        st.lastActionTime = now;
        return true;
      }
    }
    final hold = await runJs(holdLessonJs, frame);
    final holdKey = hold is Map ? hold['key'] as String? : null;

    var rem = await readRemaining(frame);
    if (rem == null) return false;
    // anti-busur: teks sama & sudah 3x -> diam 8 dtk lalu coba lagi
    if (rem == st.stdLastRem) {
      st.stdAttempts += 1;
      if (st.stdAttempts > 3) {
        if (now - st.stdLastTry < 8.0) return false;
        if (st.stdAttempts == 4) {
          log('[Standard] 3x ketik tak terkonsumsi (stage belum siap?) - mencoba lagi');
        }
        st.stdAttempts = 1;
      }
    } else {
      st.stdLastRem = rem;
      st.stdAttempts = 1;
    }
    st.stdLastTry = now;

    log("[Standard] Sisa ${rem.length} karakter: ${pyRepr(rem.length > 24 ? rem.substring(0, 24) : rem)}..."
        "${holdKey != null ? ' (TAHAN ${pyRepr(holdKey)})' : ''}");
    await focusFrame(frame);

    // stabilisasi: sisa teks tak berubah sebentar (halaman siap)
    String? r = rem;
    for (var i = 0; i < 8; i++) {
      await sleep(0.12);
      final r2 = await readRemaining(frame);
      if (r2 == null || r2 != r) {
        r = r2;
        continue;
      }
      break;
    }
    if (r == null) return false;
    rem = r;

    if (_truthy(await runJs(startBannerJs, frame))) {
      log('[Standard] banner Start Typing diklik');
      await sleep(0.8);
      rem = await readRemaining(frame) ?? '';
    }

    // bilah kemajuan UI: total = sisa saat mulai
    final totalLen = max(rem.length, 1);
    st.levelProgress = 0;

    var typedAny = false;
    try {
      if (holdKey != null) {
        await page.keyboard.down(holdKey);
        await sleep(0.15);
      }
      await clearModifiers();
      final preErr = await countErrors(frame);
      if (preErr != null && preErr > 0) {
        log('[Standard] $preErr karakter salah sudah ada sebelum mulai, '
            'coba koreksi dengan Backspace');
        try {
          for (var i = 0; i < preErr; i++) {
            await page.keyboard.press('Backspace');
            await sleep(0.06);
          }
          await sleep(0.4);
        } catch (_) {}
        final left = await countErrors(frame);
        if (left != null && left < preErr) {
          rem = await readRemaining(frame) ?? rem;
        } else {
          log('[Standard] koreksi awal tidak mempan (salah terkunci) '
              '- lanjut, akurasi lesson ini bisa < 100%');
        }
      }
      var stall = 0;
      var verified = 0;
      var bsOk = true;
      st.burstLen = 1;
      st.burstStreak = 0;
      var errPrev = await countErrors(frame) ?? 0;
      while (true) {
        if (st.stop) break;
        final cur = rem!;
        if (cur.isEmpty) break;
        // burst adaptif 1 -> 4 -> 8; pecah tepat setelah Enter/Tab
        var n = min(st.burstLen, cur.length);
        for (final spec in const ['\n', '\t']) {
          final idx = cur.indexOf(spec);
          if (idx >= 0 && idx < n) n = idx + 1;
        }
        if (!await typeBurst(cur.substring(0, n))) break;
        typedAny = true;
        var (rem2, errAfterN) = await readState(frame);
        var errAfter = errAfterN ?? errPrev;
        if (rem2 == cur.substring(n)) {
          st.burstStreak += n;
          if (st.burstStreak >= 4 && st.burstLen < 8) {
            st.burstLen = st.burstLen < 4 ? 4 : 8;
            st.burstStreak = 0;
          }
        } else if (rem2 != cur) {
          st.burstLen = 1;
          st.burstStreak = 0;
        }
        if (errAfter > errPrev && bsOk) {
          // salah di dalam burst: mundur sebanyak yang terkonsumsi, ulang pelan
          st.burstLen = 1;
          st.burstStreak = 0;
          var konsumsi = 0;
          if (rem2 != null) konsumsi = cur.length - rem2.length;
          final mundur = min(max(konsumsi, 1), 8);
          try {
            for (var i = 0; i < mundur; i++) {
              await page.keyboard.press('Backspace');
              await sleep(0.04);
            }
            await sleep(0.12);
          } catch (_) {}
          final (rChk, errChk) = await readState(frame);
          if (rChk != null && errChk != null && errChk < errAfter) {
            rem2 = rChk;
            errAfter = errChk;
          } else {
            bsOk = false;
            log('[Standard] koreksi mundur tidak mempan (lanjut - tercatat di akurasi)');
            rem2 = rChk;
          }
        }
        if (rem2 == null || rem2.isEmpty) {
          // bisa selesai, bisa juga baris berikut belum dirender
          String? got;
          for (var i = 0; i < 16; i++) {
            await sleep(0.05);
            final rr = await readRemaining(frame);
            if (rr != null && rr.isNotEmpty) {
              got = rr;
              break;
            }
          }
          if (got != null) {
            rem = got;
            stall = 0;
            continue;
          }
          break; // benar2 habis = lesson selesai
        }
        if (rem2 == cur) {
          // tak terkonsumsi: pulihkan fokus/banner tiap iterasi
          stall += 1;
          st.burstLen = 1;
          st.burstStreak = 0;
          final userHadir = await userActive(3.0);
          if (userHadir) {
            stall = min(stall, 3);
            if (!st.stallUserNote) {
              st.stallUserNote = true;
              log('[Standard] user memegang halaman - fokus dipulihkan terus, '
                  'mengetik tidak berhenti');
            }
          } else {
            st.stallUserNote = false;
          }
          await runJs(quietAliveJs, frame);
          await focusFrame(frame);
          if (_truthy(await runJs(startBannerJs, frame))) {
            log('[Standard] banner pause muncul, diklik');
            await sleep(0.15);
          }
          await sleep(0.04);
          final (rRetry, _) = await readState(frame);
          if (rRetry != null && rRetry != cur) {
            rem = rRetry;
            stall = 0;
            verified += 1;
            if (verified % 20 == 0) await keepAliveQuiet(frame);
            if (verified % 25 == 0) await escModalsOnly(frame);
            continue;
          }
          if (stall >= 8 && !userHadir) {
            log('[Standard] ketikan tidak masuk - mungkin selesai '
                'tanpa layar skor, coba tombol lanjut');
            if (await phaserTryAdvance()) {
              st.lastActionTime = now;
              await sleep(0.6);
              return true;
            }
            break;
          }
          errPrev = errAfter;
          continue;
        }
        rem = rem2;
        stall = 0;
        verified += 1;
        errPrev = errAfter;
        st.levelProgress = (1 - rem2.length / totalLen).clamp(0.0, 1.0);
        if (verified % 20 == 0) await keepAliveQuiet(frame);
        if (verified % 25 == 0) await escModalsOnly(frame);
      }
    } finally {
      if (holdKey != null) {
        try {
          await page.keyboard.up(holdKey);
        } catch (_) {}
      }
      await clearModifiers();
    }
    if (lessonGone()) return false;
    if (!typedAny) return false;
    st.levelProgress = 1;
    st.lastTypedText = '$text';
    st.bump('std');
    st.lastActionTime = now;
    final errTotal = await countErrors(frame);
    if (errTotal != null && errTotal > 0) {
      log('[Standard] lesson selesai dengan $errTotal karakter salah');
    }

    // tunggu transisi pasca-lesson; keluar begitu URL berganti
    final entryUrl = page.url;
    var noScoreClicked = 0;
    final entryWaitStart = now;
    var deadline = now + 10;
    while (now < deadline) {
      if (st.stop) break;
      if (await closeOverlaysAllFrames() > 0) {
        await sleep(0.6);
        continue;
      }
      final d = await detectAllFrames();
      if (d.det == 'score') {
        await advanceScoreScreen();
        await sleep(0.8);
      }
      if (const {'std', 'mini', 'tut'}.contains(d.det)) break;
      if (page.url != entryUrl) break;
      if (noScoreClicked < 3 && now > entryWaitStart + 3.0 + 4.0 * noScoreClicked) {
        try {
          final loc = page.locator('.navbar-continue, a.navbar-continue').first;
          if (await loc.count() > 0 && await loc.isVisible()) {
            await loc.click(timeout: 2);
            noScoreClicked += 1;
            log('[Standard] layar skor belum muncul - klik tombol lanjut');
            await sleep(0.8);
            continue;
          }
        } catch (_) {}
      }
      await sleep(0.25);
    }
    deadline = now + 8;
    while (now < deadline) {
      if (st.stop) break;
      final d = await detectAllFrames();
      if (d.det != 'unknown') break;
      if (page.url != entryUrl) break;
      await sleep(0.2);
    }
    st.lastActionTime = now;
    return true;
  }
}
