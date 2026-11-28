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
    // Layar selesai masih tampil: kotak hurufnya tetap ada di DOM, jadi
    // deteksi membaca teks yang sama lagi. Itu BUKAN 'edclub menolak':
    // jangan ketik ulang (dulu 8 dtk ketik pelan ke layar selesai, log
    // 07:55:44 / 08:10:35), cukup Enter tiap 0.5 dtk sampai layar ganti.
    // Dua cara mengenali, karena tanda class kotak tidak selalu berubah:
    // - tanda terakhir BEDA dari tanda 'belum diketik' -> pasti selesai
    //   (ditunggu sampai 15 dtk);
    // - tanda tak membedakan apa pun -> teks sama dalam 6 dtk sejak
    //   selesai diketik dianggap layar selesai.
    // Penolakan sungguhan (kotak kembali 'belum diketik') tetap jatuh ke
    // jalur ulang-pelan di bawah.
    if (st.tutDoneText != null) {
      final r = await _tutRead(frame);
      final umur = now - st.tutDoneT;
      final pend = st.tutDoneSig; // tanda 'belum diketik' (null = tak tahu)
      final masih = r != null &&
          (pend != null
              ? '${r['lastSig']}' != pend && umur < 15.0
              : text == st.tutDoneText && umur < 6.0);
      if (masih) {
        if (now - st.tutEnterT >= 0.5) {
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
        await sleep(0.1);
        return true;
      }
      // berganti keadaan / terlalu lama tak beranjak: kembali ke jalur lama
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
    final awal = rem.length;
    // kotak ikut melacak ketikan? (sisa memendek saat diketik) -> di akhir
    // 'semua kembali belum diketik' berarti ditolak sungguhan
    var melacak = false;
    var potong = 0;
    while (rem.isNotEmpty) {
      if (st.stop) return false;
      final n = min(ch, rem.length);
      if (!await typeChars(rem.substring(0, n), slow: pelan, wpmCap: 140)) break;
      await keepAliveQuiet(frame);
      rem = rem.substring(n);
      potong += 1;
      if (potong == 1 && rem.isNotEmpty) {
        final rm = (await _tutRead(frame))?['rem'];
        if (rm is String && rm.isNotEmpty && rm.length < awal) melacak = true;
      }
    }
    // pengetikan terputus (stop / user pindah halaman): JANGAN Enter -
    // dulu Enter jatuh ke halaman yang dibuka user (log 08:02:04)
    if (rem.isNotEmpty) return false;
    levelKind?.call('tutorial');
    st.bump('tut');
    st.lastActionTime = now;
    await _tutSelesai(frame, pendSig, awal, melacak);
    st.lastActionTime = now;
    return true;
  }

  /// Sesudah karakter terakhir: pantau layar tiap 0.1 dtk (maks 2.5 dtk
  /// di sini, sisanya dilanjutkan [handleTutorial] lewat loop utama) dan
  /// tekan Enter tiap 0.5 dtk. Dulu: tidur 0.8 dtk + SATU Enter + satu
  /// kali baca - Enter yang datang sebelum layar selesai siap terbuang,
  /// dan bacaan yang jatuh di tengah animasi membuat layar selesai tak
  /// dikenali -> tutorial diketik ulang pelan (kadang cepat, kadang 9 dtk).
  Future<void> _tutSelesai(
      Frame frame, String? pendSig, int awal, bool melacak) async {
    final url0 = st.lastUrl;
    final t0 = now;
    var enterT = 0.0;
    var enterN = 0;
    var tandaBeda = false; // pernah terlihat tanda 'sudah diketik'
    var hasil = 'masih tampil';
    Map? akhir;
    st.tutDoneText = null;
    st.tutDoneSig = null;
    while (now - t0 < 2.5) {
      if (st.stop) return;
      if (url0.isNotEmpty) {
        var u = url0;
        try {
          u = await realUrl();
        } catch (_) {}
        if (u != url0) {
          hasil = 'level berganti';
          akhir = null;
          break;
        }
      }
      final r = await _tutRead(frame);
      if (r == null) {
        // kotak hilang = layar skor: langsung Enter (tanpa menunggu
        // putaran loop utama)
        hasil = 'kotak hilang';
        akhir = null;
        if (_truthy(await runJs(scoreJs, page.mainFrame))) {
          hasil = 'layar skor';
          if (await advanceScoreScreen()) await sleep(0.3);
        }
        break;
      }
      akhir = r;
      final sig = '${r['lastSig']}';
      final rm = r['rem'];
      final sisa = rm is String ? rm.length : 0;
      if (pendSig != null && sig != pendSig) {
        tandaBeda = true;
      } else if (pendSig != null && (tandaBeda || melacak) && sisa > 0) {
        // kotak (kembali) 'belum diketik': ditolak / ada tombol yang tak
        // masuk -> biarkan jalur ulang mengetik sisanya (beri 0.6 dtk
        // dulu utk DOM yang telat)
        if (tandaBeda || now - t0 > 0.6) {
          hasil = sisa >= awal ? 'ditolak (kotak kosong lagi)' : 'sisa $sisa';
          akhir = null;
          break;
        }
        await sleep(0.1);
        continue;
      }
      if (now - enterT >= 0.5) {
        enterT = now;
        enterN += 1;
        try {
          await page.keyboard.press('Enter');
          if (enterN == 1) log('[Tutorial] selesai - Enter');
        } catch (_) {}
      }
      await sleep(0.1);
    }
    if (akhir != null) {
      // layar selesai belum beranjak: lanjut dijaga dari loop utama
      final rm = akhir['rem'];
      st.tutDoneText = rm is String ? rm : '';
      st.tutDoneSig = tandaBeda ? pendSig : null;
      st.tutDoneT = t0;
      st.tutEnterT = enterT;
      st.tutDoneNote = false;
    }
    log('[Tutorial] sesudah ketik: $hasil dalam '
        '${(now - t0).toStringAsFixed(1)} dtk (Enter ${enterN}x, tanda '
        '${tandaBeda ? 'berubah' : 'tetap'}${melacak ? ', kotak melacak' : ''})');
  }
}
