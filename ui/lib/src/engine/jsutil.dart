// Port engine/jsutil.py: util frame & JS, deteksi state per frame,
// penutup pop-up/premium, debug dump.
part of 'engine.dart';

typedef Detect = ({String det, Frame? frame, dynamic data});

extension JsUtil on Engine {
  /// Semua frame halaman (utama + iframe, termasuk lintas origin).
  List<Frame> allFrames() {
    try {
      return page.frames;
    } catch (_) {
      return [page.mainFrame];
    }
  }

  /// Frame milik edclub (frame Stripe/checkout dikecualikan).
  Future<List<Frame>> edclubFrames() async {
    final out = <Frame>[];
    for (final fr in allFrames()) {
      if (await edclubFrame(fr)) out.add(fr);
    }
    return out;
  }

  Future<bool> edclubFrame(Frame fr) async {
    if (fr.isMain) return isEdclubUrl(await realUrl());
    return isEdclubFrameUrl(fr.url);
  }

  /// evaluate body JS di frame (default utama). Aman dari error -> null.
  Future<dynamic> runJs(String js, [Frame? frame]) async {
    final fr = frame ?? page.mainFrame;
    try {
      return await fr.evaluate('() => {$js}');
    } catch (_) {
      return null;
    }
  }

  /// location.href asli, rute lesson UI baru dinormalkan ke .play.
  Future<String> realUrl() async => lessonPlayUrl(await page.realUrl());

  String frameLabel(Frame fr) {
    if (fr.isMain) return 'atas';
    final u = fr.url;
    if (u.isEmpty) return 'frame:${fr.name}';
    return 'frame:${u.length > 60 ? u.substring(u.length - 60) : u}';
  }

  Future<bool> closeDidomiNotice() async =>
      _truthy(await runJs(didomiJs, page.mainFrame));

  /// Modal 'When is your birthday?': isi tanggal netral, klik Confirm.
  Future<bool> fillBirthdayModal() async {
    try {
      if (!_truthy(await runJs(birthdayJs, page.mainFrame))) return false;
      final dlg = page.locator('[role="dialog"]').first;
      await dlg.locator('select[name="month"]').selectOption(birthMonth, timeout: 4);
      await dlg.locator('input[name="year"]').fill(birthYear, timeout: 4);
      await dlg.locator('button', hasText: 'Confirm').first.click(timeout: 4);
      log('[Modal] birthday diisi ($birthMonth $birthYear)');
      return true;
    } catch (_) {
      return false;
    }
  }

  /// Gerbang audio 'Ready to start?': klik CDP = gesture sah.
  Future<bool> clickAudioGate() async {
    try {
      if (!_truthy(await runJs(audioGateJs, page.mainFrame))) return false;
      await markBotClick(page.mainFrame);
      await page
          .locator('button[data-testid="audio-activation-gate"]')
          .first
          .click(timeout: 3);
      log("[Gerbang] audio 'Ready to start?' diklik");
      return true;
    } catch (_) {
      return false;
    }
  }

  Future<Detect> detectAllFrames() async {
    var canvases = 0;
    final canvasFrames = <Frame>[];
    for (final fr in allFrames()) {
      final info = await runJs(detectJs, fr);
      if (info is! Map || info.isEmpty) continue;
      final c = info['canvases'];
      if (c is num && c > 0) {
        canvases += c.toInt();
        canvasFrames.add(fr);
      }
      if (_truthy(info['std'])) return (det: 'std', frame: fr, data: info['std']);
      if (_truthy(info['tut'])) return (det: 'tut', frame: fr, data: info['tut']);
      if (_truthy(info['mini'])) return (det: 'mini', frame: fr, data: info['mini']);
      if (fr.isMain && _truthy(await runJs(scoreJs, fr))) {
        return (det: 'score', frame: fr, data: null);
      }
    }
    return (
      det: 'unknown',
      frame: null,
      data: {'canvases': canvases, 'canvas_frames': canvasFrames},
    );
  }

