// Port engine/supervisor.py: loop utama (mesin keputusan per iterasi).
part of 'engine.dart';

extension Supervisor on Engine {
  Future<void> mainLoop() async {
    st.rangeValidated = false;
    st.rangeMaxSeen = 0;
    var rendererGagal = 0;
    var navTime = 0.0;
    var tungguRentangBaru = false;
    // mulai = user menyerahkan kendali: klik/blur sebelum ini diabaikan
    handOver();
    // lompat ke levelStart hanya sekali, dan hanya kalau saat mulai tidak
    // sedang di lesson (lesson yang dibuka user = kerjakan dulu)
    st.rangeJumpDone = diLesson(page.url);
    if (st.rangeJumpDone && st.levelStart > 1) {
      log('[RENTANG] sudah ada lesson terbuka - kerjakan ini dulu '
          '(lompatan ke level ${st.levelStart} dilewati).');
    }
    while (true) {
      try {
        if (st.stop) {
          log('Bot dihentikan.');
          break;
        }
        // gerbang kesehatan renderer (dilewati saat user di alur OAuth)
        final oauthGate = st.needsLogin && isOauthUrl(page.url);
        if (!page.closed && !oauthGate && !await page.alive()) {
          rendererGagal += 1;
          if (rendererGagal == 1) {
            log('[PEMULIHAN] Tab tidak merespons, memberi 5 detik...');
            await sleep(5);
            continue;
          }
          // mode embedded: webview tidak boleh dibunuh (sama dgn 3.5.x)
          log('[PEMULIHAN] mode embedded - WebView2 tidak boleh dibunuh. '
              'Tekan Stop lalu Start untuk mulai ulang sesi.');
          st.stop = true;
          break;
        }
        rendererGagal = 0;

        await keepAliveFrames();

        // webview dibuang (ganti akun / app ditutup)
        if (page.closed) {
          if (!st.browserClosed) {
            st.browserClosed = true;
            st.statusUrl = '';
            st.statusLabel = '';
            log('[BOT] Browser ditutup - bot menunggu. Tekan Stop '
                'lalu Start untuk buka browser baru.');
          }
          await sleep(0.5);
          continue;
        }
        st.browserClosed = false;

        var url = page.url;
        // page.url bisa basi: percayai location.href
        String real;
        try {
          real = await realUrl();
        } catch (_) {
          real = url;
        }
        if (isEdclubUrl(real)) {
          url = real;
        } else {
          final rh = Uri.tryParse(real)?.host.toLowerCase() ?? '';
          if (rh.contains('stripe') || rh.contains('checkout')) url = real;
        }
        st.statusUrl = url;
        if (st.statusLabel.isEmpty && now - st.labelRetry > 2) {
          st.labelRetry = now;
          try {
            st.statusLabel = await levelLabel();
          } catch (_) {}
        }
        if (!isEdclubUrl(url)) {
          // user sedang login Google di dalam app: diam & tunggu
          if (st.needsLogin && isOauthUrl(url)) {
            st.statusUrl = url;
            await sleep(0.5);
            continue;
          }
          // halaman dibawa ke Stripe/luar: kembali ke lesson / daftar
          if (now - st.navTry > 10) {
            st.navTry = now;
            final key = st.lastUrl.contains('.play') ? st.lastUrl : url;
            final n = (st.hijackCounts[key] ?? 0) + 1;
            st.hijackCounts[key] = n;
            if (n >= 2 && await skipToNextLesson('tab berulang kali dibawa ke Stripe')) {
              st.hijackCounts.remove(key);
              continue;
            }
            final target = diLesson(key) ? lessonRouteUrl(key) : courseUrl;
            try {
              await page.goto(target, timeout: 25);
              st.lastUrl = lessonPlayUrl(page.url);
              st.lastActionTime = now;
              log('[NAV] tab dibajak Stripe - kembali ke ${tail(target)}');
            } catch (_) {}
          }
          await sleep(1);
          continue;
        }

        final low = url.toLowerCase();
        await loginPatrol(url);
        if (st.needsLogin) {
          if (now - st.loginNotice > 30) {
            st.loginNotice = now;
            log('[LOGIN] Menunggu login edclub di dalam app...');
          }
          await sleep(1);
          continue;
        }
        if (!st.loginDicek) {
          if (now - st.loginNotice > 15) {
            st.loginNotice = now;
            log('[LOGIN] Menunggu status login terbaca '
                '(jangan melakukan apapun dulu)...');
          }
          await sleep(1);
          continue;
        }
        if (low.contains('login') ||
            low.contains('signin') ||
            low.contains('sign-in') ||
            low.contains('signup')) {
          if (now - st.loginNotice > 30) {
            st.loginNotice = now;
            log('[LOGIN] Halaman login terdeteksi. Login dulu di '
                'browser bot, bot menunggu di sini...');
          }
          await sleep(2);
          continue;
        }

        if (!await rangeValidateStep()) {
          st.stop = true;
          return;
        }

        // modal premium baru: tutup kapan pun (throttle 10 dtk)
        if (now - st.premSkipT > 10 &&
            _truthy(await runJs(premiumSkipJs, page.mainFrame))) {
          st.premSkipT = now;
          st.lastActionTime = now;
          log("[Pop-up] modal premium - 'Skip this lesson' (kapan pun)");
          await sleep(0.3);
          continue;
        }

        // user asli memakai halaman di luar lesson: jangan ambil alih
        if (!diLesson(url) && await userActive(25.0)) {
          st.userLepas = true;
          await waitForUser(url);
          continue;
        }
        if (diLesson(url)) st.userLepas = false;
        userIdleAgain(url);

        if (url != st.lastUrl) {
          // level baru: reset penanda per level
          st.phaserCooldownUntil = 0;
          st.miniVoidTahan = 0;
          st.balloonTahanN = 0;
          st.phaserFreezeUrl = '';
          st.phaserFreezeCount = 0;
          st.phaserFreezeClicked = false;
          st.introFlow = false;
          st.tutDoneText = null;
          st.tutDoneSig = null;
          st.resyncN = 0;
          st.premlockSince = 0;
          st.statusLabel = '';
          st.levelProgress = 0;
          if (st.lastUrl.isNotEmpty) {
            final s = st.stats;
            log('[PROGRES] ${await levelLabel().catchError((_) => '')} '
                '(${tail(st.lastUrl)} -> ${tail(url)})  '
                '(std=${s['std']} tut=${s['tut']} mini=${s['mini']} '
                'phaser=${s['phaser']} ocr=${s['ocr']} hold=${s['hold']} '
                'video=${s['video']} popup=${s['popup']})');
          }
          try {
            st.statusLabel = await levelLabel();
          } catch (_) {
            st.statusLabel = '';
          }
          st.lastUrl = url;
          levels.catatPosisi(levels.urlToLevel(url) ?? 0);
          st.lastActionTime = now;
          navTime = now;
        }

        if (st.askBuildMap) {
          st.askBuildMap = false;
          await buildLevelMap();
          continue;
        }
        if (st.askRecovery) {
          st.askRecovery = false;
          log('[PEMULIHAN] diminta manual - memeriksa & memulihkan lesson...');
          if (await recoverAndRestartLesson()) st.lastActionTime = now;
          continue;
        }
        if (st.awaitRange) {
          if (!tungguRentangBaru) {
            log('[RENTANG] menahan bot - menunggu pilihan level dari GUI...');
          }
          tungguRentangBaru = true;
          await sleep(0.3);
          continue;
        }
        if (tungguRentangBaru) {
          tungguRentangBaru = false;
          st.lastActionTime = now;
        }
        if (await rangeCheck(url)) continue;

        // penahan halaman UI baru: Didomi, gerbang audio, modal ultah
        if (await closeDidomiNotice()) {
          st.lastActionTime = now;
          await sleep(0.4);
          continue;
        }
        if (await clickAudioGate()) {
          st.lastActionTime = now;
          await sleep(0.8);
          continue;
        }
        if (await fillBirthdayModal()) {
          st.lastActionTime = now;
          await sleep(0.8);
          continue;
        }

        // watch window modal premium (X diklik = edclub lanjut sendiri)
        if (await premiumModalAction() == 'clicked') {
          st.lastActionTime = now;
          await sleep(0.8);
          continue;
        }

        // modal iklan/langganan di tengah lesson: tutup secepatnya, juga
        // saat 'user aktif' (blur dari modal itu sendiri terbaca begitu
        // -> dulu penutup di bawah menunggu 3 dtk, log 07:55:31-36)
        if (diLesson(url) && now - st.adModalT > 0.4 && await closeAdModal()) {
          st.lastActionTime = now;
          await sleep(0.15);
          continue;
        }

        // level video duluan sebelum penutup pop-up
        if (diLesson(url) && await handleVideoLevel()) continue;

        // jalur cepat game baru sebelum penutup pop-up
        if (await tryBalloonCore()) {
          await sleep(0.05);
          continue;
        }

        // penutup pop-up (dilewati saat user memegang halaman)
        if (!await userActive(3.0) &&
            now - st.popupT > 1.5 &&
            await closeOverlaysAllFrames() > 0) {
          st.popupT = now;
          st.bump('popup');
          await sleep(0.6);
          continue;
        }

        final d = await detectAllFrames();
        final det = d.det;
        if (det == 'std') {
          await handleStandard(d.frame!, d.data);
        } else if (det == 'tut') {
          await handleTutorial(d.frame!, d.data);
        } else if (det == 'mini' && (!diLesson(url) || lessonGone())) {
          // 'kata' di halaman non-lesson (dashboard/daftar) bukan game:
          // jangan diketik & jangan ditahan sbg balon (log 05:10:48
          // mengetik 'Dashboard'; 05:41-06:18 menahan 37 menit). url
          // putaran ini bisa basi (user baru pindah, log 07:57:51) ->
          // cek juga page.url terkini
          if (await _unknownStep(url, d.data, navTime)) continue;
        } else if (det == 'mini') {
          if (await tryBalloonCore()) {
            await sleep(0.05);
            continue;
          }
          if (await tryOcrBalloon()) {
            await sleep(0.3);
            continue;
          }
          try {
            if (await handlePhaserMinigame()) {
              await sleep(0.3);
              continue;
            }
          } catch (_) {}
          final frBal = await balloonFrame();
          if (frBal != null) {
            try {
              if (await handlePhaserMinigame()) {
                await sleep(0.3);
                continue;
              }
            } catch (_) {}
            st.balloonTahanN += 1;
            if (st.balloonTahanN % 30 == 1) {
              log('[Minigame/Balloon] varian iframe - menahan ketikan '
                  '(menunggu dukungan)');
            }
            st.lastActionTime = now;
            await sleep(0.4);
            continue;
          }
          final baruHilang = now - st.balloonFrameSeen < 15.0;
          final lowUrl = page.url.toLowerCase();
          final ruteGame = lowUrl.contains('sportal') || lowUrl.contains('/lesson/');
          if (baruHilang || ruteGame) {
            st.miniVoidTahan += 1;
            if (st.miniVoidTahan < 60) {
              st.lastActionTime = now;
              await sleep(0.4);
              continue;
            }
            st.miniVoidTahan = 0; // fallback 25 dtk
          }
          await handleMinigame(d.frame!, d.data);
        } else if (det == 'score') {
          if (await advanceScoreScreen()) st.lastActionTime = now;
          await sleep(0.6);
        } else {
          if (await _unknownStep(url, d.data, navTime)) continue;
        }
        await sleep(0.15);
      } catch (e) {
        // jangan menelan error diam-diam (throttle 30 dtk)
        if (now - st.lastLoopErr > 30) {
          st.lastLoopErr = now;
          log('[LOOP] error (diabaikan, lanjut): $e');
        }
        await sleep(0.5);
      }
    }
    final s = st.stats;
    log('Selesai. Total: lesson=${s['std']} tutorial=${s['tut']} '
        'minigame=${s['mini']} phaser=${s['phaser']} ocr=${s['ocr']} '
        'hold=${s['hold']} video=${s['video']} popup=${s['popup']}');
  }

