// Tutorial boxed: selesai sekali, layar selesai tidak diketik ulang;
// penolakan sungguhan tetap diulang pelan. Plus serah-terima kendali
// user (handOver) & hitungan 'klik tutup tanpa hasil'.
import 'dart:math';

import 'package:flutter_test/flutter_test.dart';
import 'package:typingbot/src/engine/engine.dart';
import 'package:typingbot/src/engine/js.dart';
import 'package:typingbot/src/engine/js_inline.dart';
import 'package:typingbot/src/engine/page.dart';

import 'support/fake_edclub.dart';

const _l1 = 'https://www.edclub.com/student/course/3/lesson/117';
const _l2 = 'https://www.edclub.com/student/course/3/lesson/118';
const _teks = 'f f j j ff ff jj jj fj jf ff jj';

Future<(FakeEdclub, Engine, List<String>)> _setup({String url = _l1}) async {
  final fake = FakeEdclub(url: url);
  final page = Page(fake.bridge, clock: fake.clock);
  await page.attach();
  final logs = <String>[];
  final eng = Engine(page: page, random: Random(3), onLog: logs.add)..st.speedWpm = 400;
  return (fake, eng, logs);
}

Future<void> _runUntil(FakeEdclub fake, Engine eng, bool Function() until, {int budget = 20000}) async {
  fake.onEval = (n) {
    if (until() || n > budget) eng.st.stop = true;
  };
  await eng.run();
}

