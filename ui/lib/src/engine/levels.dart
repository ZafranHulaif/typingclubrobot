// Port engine/levels.py: rentang & validasi kunci, navigasi daftar
// pelajaran (URUT KETAT), lompat level, label level, bangun peta.
part of 'engine.dart';

// _DAFTAR_JS 3.5.x ditulis di raw string python dgn '\\d' -> regex JS
// mencari backslash literal, nomor baris SELALU 0 (filter 'cari' mati,
// lompat daftar bisa mundur ke baris terbuka pertama). Diperbaiki di sini
// tanpa mengubah sumber verbatim; perbaikan yg sama perlu di 3.5.x.
final daftarJsFixed = daftarJs.replaceAll(r'(\\d+)', r'(\d+)');

const _rowSel = "a[aria-label^='Lesson '], div.box-container";

extension Levels on Engine {
  /// Buka daftar lesson (rute baru course/3) kalau belum di sana, lalu
  /// tunggu barisnya. Sudah di daftar = jangan reload.
  Future<void> waitDaftar() async {
    var u = '';
    try {
      u = await realUrl();
    } catch (_) {}
    if (!u.contains('/student/course/')) {
      await page.goto(courseUrl, timeout: 30);
    }
    await page.waitForSelector(_rowSel, timeout: 20);
  }

  Future<Set<int>> bacaUnlock() async {
    final r = await page.evaluate(bacaUnlockJs);
    return {for (final n in (r as List? ?? const [])) (n as num).toInt()};
  }

  /// Set level terbuka dari daftar (redirect tab utama pulang-pergi).
  /// null = daftar tak terbaca.
  Future<Set<int>?> readUnlockSet() async {
    String asal;
    try {
      asal = await realUrl();
    } catch (_) {
      return null;
    }
    final kembali = asal.contains('.play') ? asal : '';
    try {
      await waitDaftar();
      await sleep(1.0);
      return await bacaUnlock();
    } catch (_) {
      return null;
    } finally {
      if (kembali.isNotEmpty && diLesson(kembali)) {
        try {
          await page.goto(lessonRouteUrl(kembali), timeout: 25);
        } catch (_) {}
      }
    }
  }

  /// Validasi NON-BLOKIR level awal (terkunci = halaman kosong). False =
  /// user memilih stop.
  Future<bool> rangeValidateStep() async {
    if (st.rangeValidated || st.levelStart <= 1) {
      st.rangeValidated = true;
      return true;
    }
    if (st.needsLogin || !st.loginDicek) return true;
    if (await loginProfile() == 'out') {
      st.rangeValidated = true;
      return true;
    }
    try {
      if (diLesson(await realUrl())) {
        st.rangeValidated = true;
        return true;
      }
    } catch (_) {}
    // level terbuka berurutan: posisi terdepan akun >= awal = pasti buka
    if (levels.posisi > 0 && st.levelStart <= levels.posisi) {
      st.rangeValidated = true;
      return true;
    }
    st.unlockSet ??= await readUnlockSet();
    final us = st.unlockSet;
    if (us == null || us.isEmpty || us.reduce(max) >= st.levelStart) {
      st.rangeValidated = true;
      return true;
    }
    final fallback = us.reduce(max);
    log('[RENTANG] level ${st.levelStart} masih TERKUNCI di akun ini - '
        'terbuka sampai level $fallback.');
    st.levelAsked
      ..aktif = true
      ..start = st.levelStart
      ..fallback = fallback
      ..jawab = '';
    String? jawab;
    final ask = askLocked;
    if (ask != null) {
      try {
        jawab = await ask(st.levelStart, fallback)
            .timeout(const Duration(seconds: 300), onTimeout: () => null);
      } catch (_) {}
    }
    st.levelAsked.aktif = false;
    jawab = (jawab == null || jawab.isEmpty) ? 'mulai' : jawab;
    st.levelAsked.jawab = jawab;
    st.rangeValidated = true;
    if (jawab == 'stop' || st.stop) {
      log('[RENTANG] dibatalkan user - bot tidak jalan.');
      return false;
    }
    st.levelStart = fallback;
    log('[RENTANG] mulai dari level ${st.levelStart} (posisi terdepan akun).');
    return true;
  }

  /// Lesson benar2 dirender (canvas/video/teks), bukan halaman kosong.
  Future<bool> lessonHidup([double batas = 8.0]) async {
    final mulai = now;
    while (now - mulai < batas) {
      if (st.stop) return false;
      dynamic n;
      try {
        n = await page.evaluate(lessonHidupJs);
      } catch (_) {
        n = null;
      }
      if (n is Map && diLesson('${n['u'] ?? ''}')) {
        final b = (n['b'] as num?) ?? 0;
        if (_truthy(n['c']) || _truthy(n['v']) || b > 200) return true;
        if (await gateAtauMulai()) return true;
      }
      await sleep(0.5);
    }
    return false;
  }

  Future<bool> gateAtauMulai() async {
    try {
      return await page.evaluate(gateAtauMulaiJs) == true;
    } catch (_) {
      return false;
    }
  }

