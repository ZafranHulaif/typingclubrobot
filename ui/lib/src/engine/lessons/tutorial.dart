// Port engine/lessons/tutorial.py: level tutorial boxed (ketik urutan
// penuh, maks 140 wpm; mengulang = turunkan ke cadence aman).
part of '../engine.dart';

extension TutorialLesson on Engine {
  Future<Map?> _tutRead(Frame frame) async {
    final r = await runJs(tutRemainJs, frame);
    return r is Map ? r : null;
  }

  Future<bool> handleTutorial(Frame frame, dynamic data) async {
    final text = data is Map ? '${data['text'] ?? ''}' : '';
    if (text.isEmpty) return false;
    // Layar selesai ('Good job!') masih tampil: kotak hurufnya tetap ada
    // di DOM dgn SEMUA karakter bertanda 'sudah diketik', jadi deteksi
    // membaca teks penuh yang sama. Dulu itu dikira 'edclub menolak' ->
    // seluruh tutorial diketik ulang pelan ke layar selesai (spasi =
    // halaman tergulir) dan baru Enter 8 dtk kemudian (log 07:20:52).
    // Sekarang: jangan ketik, cukup Enter lagi tiap 1 dtk sampai layar
    // berganti. Penolakan sungguhan (kotak kembali 'belum diketik' =
    // tandanya beda) tetap jatuh ke jalur ulang-pelan di bawah.
    if (st.tutDoneText == text && st.tutDoneSig != null) {
      final r = await _tutRead(frame);
      final masih = r != null &&
          r['allSame'] == true &&
          '${r['lastSig']}' == st.tutDoneSig;
      if (masih && now - st.tutDoneT < 15.0) {
        if (now - st.tutEnterT >= 1.0) {
          st.tutEnterT = now;
          if (!st.tutDoneNote) {
            st.tutDoneNote = true;
            log('[Tutorial] layar selesai masih tampil - Enter lagi '
                '(tidak diketik ulang)');
          }
          try {
            await page.keyboard.press('Enter');
          } catch (_) {}
        }
        await sleep(0.2);
        return true;
      }
      // berganti keadaan / 15 dtk tak beranjak: kembali ke jalur lama
      st.tutDoneText = null;
      st.tutDoneSig = null;
    }
    if (text == st.tutSig && st.tutAttempts >= 6) return false;
    if (text != st.tutSig) {
      st.tutSig = text;
      st.tutAttempts = 0;
      st.tutFull = text;
    }
    st.tutAttempts += 1;
    await focusFrame(frame);
    log('[Tutorial] ketik ${pyRepr(text)} (coba ${st.tutAttempts})');
    if (_truthy(await runJs(startBannerJs, frame))) await sleep(0.4);
    var rem = text;
    var res = await _tutRead(frame);
    final pelan = st.tutAttempts >= 2;
    if (pelan) {
      log('[Tutorial] level ini mengulang - kecepatan diturunkan '
          '(edclub menolak penyelesaian yang terlalu cepat)');
    }
    var stable = 0;
    for (var i = 0; i < 8; i++) {
      await sleep(0.25);
      final r2 = await _tutRead(frame);
      if (res != null && r2 != null && r2['rem'] == res['rem']) {
        stable += 1;
      } else {
        res = r2;
        stable = 0;
      }
      if (stable >= 2) break;
    }
    final full = st.tutFull;
    final rr = res?['rem'];
    if (st.tutAttempts >= 2 &&
        full != null &&
        rr is String &&
        rr.isNotEmpty &&
        rr.length < full.length &&
        full.endsWith(rr)) {
      rem = rr;
      log('[Tutorial] lanjut dari sisa ${rem.length} karakter');
    }
    // tanda class karakter yang BELUM diketik (run terakhir sebelum mulai)
    final pendSig = res == null ? null : '${res['lastSig']}';
    const ch = 10; // potongan kecil utk keep-alive senyap di selanya
    while (rem.isNotEmpty) {
      if (st.stop) return false;
      final n = min(ch, rem.length);
      if (!await typeChars(rem.substring(0, n), slow: pelan, wpmCap: 140)) break;
      await keepAliveQuiet(frame);
      rem = rem.substring(n);
    }
    // akhir pola: Enter (aman walau layar skor sudah muncul)
    await sleep(0.8);
    // semua karakter kini satu tanda & bukan tanda 'belum diketik' =
    // keadaan selesai: catat supaya putaran berikut tidak mengetik ulang
    final akhir = rem.isEmpty ? await _tutRead(frame) : null;
    final akhirRem = akhir?['rem'];
    if (akhir != null &&
        akhir['allSame'] == true &&
        pendSig != null &&
        '${akhir['lastSig']}' != pendSig &&
        akhirRem is String &&
        akhirRem.isNotEmpty) {
      st.tutDoneText = akhirRem;
      st.tutDoneSig = '${akhir['lastSig']}';
      st.tutDoneT = now;
      st.tutEnterT = now;
      st.tutDoneNote = false;
    } else {
      st.tutDoneText = null;
      st.tutDoneSig = null;
    }
    try {
      await page.keyboard.press('Enter');
      log('[Tutorial] selesai - Enter');
    } catch (_) {}
    st.bump('tut');
    st.lastActionTime = now;
    await sleep(0.3);
    return true;
  }
}