  /// Cabang det 'unknown' (intro, hold, layar, OCR, premium gelap, stall
  /// -> pemulihan). True = loop `continue`.
  Future<bool> _unknownStep(String url, dynamic data, double navTime) async {
    final pm = await premiumModalAction();
    if (pm == 'clicked') {
      st.lastActionTime = now;
      await sleep(0.6);
      return true;
    }
    if (pm is Map && _truthy(pm['zombie'])) {
      if (st.premlockSince == 0) {
        st.premlockSince = now;
        log('[Premium] modal fullscreen tanpa X (checkout Stripe) - menunggu...');
      } else if (now - st.premlockSince > 12.0) {
        if (await skipToNextLesson('modal premium tak tertutup')) {
          st.premlockSince = 0;
          return true;
        }
      }
    } else {
      st.premlockSince = 0;
    }
    if (await handleIntroSteps()) {
      await sleep(0.05);
      return true;
    }
    if (await handlePhaserMinigame()) {
      await sleep(0.3);
      return true;
    }
    if (await tryHoldLevel()) {
      await sleep(0.4);
      return true;
    }
    if (await clickScreenKeyboard()) {
      await sleep(0.4);
      return true;
    }
    if (await tryOcrBalloon()) {
      await sleep(0.3);
      return true;
    }
    if (await tryBalloonCore()) {
      await sleep(0.3);
      return true;
    }
    if (await tryOcrMinigame(data is Map ? data : const {})) return false;

    final stalled = now - st.lastActionTime;
    final userSibuk = await userActive(25.0) || st.userLepas;
    // dump maks 3x per masa diam (dulu tiap 10 dtk tanpa henti selama
    // bot menunggu user di daftar level: ratusan baris, log 08:02-08:09)
    if (st.dumpRef != st.lastActionTime) {
      st.dumpRef = st.lastActionTime;
      st.dumpN = 0;
    }
    if (stalled > 10 && now - st.lastDebugDump > 10 && st.dumpN < 3) {
      st.lastDebugDump = now;
      st.dumpN += 1;
      log('[TUNDA] tidak ada aktivitas ${stalled.toStringAsFixed(0)}s di '
          '${tail(url)} - dumping state...');
      await dumpDebugInfo();
    }
    // jaring pengaman: lesson/game bisa hidup di iframe yang belum
    // terlihat mesin -> baca ulang frame sebelum pemulihan berat (reload)
    // Sesudah navigasi penuh (goto/reload) iframe lesson yang baru sering
    // belum terlihat: dulu baru dibaca ulang setelah diam 4 dtk (log
    // 08:06:28 -> 08:06:33, 08:07:01 -> 08:07:06). Sekarang 1 dtk, 3x
    // pertama per level berjarak 2 dtk, sesudahnya tiap 20 dtk.
    if (stalled > 1.0 &&
        diLesson(url) &&
        now - st.lastResync > (st.resyncN < 3 ? 2.0 : 20.0)) {
      st.lastResync = now;
      st.resyncN += 1;
      final n0 = allFrames().length;
      try {
        await page.resync();
        await sleep(0.3);
      } catch (_) {}
      if (allFrames().length != n0) {
        log('[FRAME] daftar frame dibaca ulang ($n0 -> ${allFrames().length})');
        return true;
      }
    }
    if (stalled > 6 && !userSibuk) {
      var prem = false;
      for (final fr2 in allFrames()) {
        final h = await runJs(modalHintJs, fr2);
        if (h is Map && _truthy(h['premium'])) {
          prem = true;
          break;
        }
      }
      if (prem) {
        try {
          final loc = page.locator('.navbar-continue, a.navbar-continue').first;
          if (await loc.count() > 0 && await loc.isVisible()) {
            await loc.click(timeout: 2);
            log('[Premium] layar gelap premium - lanjut ke lesson berikutnya');
            st.lastActionTime = now;
            return true;
          }
        } catch (_) {}
        if (stalled > 8) {
          for (final fr2 in allFrames()) {
            if (_truthy(await runJs(bukaBlokJs, fr2))) {
              log('[Premium] modal premium tanpa X saat diblokir - blokir dibuka sesaat');
              break;
            }
          }
        }
        if (stalled > 20 &&
            await skipToNextLesson('layar gelap premium tanpa tombol lanjut')) {
          st.lastActionTime = now;
          return true;
        }
        await sleep(0.4);
        return true;
      }
    }
    if (stalled > 6 && !userSibuk && await switchToPlayableTab()) return true;
    if (stalled > 12 &&
        !userSibuk &&
        now - st.lastRecovery > 25 &&
        now - navTime > 25) {
      if (!await recoverAndRestartLesson()) st.lastRecovery = now;
    }
    if (stalled > 20 && !userSibuk) {
      // level terkunci = halaman kosong: lompat sesuai urutan daftar
      var nomor = 0;
      if (st.statusLabel.startsWith('L')) {
        nomor = int.tryParse(st.statusLabel.substring(1)) ?? 0;
      }
      if (nomor > 0 && st.unlockSet == null && now - st.unlockCk > 60) {
        st.unlockCk = now;
        st.unlockSet = await readUnlockSet();
      }
      final us = st.unlockSet;
      if (nomor > 0 && us != null && us.isNotEmpty && !us.contains(nomor)) {
        if (await skipToNextLesson('level terkunci untuk akun')) {
          st.lastActionTime = now;
          return true;
        }
      }
    }
    return false;
  }
}