  /// Jalankan penutup pop-up di semua frame. Return jumlah aksi.
  Future<int> closeOverlaysAllFrames() async {
    if (now < st.repeatUntil) return 0;
    var total = 0;
    final frames = await edclubFrames();
    // blokir CSS permanen dulu (iklan layar hasil & modal Premium)
    await runJs(blokPopupJs, page.mainFrame);
    for (final fr in frames) {
      await runJs(blokPopupJs, fr);
    }
    try {
      final sembunyi = await runJs(adhideJs, page.mainFrame);
      if (sembunyi is List && sembunyi.isNotEmpty) {
        log('[Pop-up] iklan layar hasil disembunyikan '
            '(${sembunyi.take(3).join('; ')})');
        total += sembunyi.length;
      }
    } catch (_) {}
    try {
      if (_truthy(await runJs(edmodalJs, page.mainFrame))) {
        await sleep(0.5);
        final titik = await runJs(edmodalCekJs, page.mainFrame);
        if (titik is Map && _truthy(titik['ada_x'])) {
          await markBotClick();
          await page.mouse.click(titik['x'] as num, titik['y'] as num);
          await sleep(0.3);
          final masih = await runJs(edmodalCekJs, page.mainFrame);
          log('[Pop-up] modal Premium ditutup ${masih == null ? '(klik mouse .edmodal-x)' : '- GAGAL, tunggu penutup generik'}');
          total += 1;
        } else if (titik == null) {
          log('[Pop-up] modal Premium ditutup (.edmodal-x)');
          total += 1;
        }
      }
    } catch (_) {}
    if (_truthy(await runJs(premiumSkipJs, page.mainFrame))) {
      log("[Pop-up] modal premium baru - 'Skip this lesson' diklik");
      st.lastActionTime = now;
      total += 1;
    }
    try {
      if (_truthy(await runJs(badgeStreakJs, page.mainFrame))) {
        await page.keyboard.press('Escape');
        log('[Pop-up] badge streak/pencapaian ditutup (ESC)');
        total += 1;
      }
    } catch (_) {}
    for (final fr in frames) {
      final taken = await runJs(overlayJs, fr);
      if (taken is List && taken.isNotEmpty) {
        log('[Pop-up] ${frameLabel(fr)}: ${taken.take(3).join('; ')}');
        total += taken.length;
        final first = '${taken.first}';
        // 'berulang tanpa hasil' = label sama BERUNTUN (< 4 dtk). Dulu
        // hitungan menumpuk lintas level (tiap layar hasil punya tombol
        // tutup berlabel sama) -> tiap 2-3 level eskalasi palsu + penutup
        // dibungkam 8 dtk: layar hasil/pencapaian diam lama (log 05:38:43).
        final beruntun = now - st.repeatT < 4.0;
        st.repeatT = now;
        if (first == st.repeatLabel && beruntun) {
          st.repeatCount += 1;
          if (st.repeatCount >= 3) {
            // klik JS 3x tanpa hasil: ESC + klik mouse dgn cek posisi
            log('[Pop-up] klik tutup tanpa hasil - eskalasi '
                'ESC + klik mouse (dengan pengecekan posisi)');
            await runJs(escFallbackJs, fr);
            await runJs(closePointJs, fr);
            final pt = await runJs('return window.__CLICKPT;', fr);
            if (pt is Map) {
              try {
                await markBotClick();
                await page.mouse.click(pt['x'] as num, pt['y'] as num);
              } catch (_) {}
            }
            st.repeatUntil = now + 3;
            st.repeatCount = 0;
          }
        } else {
          st.repeatLabel = first;
          st.repeatCount = 1;
        }
        break;
      }
    }
    if (total == 0) {
      for (final fr in await edclubFrames()) {
        final hint = await runJs(modalHintJs, fr);
        if (hint is Map && _truthy(hint['achievement'])) {
          if (_truthy(await runJs(escFallbackJs, fr))) {
            log('[Pop-up] modal tanpa tombol tutup, kirim ESC (achievement)');
            total += 1;
          }
          break;
        }
        // modal premium jangan di-ESC (ditangani premiumModalAction)
        if (hint is Map && _truthy(hint['premium'])) break;
      }
    }
    return total;
  }

  Future<void> dumpDebugInfo() async {
    try {
      log('---- DEBUG (tiap frame) ----');
      for (final fr in allFrames()) {
        final info = await runJs(debugDumpJs, fr);
        if (info is Map) {
          log('DEBUG ${frameLabel(fr)}: core=${info['core']} '
              'canvas=${info['canvases']} video=${info['videos']} '
              'gate=${info['gate']} didomi=${info['didomi']} '
              'birthday=${info['birthday']} url=${info['url']}');
          for (final t in (info['texts'] as List? ?? const [])) {
            log('DEBUG   dom: $t');
          }
        }
      }
      log('---------------------------');
    } catch (e) {
      log('DEBUG gagal: $e');
    }
  }
}

/// Kebenaran ala python (None/''/0/[]/{} = False).
bool _truthy(dynamic v) {
  if (v == null || v == false) return false;
  if (v is num) return v != 0;
  if (v is String) return v.isNotEmpty;
  if (v is List) return v.isNotEmpty;
  if (v is Map) return v.isNotEmpty;
  return true;
}

/// repr ala python utk log ('\n' terlihat sebagai \n).
String pyRepr(String s) =>
    "'${s.replaceAll('\\', r'\\').replaceAll('\n', r'\n').replaceAll('\t', r'\t').replaceAll("'", r"\'")}'";
