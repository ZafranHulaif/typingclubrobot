// Port engine/rentang.py: terapkan rentang level pilihan user tiap
// iterasi loop utama.
part of 'engine.dart';

extension Rentang on Engine {
  /// True = loop utama harus `continue` (navigasi/berhenti di sini).
  Future<bool> rangeCheck(String url) async {
    if (!st.rangeReady) return false;
    if (st.rangeDone || (st.levelStart <= 1 && st.levelEnd == 0)) return false;
    final onPlay = url.contains('.play');
    var nomor = 0;
    if (onPlay) {
      if (st.statusLabel.startsWith('L')) {
        nomor = int.tryParse(st.statusLabel.substring(1)) ?? 0;
      }
      if (nomor == 0) nomor = levels.urlToLevel(url) ?? 0;
      if (nomor > st.rangeMaxSeen) st.rangeMaxSeen = nomor;
    }
    // 1) melewati akhir rentang -> selesai
    if (nomor > 0 && st.levelEnd > 0 && nomor > st.levelEnd) {
      st.rangeDone = true;
      st.stop = true;
      log('[RENTANG] level $nomor melewati akhir rentang '
          '(${st.levelEnd}) - bot selesai.');
      return true;
    }
    // 1b) keluar dari level akhir (level terakhir kursus tak punya
    // lesson berikutnya -> mendarat di daftar)
    if (st.levelEnd > 0 &&
        st.rangeMaxSeen >= st.levelEnd &&
        !onPlay &&
        !st.needsLogin) {
      st.rangeDone = true;
      st.stop = true;
      log('[RENTANG] level akhir ${st.rangeMaxSeen} selesai (keluar dari '
          'lesson) - bot selesai.');
      return true;
    }
    if (onPlay) {
      if (st.levelStart <= 1 || st.rangeJumpDone) return false;
      // level dalam rentang sudah dikerjakan sesi ini = user sengaja buka
      if (st.rangeMaxSeen >= st.levelStart && st.rangeMaxSeen > 1) return false;
      // 2) di lesson di bawah awal rentang -> lompat
      if (nomor > 0 && nomor < st.levelStart && now - st.rangeNav > 10) {
        st.rangeNav = now;
        log('[RENTANG] level $nomor di bawah awal (${st.levelStart}) '
            '- lompat ke level ${st.levelStart}');
        if (await gotoLevelUrl(st.levelStart)) {
          st.rangeJumpDone = true;
        } else {
          log('[RENTANG] URL level awal belum ada di peta - '
              'bangun peta dulu (tombol Rentang).');
        }
        return true;
      }
      return false;
    }
    // 3) di luar lesson & user diam: kembali ke level sesi ini
    if (st.userLepas) return false;
    if (!st.needsLogin && !await userActive(25.0) && now - st.rangeNav > 10) {
      st.rangeNav = now;
      final lanjut = max(st.levelStart, st.rangeMaxSeen);
      if (await gotoLevelUrl(lanjut)) {
        st.rangeJumpDone = true;
        log('[RENTANG] kembali ke level $lanjut...');
        return true;
      }
      log('[RENTANG] URL level lanjut belum ada di peta - lanjut otomatis.');
    }
    return false;
  }
}
