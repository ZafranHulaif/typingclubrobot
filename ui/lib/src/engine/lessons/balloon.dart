// Port engine/lessons/ocr.py: game balon/monster lewat jembatan core
// (window.core / Phaser core) + jalur OCR (lewat [OcrService]).
part of '../engine.dart';

final balloonStateJs = balloonBridgeJs.replaceAll("'FEED'", '0');
final _majuLabelJs = majuDasar.replaceAll('__LABEL__', majuLabel);
final cariMajuJs = _majuLabelJs.replaceAll(
    '__AKSI__',
    "  const label = (el.innerText || '').trim().slice(0, 20) || "
        "el.getAttribute('aria-label') || 'tombol'; "
        'el.click(); '
        'return label;');
final cemaiMajuJs = _majuLabelJs.replaceAll('__AKSI__', '  return true;');
final titikMajuJs = _majuLabelJs.replaceAll(
    '__AKSI__', '  return {x: r.x + r.width / 2, y: r.y + r.height / 2};');

final _phaserNum = RegExp(r'phaser\d+');
final _az = RegExp(r'^[a-z]+$');
final _az212 = RegExp(r'^[a-z]{2,12}$');

extension BalloonLesson on Engine {
  /// Frame yang punya jembatan core GAME BARU (keluarga phaserNN/balloon
  /// saja: frame pelajaran biasa juga punya window.core). Cache 3 dtk.
  Future<Frame?> coreBridgeFrame() async {
    final kini = now;
    final cached = st.balloonBridgeFrame;
    if (cached != null && kini - st.balloonBridgeT < 3.0) {
      try {
        if (await cached.evaluate('() => 1') == 1) return cached;
      } catch (_) {}
    }
    for (final fr in allFrames()) {
      try {
        if (fr.isMain) {
          final u = fr.url.toLowerCase();
          if (u.contains('sportal') && u.contains('.play')) {
            if (_truthy(await runJs(coreMainJs, fr))) {
              st.balloonBridgeFrame = fr;
              st.balloonBridgeT = kini;
              return fr;
            }
          }
          continue;
        }
        if (_truthy(await runJs(coreIframeJs, fr))) {
          st.balloonBridgeFrame = fr;
          st.balloonBridgeT = kini;
          return fr;
        }
      } catch (_) {
        continue;
      }
    }
    st.balloonBridgeFrame = null;
    return null;
  }

  /// Balloon/monster UI baru: feed cur_char lewat core, tunggu game
  /// mengonsumsi sebelum huruf berikut. True kalau ada aksi.
  Future<bool> tryBalloonCore() async {
    final fr = await coreBridgeFrame();
    if (fr == null) {
      // gerbang audio 'Ready to start?' sebelum iframe game terpasang
      if (now - st.gerbangAudioT < 5) return false;
      try {
        final u = page.mainFrame.url.toLowerCase();
        if (!u.contains('.play') || !u.contains('sportal')) return false;
        if (_truthy(await runJs(readyStartJs, page.mainFrame))) {
          st.gerbangAudioT = now;
          st.lastActionTime = now;
          log("[Minigame/Balloon] gerbang audio 'Ready to start?' - Start diklik");
          return true;
        }
      } catch (_) {}
      return false;
    }
    final res = await runJs(balloonStateJs, fr);
    if (res is! Map || res.isEmpty) return false;
    if (_truthy(res['ended'])) {
      if (st.balloonEndT == 0) st.balloonEndT = now;
      await gamePaceEnd(fr);
      if (now - st.balloonSkipT > 1.2) {
        st.balloonSkipT = now;
        await runJs(canvasSkipJs, fr);
      }
      dynamic klik;
      var frLbl = '';
      Frame? frObj;
      for (final f2 in allFrames()) {
        final k2 = await runJs(cariMajuJs, f2);
        if (_truthy(k2)) {
          klik = k2;
          frObj = f2;
          frLbl = frameLabel(f2);
          break;
        }
      }
      if (klik != null && frObj != null) {
        // level tamat -> jangkar rentang maju ke level berikutnya
        final angka = RegExp(r'\d+').firstMatch(st.statusLabel);
        if (angka != null) {
          st.rangeMaxSeen = max(st.rangeMaxSeen, int.parse(angka[0]!) + 1);
        }
        if (_truthy(await runJs(cemaiMajuJs, frObj))) {
          final titik = await runJs(titikMajuJs, frObj);
          if (titik is Map && _truthy(titik['x'])) {
            await markBotClick();
            try {
              await page.mouse.click(titik['x'] as num, titik['y'] as num);
              log("[Minigame/Balloon] layar akhir - klik mouse asli '$klik' @$frLbl");
            } catch (_) {
              log("[Minigame/Balloon] layar akhir - klik '$klik' @$frLbl (mouse gagal)");
            }
          } else {
            log("[Minigame/Balloon] layar akhir - klik '$klik' @$frLbl (tanpa titik)");
          }
        } else {
          log("[Minigame/Balloon] layar akhir - klik '$klik' @$frLbl");
        }
        st.lastActionTime = now;
        st.balloonEndT = 0;
        return false;
      }
      if (now - st.balloonEndT > 25) {
        var klik2 = await runJs(cariUlangJs);
        if (!_truthy(klik2)) klik2 = await runJs(cariUlangJs, fr);
        if (_truthy(klik2)) {
          log("[Minigame/Balloon] tanpa tombol maju 25 dtk - ulang '$klik2'");
        }
        st.balloonEndT = 0;
      }
      return true;
    }
    // target bintang (N7b): huruf demi huruf sesuai jadwal + salah yang
    // disengaja. Layar mulai (spasi) juga lewat sini: rantai cepat jalur
    // biasa bisa langsung menyambar huruf2 pertama
    if (gamePaceMaybe) {
      final gs = await runJs(gameStatJs, fr);
      if (gs is Map) {
        final pace = await gamePace(fr, gs);
        if (pace != null) {
          st.balloonEndT = 0;
          return _balloonPaced(fr, pace, gs);
        }
      } else if (gamePaceHold()) {
        return true;
      }
    }
    final chr = res['chr'] as String?;
    final idx = res['idx'];
    final kini = now;
    st.balloonEndT = 0;
    if (st.hasBalloonCoreLast &&
        st.balloonCoreChr == chr &&
        st.balloonCoreIdx == idx &&
        kini - st.balloonCoreLastT < 3.5) {
      return true; // sudah diketik, game belum konsumsi = klaim siklus
    }
    if (kini - st.balloonCoreTyped < 0.12) return true;
    final fed = await runJs(balloonFeedJs, fr);
    if (fed is Map && _truthy(fed['fed'])) {
      final huruf = '${fed['huruf'] ?? ''}';
      st.hasBalloonCoreLast = true;
      st.balloonCoreChr = chr;
      st.balloonCoreIdx = fed['idx'] ?? idx;
      st.balloonCoreLastT = kini;
      st.balloonCoreTyped = kini;
      log("[Minigame/Balloon] core: '$huruf' idx->${fed['idx']}");
      st.bump('phaser', huruf.length);
      st.lastActionTime = now;
      return true;
    }
    return false;
  }

