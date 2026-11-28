// Port engine/lessons/holdkey.py: level "tahan tombol".
part of '../engine.dart';

String? mapHoldKey(String? k) {
  final s = (k ?? '').trim().toLowerCase();
  final m = holdKeyMap[s];
  if (m != null) return m;
  if (s.length == 1 && RegExp(r'^[a-z]$').hasMatch(s)) return s;
  return null;
}

extension HoldKeyLesson on Engine {
  Future<bool> tryHoldLevel() async {
    for (final fr in allFrames()) {
      final instr = await runJs(holdJs, fr);
      if (instr is! Map || instr.isEmpty) continue;
      final key = mapHoldKey(instr['key'] as String?);
      if (key == null) continue;
      final rawS = '${instr['raw'] ?? ''}';
      final raw = rawS.isEmpty ? key : rawS;
      if (raw == st.lastHoldRaw && st.holdAttempts >= 4) return false;
      if (raw != st.lastHoldRaw) {
        st.lastHoldRaw = raw;
        st.holdAttempts = 0;
      }
      st.holdAttempts += 1;
      await focusFrame(fr);
      final duration = min(1.5 * st.holdAttempts, 8.0);
      log("[Hold] instruksi '$raw' -> menahan ${duration.toStringAsFixed(1)}s "
          '(coba ${st.holdAttempts})');
      try {
        await page.keyboard.down(key);
        await sleep(duration);
      } catch (_) {
      } finally {
        try {
          await page.keyboard.up(key);
        } catch (_) {}
      }
      levelKind?.call('free');
      st.bump('hold');
      st.lastActionTime = now;
      return true;
    }
    return false;
  }
}
