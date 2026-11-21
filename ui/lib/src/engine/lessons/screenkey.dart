// Port engine/lessons/screenkey.py: keyboard layar (klik tombol highlight).
part of '../engine.dart';

extension ScreenKeyLesson on Engine {
  Future<bool> clickScreenKeyboard() async {
    if (now < st.scrkeyUntil) return false;
    for (final fr in allFrames()) {
      final hit = await runJs(screenkeyJs, fr);
      if (hit is! Map || hit.isEmpty) continue;
      final k = '${hit['key'] ?? ''}';
      if (k == st.scrkeyKey) {
        st.scrkeyCount += 1;
        if (st.scrkeyCount >= 4) {
          st.scrkeyUntil = now + 10;
          st.scrkeyCount = 0;
          log('[Keyboard-layar] klik tanpa efek, jeda 10 detik');
          return false;
        }
      } else {
        st.scrkeyKey = k;
        st.scrkeyCount = 1;
      }
      log("[Keyboard-layar] klik '$k' (${hit['sel']})");
      st.bump('uikey');
      st.lastActionTime = now;
      return true;
    }
    return false;
  }
}
