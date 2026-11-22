// Port engine/lessons/video.py: level video (play, lompat ke akhir).
part of '../engine.dart';

extension VideoLesson on Engine {
  Future<bool> handleVideoLevel() async {
    for (final fr in await edclubFrames()) {
      final info = await runJs(videoStateJs, fr);
      if (info is! Map || info.isEmpty) continue;
      if (!_truthy(info['splash'])) {
        final hiasan = await runJs(videoHiasanJs, fr);
        if (hiasan is String) {
          final k = '${frameLabel(fr)} $hiasan';
          if (st.videoIgnored != k) {
            st.videoIgnored = k;
            log('[Video] ${frameLabel(fr)}: video hiasan diabaikan ($hiasan)');
          }
          continue;
        }
      }
      if (_truthy(info['splash'])) {
        // pemain belum mount: klik splash play besar dulu
        try {
          await markBotClick(fr);
          await fr.locator('.vjs-big-play-button').first.click(timeout: 2);
          st.bump('video');
          st.lastActionTime = now;
          log('[Video] ${frameLabel(fr)}: splash play diklik');
          await sleep(0.8);
          return true;
        } catch (_) {
          continue;
        }
      }
      if (_truthy(info['paused'])) {
        try {
          await markBotClick(fr);
          await fr.locator('.vjs-big-play-button').first.click(timeout: 2);
          await sleep(0.8);
        } catch (_) {}
      }
      await runJs(videoSkipJs, fr);
      st.bump('video');
      st.lastActionTime = now;
      log('[Video] ${frameLabel(fr)}: dilompat ke akhir');
      await sleep(0.5);
      return true;
    }
    return false;
  }
}
