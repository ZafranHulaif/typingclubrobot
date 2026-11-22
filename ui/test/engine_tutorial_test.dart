// Tutorial boxed: selesai sekali, layar selesai tidak diketik ulang;
// penolakan sungguhan tetap diulang pelan. Plus serah-terima kendali
// user (handOver) & hitungan 'klik tutup tanpa hasil'.
import 'dart:math';

import 'package:flutter_test/flutter_test.dart';
import 'package:typingbot/src/engine/engine.dart';
import 'package:typingbot/src/engine/js.dart';
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

    test('3x beruntun tanpa hasil -> eskalasi, jeda hanya 3 dtk', () async {
      final (fake, eng, logs) = await _setup();
      fake.overrides[overlayJs] = () => ['tutup:[aria-label*="close" i]'];
      for (var i = 0; i < 3; i++) {
        await eng.closeOverlaysAllFrames();
        fake.clock.advance(1);
      }
      expect(logs.where((l) => l.contains('eskalasi')).length, 1);
      expect(await eng.closeOverlaysAllFrames(), 0);
      fake.clock.advance(3);
      expect(await eng.closeOverlaysAllFrames(), 1);
    });
  });
}