void main() {
  group('tutorial', () {
    test('layar selesai lambat menerima Enter: TIDAK diketik ulang, Enter diulang', () async {
      final (fake, eng, logs) = await _setup();
      final tu = FakeTutorial(_teks, enterDelay: 2.5);
      fake.tutorial = tu;
      fake.nextUrl = _l2;
      await _runUntil(fake, eng, () => fake.tutorial == null && fake.url == _l2);
      expect(fake.tutorial, isNull, reason: 'tutorial harus tuntas');
      expect(tu.completions, 1);
      expect(tu.strayKeys, 0, reason: 'tak boleh mengetik ke layar selesai');
      expect(tu.earlyEnters, greaterThanOrEqualTo(1));
      expect(logs.where((l) => l.contains('(coba 2)')), isEmpty);
      expect(logs.where((l) => l.contains('kecepatan diturunkan')), isEmpty);
      expect(eng.st.stats['tut'], 1);
      // lanjut segera setelah Enter diterima (dulu ~8 dtk ketik ulang)
      expect(tu.advancedAt - tu.doneAt, lessThan(4.5));
    });

    test('Enter langsung diterima: sekali ketik, sekali Enter', () async {
      final (fake, eng, logs) = await _setup();
      final tu = FakeTutorial(_teks);
      fake.tutorial = tu;
      fake.nextUrl = _l2;
      await _runUntil(fake, eng, () => fake.tutorial == null && fake.url == _l2);
      expect(tu.completions, 1);
      expect(tu.strayKeys, 0);
      expect(logs.where((l) => l.contains('selesai - Enter')).length, 1);
      expect(logs.where((l) => l.contains('Enter lagi')), isEmpty);
    });

    test('penolakan sungguhan (kotak kembali kosong) -> diulang pelan', () async {
      final (fake, eng, logs) = await _setup();
      final tu = FakeTutorial(_teks, rejects: 1);
      fake.tutorial = tu;
      fake.nextUrl = _l2;
      await _runUntil(fake, eng, () => fake.tutorial == null && fake.url == _l2);
      expect(fake.tutorial, isNull);
      expect(tu.completions, 2);
      expect(tu.strayKeys, 0);
      expect(logs.any((l) => l.contains('(coba 2)')), isTrue);
      expect(logs.any((l) => l.contains('kecepatan diturunkan')), isTrue);
    });

    test('layar selesai macet > 15 dtk -> kembali ke jalur lama (tidak diam selamanya)', () async {
      final (fake, eng, logs) = await _setup();
      final tu = FakeTutorial(_teks, enterDelay: 1e9);
      fake.tutorial = tu;
      await _runUntil(fake, eng, () => tu.strayKeys > 0);
      expect(tu.strayKeys, greaterThan(0));
      expect(logs.any((l) => l.contains('(coba 2)')), isTrue);
    });
  });

  group('tutorial: lanjut cepat apa pun bentuk layar selesainya', () {
    test('tanda class tak pernah berubah: tidak diketik ulang, Enter diulang', () async {
      final (fake, eng, logs) = await _setup();
      final tu = FakeTutorial(_teks, sigTetap: true, enterDelay: 1.4);
      fake.tutorial = tu;
      fake.nextUrl = _l2;
      await _runUntil(fake, eng, () => fake.tutorial == null && fake.url == _l2);
      expect(fake.tutorial, isNull);
      expect(tu.strayKeys, 0, reason: 'tak boleh mengetik ke layar selesai');
      expect(logs.where((l) => l.contains('(coba 2)')), isEmpty);
      expect(tu.advancedAt - tu.doneAt, lessThan(1.4 + 0.6));
    });

    test('animasi selesai (karakter terakhir telat seragam): tetap dikenali', () async {
      final (fake, eng, logs) = await _setup();
      final tu = FakeTutorial(_teks, settle: 1.2, enterDelay: 3.2);
      fake.tutorial = tu;
      fake.nextUrl = _l2;
      await _runUntil(fake, eng, () => fake.tutorial == null && fake.url == _l2);
      expect(fake.tutorial, isNull);
      expect(tu.strayKeys, 0);
      expect(logs.where((l) => l.contains('(coba 2)')), isEmpty);
      expect(tu.advancedAt - tu.doneAt, lessThan(3.2 + 0.6));
    });

    test('layar skor muncul sendiri: Enter langsung begitu kotak hilang', () async {
      final (fake, eng, logs) = await _setup();
      final tu = FakeTutorial(_teks, autoSkor: 1.6);
      fake.tutorial = tu;
      fake.nextUrl = _l2;
      double? skorEnter;
      final lama = fake.bridge.handlers['Input.dispatchKeyEvent']!;
      fake.bridge.handlers['Input.dispatchKeyEvent'] = (p, s) {
        final dulu = fake.enterOnScore;
        final r = lama(p, s);
        if (fake.enterOnScore > dulu) skorEnter ??= fake.clock.now;
        return r;
      };
      await _runUntil(fake, eng, () => fake.url == _l2);
      expect(fake.url, _l2);
      expect(tu.strayKeys, 0);
      expect(fake.enterOnScore, 1);
      expect(logs.where((l) => l.contains('(coba 2)')), isEmpty);
      expect(skorEnter! - tu.advancedAt, lessThan(0.5),
          reason: 'Enter di layar skor tanpa menunggu putaran loop');
    });

    test('Enter pertama dikirim segera, bukan setelah tidur 0.8 dtk', () async {
      final (fake, eng, _) = await _setup();
      final tu = FakeTutorial(_teks);
      fake.tutorial = tu;
      fake.nextUrl = _l2;
      await _runUntil(fake, eng, () => fake.tutorial == null && fake.url == _l2);
      expect(tu.advancedAt - tu.doneAt, lessThan(0.3));
    });
  });

  group('modal iklan di tengah lesson', () {
    test('ditutup saat itu juga, ketikan lanjut, akurasi 100%', () async {
      const l3 = 'https://www.edclub.com/sportal/program-3/4613.play';
      final (fake, eng, logs) = await _setup(url: l3);
      final les = FakeLesson('gf ggf gf ggf hj hhj hj hhj gfg hjh gf hj');
      fake.lesson = les;
      fake.adAfterKeys = 7;
      await _runUntil(fake, eng, () => les.done);
      expect(les.done, isTrue);
      expect(les.typed.toString(), les.text);
      expect(les.errs, isEmpty, reason: 'tombol yang tertelan modal bukan salah ketik');
      expect(fake.adClosedAt, greaterThanOrEqualTo(0));
      expect(fake.adClosedAt - fake.adAt, lessThan(1.0),
          reason: 'dulu ~4 dtk (blur modal dikira user aktif)');
      expect(logs.any((l) => l.contains('modal di tengah lesson ditutup')), isTrue);
      expect(logs.where((l) => l.contains('ketikan tidak masuk')), isEmpty);
      expect(logs.where((l) => l.contains('user memegang halaman')), isEmpty);
      expect(eng.st.stats['std'], 1);
    });
  });

  group('serah-terima kendali (handOver)', () {
    test('aktivitas user sebelum handOver diabaikan, sesudahnya dihitung', () async {
      final (fake, eng, _) = await _setup();
      var elapsed = 2.0; // user klik 2 dtk lalu
      fake.overrides[userWatchJs] = () => elapsed;
      expect(await eng.userActive(25), isTrue);
      eng.st
        ..userLepas = true
        ..waitUserUrl = _l1
        ..askNextLevel = true;
      eng.handOver();
      expect(eng.st.userLepas, isFalse);
      expect(eng.st.waitUserUrl, '');
      expect(eng.st.askNextLevel, isFalse);
      expect(await eng.userActive(25), isFalse, reason: 'klik lama = sebelum serah-terima');
      // 10 dtk kemudian user klik lagi (1 dtk lalu) -> aktif
      fake.clock.advance(10);
      elapsed = 1.0;
      expect(await eng.userActive(25), isTrue);
      // klik lama itu sendiri makin tua: tetap diabaikan
      eng.handOver();
      fake.clock.advance(5);
      elapsed = 6.0;
      expect(await eng.userActive(25), isFalse);
    });

    test('mulai mesin = serah-terima: di luar lesson tidak menunggu user', () async {
      final (fake, eng, logs) = await _setup(url: 'https://www.edclub.com/student/course/3');
      fake.overrides[userWatchJs] = () => 1.5; // klik sesaat sebelum Mulai
      await _runUntil(fake, eng, () => false, budget: 300);
      expect(logs.where((l) => l.contains('kamu sedang memakai browser bot')), isEmpty);
    });
  });

  group('penutup pop-up', () {
    test('label sama di level berbeda (berjauhan) bukan "tanpa hasil"', () async {
      final (fake, eng, logs) = await _setup();
      fake.overrides[overlayJs] = () => ['tutup:[aria-label*="close" i]'];
      for (var i = 0; i < 5; i++) {
        expect(await eng.closeOverlaysAllFrames(), 1);
        fake.clock.advance(10);
      }
      expect(logs.where((l) => l.contains('eskalasi')), isEmpty);
    });

    test('layar hasil + pencapaian: [tutup],[tutup],[tutup+continue] bukan gagal 3x', () async {
      final (fake, eng, logs) = await _setup();
      var n = 0;
      fake.overrides[overlayJs] = () {
        n++;
        if (n <= 2) return ['tutup:[aria-label*="close" i]'];
        if (n == 3) return ['tutup:[aria-label*="close" i]', 'teks:"continue"'];
        return ['tutup:[aria-label*="close" i]', 'teks:"next"'];
      };
      for (var i = 0; i < 3; i++) {
        expect(await eng.closeOverlaysAllFrames(), greaterThan(0));
        fake.clock.advance(1);
      }
      expect(logs.where((l) => l.contains('eskalasi')), isEmpty);
      // penutup TIDAK dibungkam: 'next' langsung terklik di putaran berikut
      expect(await eng.closeOverlaysAllFrames(), 2);
      expect(logs.last, contains('teks:"next"'));
    });

    test('3x beruntun tanpa hasil -> eskalasi, jeda pendek (1.2 dtk)', () async {
      final (fake, eng, logs) = await _setup();
      fake.overrides[overlayJs] = () => ['tutup:[aria-label*="close" i]'];
      for (var i = 0; i < 3; i++) {
        await eng.closeOverlaysAllFrames();
        fake.clock.advance(1);
      }
      expect(logs.where((l) => l.contains('eskalasi')).length, 1);
      expect(await eng.closeOverlaysAllFrames(), 0);
      fake.clock.advance(1.3);
      expect(await eng.closeOverlaysAllFrames(), 1);
    });
  });

  group('lessonHidup (lesson UI baru hidup di iframe)', () {
    const lsn = 'https://www.edclub.com/student/course/3/lesson/129';
    Future<(FakeEdclub, Engine)> siap({required bool diumumkan}) async {
      final (fake, eng, _) = await _setup(url: lsn);
      final b = fake.bridge;
      final asli = b.handlers['Runtime.evaluate']!;
      b.handlers['Runtime.evaluate'] = (p, s) {
        final e = '${p['expression']}';
        if (s.isEmpty && e.contains(lessonHidupJs)) {
          // frame utama: hanya navbar (tanpa canvas/video, teks pendek)
          return {
            'result': {
              'type': 'object',
              'value': {'c': 0, 'v': false, 'b': 60, 'u': lsn}
            }
          };
        }
        if (s.isNotEmpty) {
          return {
            'result': {
              'type': 'object',
              'value': e.contains(detectJs) ? {'std': 'ask dad all salads', 'canvases': 0} : null
            }
          };
        }
        return asli(p, s);
      };
      void umumkan() => b.emit('Target.attachedToTarget', {
            'sessionId': 'S${b.sent.length}',
            'targetInfo': {'targetId': 'OOP1', 'type': 'iframe', 'url': 'https://coreclassictyping.edclub.app/?nst=1'},
          });
      if (diumumkan) {
        umumkan();
        await pumpEventQueue();
      } else {
        // iframe baru terlihat kalau daftar frame dibaca ulang
        b.handlers['Target.setAutoAttach'] = (p, s) {
          if (s.isEmpty && p['autoAttach'] == true) umumkan();
          return {};
        };
      }
      return (fake, eng);
    }

    test('lesson di iframe = hidup (dulu selalu "tidak hidup" 8 dtk)', () async {
      final (fake, eng) = await siap(diumumkan: true);
      final t0 = fake.clock.now;
      expect(await eng.lessonHidup(), isTrue);
      expect(fake.clock.now - t0, lessThan(0.5));
    });

    test('iframe belum terlihat mesin -> dibaca ulang, hidup < 2 dtk', () async {
      final (fake, eng) = await siap(diumumkan: false);
      final t0 = fake.clock.now;
      expect(await eng.lessonHidup(), isTrue);
      expect(fake.clock.now - t0, lessThan(2.0));
    });

    test('halaman benar2 kosong tetap "tidak hidup"', () async {
      final (fake, eng, _) = await _setup(url: lsn);
      fake.overrides[lessonHidupJs] = () => {'c': 0, 'v': false, 'b': 60, 'u': lsn};
      expect(await eng.lessonHidup(3.0), isFalse);
    });
  });
}