  Future<bool> gotoLevelViaDaftar(int nomor) async {
    st.petaBangun = true;
    try {
      return await _gotoLevelViaDaftarIsi(nomor);
    } finally {
      st.petaBangun = false;
    }
  }

  Future<bool> _gotoLevelViaDaftarIsi(int nomor) async {
    try {
      await waitDaftar();
    } catch (_) {
      return false;
    }
    var ketemu = -1;
    for (var putaran = 0; putaran < 10; putaran++) {
      if (st.stop) return false;
      try {
        ketemu = ((await page.evaluate(cariBarisJs, nomor)) as num?)?.toInt() ?? -1;
      } catch (_) {
        ketemu = -1;
      }
      if (ketemu >= 0) break;
      try {
        await page.evaluate(scrollBawahJs);
      } catch (_) {
        break;
      }
      await sleep(1.0);
    }
    if (ketemu < 0) return false;
    try {
      await page.evaluate(klikBarisJs, ketemu);
    } catch (_) {
      return false;
    }
    final url = await waitPlayUrl();
    if (st.stop || url == null) return false;
    if (!await lessonHidup(6.0)) {
      st.tahanNav = '/${url.split('/').last}';
      try {
        await page.goto(url, timeout: 25);
      } catch (_) {}
    }
    final rute = lessonRouteUrl(url);
    if (levels.map['$nomor'] != rute) {
      levels.record(nomor, rute);
      log('[PETA] level $nomor diperbarui via daftar: $url');
    }
    return true;
  }

  /// URL navigasi level N dari peta (tanpa navigasi).
  String urlUntukLevel(int nomor) => levels.urlFor(nomor);

  /// Buka lesson N dari peta; peta basi -> klik baris daftar.
  Future<bool> gotoLevelUrl(int nomor) async {
    final url = levels.map['$nomor'];
    if (url != null && url.isNotEmpty) {
      try {
        await page.goto(lessonRouteUrl(url), timeout: 25);
      } catch (_) {}
      if (await lessonHidup()) return true;
      log('[PETA] URL terpetakan level $nomor tidak hidup '
          '(course berubah?) - pakai daftar lesson...');
    }
    return gotoLevelViaDaftar(nomor);
  }

  /// Nomor level ASLI ('L87') dari teks halaman (nomor URL = id konten).
  Future<String> levelLabel() async {
    final url = page.url;
    final c = st.levelLabelCache[url];
    if (c != null) return c;
    final nomor = await runJs(levelLabelJs, page.mainFrame);
    if (nomor == null || '$nomor'.isEmpty) return '';
    final lab = 'L$nomor';
    st.levelLabelCache[url] = lab;
    final n = int.tryParse('$nomor');
    if (n != null) levels.record(n, url);
    return lab;
  }

  Future<String?> waitPlayUrl() async {
    for (var i = 0; i < 20; i++) {
      await sleep(0.5);
      if (st.stop) return null;
      String? u;
      try {
        final r = await page.evaluate('() => location.href');
        u = r is String ? r : null;
      } catch (_) {}
      final u2 = u == null ? null : lessonPlayUrl(u);
      if (u2 != null && u2.contains('.play') && isEdclubUrl(u2)) return u2;
      if (i == 3 || i == 9) {
        // baris terkunci: modal 'jumping ahead' / 'Skip anyways'
        try {
          await page.evaluate(klikLanjutJs);
        } catch (_) {}
      }
    }
    return null;
  }

  /// Klik baris TERBUKA pertama TEPAT SETELAH posisi sekarang (urut
  /// ketat, tidak pernah mundur). Return URL .play / null.
  Future<String?> gotoNextLessonInList(String currentUrl) async {
    final cur = lessonId(currentUrl);
    var lvlNow = levels.urlToLevel(currentUrl) ?? 0;
    if (lvlNow == 0) {
      try {
        final lab = await levelLabel();
        lvlNow = lab.startsWith('L') ? int.tryParse(lab.substring(1)) ?? 0 : 0;
      } catch (_) {}
    }
    var row = 0;
    for (var k = 0; k < 3; k++) {
      if (st.stop) return null;
      try {
        await waitDaftar();
      } catch (_) {
        continue;
      }
      int idx;
      try {
        idx = ((await page.evaluate(daftarJsFixed, {'awal': row, 'cari': lvlNow}))
                    as num?)
                ?.toInt() ??
            -1;
      } catch (_) {
        continue;
      }
      if (idx < 0) continue;
      try {
        await page.evaluate(klikBarisJs, idx);
      } catch (_) {
        continue;
      }
      row = idx + 1;
      final url = await waitPlayUrl();
      if (url == null) continue;
      final lid = lessonId(url);
      if (lid != cur && !st.brokenLessons.contains(lid)) return url;
    }
    return null;
  }

  Future<String?> waitSpaNextUrl(int? oldLid) async {
    for (var i = 0; i < 12; i++) {
      await sleep(0.7);
      if (st.stop) return null;
      String u;
      try {
        u = await realUrl();
      } catch (_) {
        continue;
      }
      if (u.contains('.play')) {
        final nid = lessonId(u);
        if (nid != null && nid != oldLid) return u;
      }
    }
    return null;
  }