  /// Game dengan target bintang: beri huruf sesuai jadwal selama ~2 dtk
  /// per panggilan (jadwal tidak terganggu putaran supervisor), lalu
  /// kembali supaya pop-up/Stop tetap tertangani.
  Future<bool> _balloonPaced(Frame fr, GamePace pace, Map s0) async {
    final mulai = now;
    var s = s0;
    var n = 0;
    while (true) {
      final r = await gamePaceStep(fr, pace, s);
      if (r == 'fed') {
        n += 1;
        st.lastActionTime = now;
      }
      if (r != 'fed' || st.stop || now - mulai > 2.0) break;
      final s2 = await runJs(gameStatJs, fr);
      if (s2 is! Map) break;
      s = s2;
    }
    if (n > 0) {
      st.bump('phaser', n);
      log('[Minigame/Balloon] core (bintang): $n huruf, idx->$_gameIdx');
    }
    return true;
  }

  /// Frame game balon (iframe balloon/phaserNN, game di frame utama
  /// sportal .play, atau iframe ber-URL kosong yang punya Phaser).
  Future<Frame?> balloonFrame() async {
    final kini = now;
    for (final fr in allFrames()) {
      final u = fr.url;
      if (u.contains('balloon') || _phaserNum.hasMatch(u)) {
        st.balloonFrameSeen = kini;
        if (u.contains('balloon')) await _probeIframe(fr);
        return fr;
      }
    }
    final mu = page.mainFrame.url.toLowerCase();
    if (mu.contains('sportal') && mu.contains('.play')) {
      st.balloonFrameSeen = kini;
      return page.mainFrame;
    }
    if (kini - st.balloonEmptyCk < 3.0) return st.balloonEmptyFrame;
    st.balloonEmptyCk = kini;
    for (final fr in allFrames()) {
      final u = fr.url.trim();
      if (u.isNotEmpty && u != 'about:blank') continue;
      if (_truthy(await runJs(phaserPresentJs, fr))) {
        st.balloonFrameSeen = kini;
        st.balloonEmptyFrame = fr;
        await _probeIframe(fr);
        return fr;
      }
    }
    st.balloonEmptyFrame = null;
    return null;
  }

  Future<void> _probeIframe(Frame fr) async {
    if (st.balloonProbeDone) return;
    st.balloonProbeDone = true;
    final info = await runJs(probeIframeJs, fr);
    final s = info == null ? 'None' : jsonEncode(info);
    log('[Minigame/Balloon] probe iframe: ${s.length > 300 ? s.substring(0, 300) : s}');
  }

  /// Screenshot elemen body frame (PNG) utk OCR.
  Future<Uint8List?> _shotBody(Frame fr) async {
    try {
      final box = await fr.locator('body').first.boundingBox(timeout: 3);
      if (box == null) return null;
      final r = await page.cdp('Page.captureScreenshot', {
        'format': 'png',
        'clip': {
          'x': box['x'],
          'y': box['y'],
          'width': box['width'],
          'height': box['height'],
          'scale': 1,
        },
      });
      return base64Decode('${r['data'] ?? ''}');
    } catch (_) {
      return null;
    }
  }

  Future<List<String>> ocrWordsFromFrame(Frame fr) async {
    final png = await _shotBody(fr);
    if (png == null) return const [];
    final out = <String>[];
    for (final w in await ocr.recognize(png)) {
      final t = w.text.trim().toLowerCase();
      if (!_az212.hasMatch(t) || uiWords.contains(t)) continue;
      if (w.cy > 0.15 && w.cy < 0.90) out.add(t);
    }
    return out;
  }

  Future<bool> tryOcrMinigame(Map meta) async {
    final frames = (meta['canvas_frames'] as List?)?.cast<Frame>() ?? const [];
    if (!ocr.available || frames.isEmpty) return false;
    final t = now;
    if (t - st.lastOcrTime < ocrMinInterval) return false;
    st.lastOcrTime = t;
    for (final fr in frames) {
      final words = await ocrWordsFromFrame(fr);
      if (words.isEmpty) continue;
      await focusFrame(fr);
      final target = words.first;
      log("[Minigame/OCR] kata: ${words.take(5).toList()} -> mengetik '$target'");
      if (!await typeChars(target)) return false;
      st.bump('ocr');
      st.lastActionTime = now;
      return true;
    }
    return false;
  }

  Future<List<OcrWord>> _ocrTokens(Frame fr) async {
    final png = await _shotBody(fr);
    if (png == null) return const [];
    final out = <OcrWord>[];
    for (final w in await ocr.recognize(png, upscale: 3)) {
      final t = w.text.trim().toLowerCase().replaceAll(RegExp(r'''^[.,!?;:'"()]+|[.,!?;:'"()]+$'''), '');
      if (!_az.hasMatch(t) || uiWords.contains(t)) continue;
      out.add(OcrWord(t, w.cx, w.cy));
    }
    return out;
  }

  /// Balon tanpa API core: baca huruf lewat OCR (butuh [OcrService]).
  Future<bool> tryOcrBalloon() async {
    if (!ocr.available) return false;
    final fr = await balloonFrame();
    if (fr == null) return false;
    final t = now;
    if (t - st.lastBalloonOcr < 0.35) return false;
    st.lastBalloonOcr = t;
    final toks = await _ocrTokens(fr);
    if (toks.isEmpty) return false;
    final joined = toks.map((e) => e.text).join(' ');
    final mulai = joined.contains('begin') ||
        joined.contains('again') ||
        joined.contains('letter') ||
        joined.contains('space');
    if (mulai && joined.contains('space')) {
      await focusFrame(fr);
      await markBotClick();
      await page.keyboard.press('Space');
      log('[Minigame/Balloon] layar SPACE - spasi ditekan');
      st.lastActionTime = now;
      return true;
    }
    if (joined.contains('move')) {
      for (final w in toks) {
        if (w.text != 'move') continue;
        try {
          final box = await fr.locator('canvas').first.boundingBox(timeout: 2);
          if (box != null) {
            await markBotClick();
            await page.mouse.click(box['x']! + w.cx * box['width']!,
                box['y']! + w.cy * box['height']!);
            log('[Minigame/Balloon] tombol Move On diklik');
            st.lastActionTime = now;
            return true;
          }
        } catch (_) {}
      }
    }
    final urut = [...toks]..sort((a, b) {
        final ra = (a.cy * 8).toInt(), rb = (b.cy * 8).toInt();
        return ra != rb ? ra.compareTo(rb) : a.cx.compareTo(b.cx);
      });
    final huruf = [
      for (final w in urut)
        if (w.text.length == 1 && w.cy > 0.08 && w.cy < 0.75 && w.cx <= 0.93) w
    ];
    if (huruf.isEmpty) return false;
    final target = huruf.first;
    if (target.cx > 0.30) return false; // belum di zona pukul
    await focusFrame(fr);
    log(mulai
        ? "[Minigame/Balloon] mulai via huruf '${target.text}' (x=${target.cx.toStringAsFixed(2)})"
        : "[Minigame/Balloon] balon di zona: '${target.text}' (x=${target.cx.toStringAsFixed(2)})");
    if (!await typeChars(target.text)) return false;
    await sleep(0.15);
    st.bump('ocr');
    st.lastActionTime = now;
    return true;
  }
}