  /// Level rusak/premium-beku: lanjut ke pelajaran berikutnya SESUAI
  /// URUTAN (tombol Skip UI baru dulu, lalu daftar).
  Future<bool> skipToNextLesson(String alasan) async {
    var base = st.lastUrl.contains('.play') ? st.lastUrl : '';
    if (base.isEmpty) {
      try {
        base = await realUrl();
      } catch (_) {}
    }
    if (!base.contains('.play')) return false;
    final lid = lessonId(base);
    if (lid != null) st.brokenLessons.add(lid);
    dynamic titik = await runJs(spaSkipJs, page.mainFrame);
    if (titik is Map) {
      try {
        await page.mouse.click(titik['x'] as num, titik['y'] as num);
      } catch (_) {
        titik = null;
      }
      if (titik != null) {
        final url = await waitSpaNextUrl(lid);
        if (url != null) {
          _afterSkip(base, url);
          log('[SKIP] $alasan - lanjut ke ${tail(url)} (tombol Skip UI baru)');
          return true;
        }
      }
    }
    String? url;
    try {
      url = await gotoNextLessonInList(base);
    } catch (_) {}
    if (url == null) return false;
    _afterSkip(base, lessonPlayUrl(page.url));
    log('[SKIP] $alasan - lanjut ke ${tail(url)} (urutan daftar pelajaran)');
    return true;
  }

  void _afterSkip(String base, String url) {
    st.recoveryCounts.remove(base);
    st.hijackCounts.remove(base);
    st.lastUrl = url;
    st.lastActionTime = now;
    st.lastRecovery = now;
  }

  /// Bangun peta level -> URL lengkap dgn klik tiap baris daftar.
  Future<int> buildLevelMap() async {
    st.petaBangun = true;
    var asal = '';
    try {
      asal = await realUrl();
    } catch (_) {}
    var baru = 0;
    try {
      await waitDaftar();
      Future<int> jumlah() async =>
          ((await page.evaluate(jumlahBarisJs)) as num?)?.toInt() ?? 0;
      var total = await jumlah();
      if (total == 0) {
        log('[PETA] daftar lesson tidak terbaca.');
        return 0;
      }
      log('[PETA] membangun peta (scroll otomatis memuat semua '
          'bagian - jangan tutup bot)...');
      var i = 0;
      var mentok = 0;
      while (i < total) {
        if (st.stop) {
          log('[PETA] dihentikan di level ${i + 1} (bisa dilanjutkan lain waktu).');
          break;
        }
        try {
          try {
            final x = page.locator('.edmodal-x');
            if (await x.count() > 0) {
              await x.first.click(timeout: 0.8);
              await sleep(0.3);
            }
          } catch (_) {}
          final lbl = '${await page.evaluate(barisLabelJs, i) ?? ''}';
          final m = RegExp(r'^Lesson\s+(\d+)').firstMatch(lbl);
          final nomor = m != null ? int.parse(m[1]!) : i + 1;
          if (levels.map.containsKey('$nomor')) {
            i += 1;
            continue;
          }
          await page.evaluate(klikBarisJs, i);
          String? url;
          for (var fase = 0; fase < 40; fase++) {
            await sleep(0.1);
            final u = '${await page.evaluate('() => location.href') ?? ''}';
            final u2 = lessonPlayUrl(u);
            if (u2.contains('.play')) {
              url = u2;
              break;
            }
            if (fase == 12 || fase == 28) await page.evaluate(klikLanjutJs);
          }
          if (url != null && levels.map['$nomor'] != lessonRouteUrl(url)) {
            levels.record(nomor, lessonRouteUrl(url));
            baru += 1;
          }
          if (url != null) {
            await page.goBack(timeout: 15);
            await page.waitForSelector(_rowSel, timeout: 20);
          }
          if ((i + 1) % 25 == 0) log('[PETA] ${i + 1}/$total level terpetakan...');
          i += 1;
          if (i >= total) {
            await page.evaluate(scrollBawahJs);
            await sleep(1.2);
            final total2 = await jumlah();
            if (total2 > total) {
              total = total2;
              mentok = 0;
            } else {
              mentok += 1;
              if (mentok >= 2) break;
            }
          }
        } catch (_) {
          var pulih = false;
          for (var k = 0; k < 3; k++) {
            try {
              await waitDaftar();
              pulih = true;
              break;
            } catch (_) {
              await sleep(2);
            }
          }
          if (!pulih) {
            log('[PETA] daftar tidak bisa dibuka lagi - berhenti '
                '(lanjutkan lain waktu, sudah terpetakan ${levels.map.length}).');
            break;
          }
        }
      }
      log('[PETA] selesai: +$baru baru, total ${levels.map.length} '
          'level terpetakan (level_map.json).');
    } catch (_) {
    } finally {
      st.petaBangun = false;
      if (asal.contains('.play')) {
        try {
          await page.goto(lessonRouteUrl(asal), timeout: 25);
        } catch (_) {}
      }
    }
    return baru;
  }
}
