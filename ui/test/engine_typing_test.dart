// N3: akurasi & timing mesin ketik (spesifikasi = _test_harness.py 3.5.x:
// lesson harus selesai TANPA karakter salah tersisa di semua skenario).
import 'dart:math';

import 'package:flutter_test/flutter_test.dart';
import 'package:typingbot/src/engine/engine.dart';
import 'package:typingbot/src/engine/page.dart';

import 'support/fake_edclub.dart';

Future<(FakeEdclub, Engine)> _setup(FakeLesson lesson, {int wpm = 400, double keyCostMs = 0}) async {
  final fake = FakeEdclub(keyCostMs: keyCostMs)..lesson = lesson;
  final page = Page(fake.bridge, clock: fake.clock);
  await page.attach();
  final eng = Engine(page: page, random: Random(7))..st.speedWpm = wpm;
  return (fake, eng);
}

const _sample = 'The quick brown fox jumps over the lazy dog.\n'
    'Pack my box with five dozen liquor jugs!\n'
    'Tab\there, "quotes" & symbols: 1+2=3; (ok) [yes] {no} ~`|\\/?<>';

void main() {
  group('akurasi lesson standar (harus 100%)', () {
    test('teks bersih: huruf, kapital, simbol, Enter, Tab', () async {
      final (fake, eng) = await _setup(FakeLesson(_sample));
      final ok = await eng.handleStandard(eng.page.mainFrame, _sample);
      expect(ok, isTrue);
      expect(fake.lesson!.done, isTrue);
      expect(fake.lesson!.errs, isEmpty);
      expect(fake.typed, _sample);
      expect(eng.st.stats['std'], 1);
      expect(eng.st.levelProgress, 1.0);
    });

    test('keystroke hilang (tiap ke-7) tetap selesai tanpa salah', () async {
      final l = FakeLesson(_sample);
      for (var i = 3; i < 400; i += 7) {
        l.dropAt.add(i);
      }
      final (fake, eng) = await _setup(l);
      await eng.handleStandard(eng.page.mainFrame, _sample);
      expect(fake.lesson!.done, isTrue);
      expect(fake.lesson!.errs, isEmpty);
    });

    test('jari meleset (situs menandai salah) -> Backspace & ketik ulang', () async {
      final l = FakeLesson(_sample)..wrongOnceAt.addAll({5, 40, 41, 90});
      final (fake, eng) = await _setup(l);
      await eng.handleStandard(eng.page.mainFrame, _sample);
      expect(fake.lesson!.done, isTrue);
      expect(fake.lesson!.errs, isEmpty);
      // ada Backspace yang dikirim
      expect(fake.keyEvents.where((e) => e['windowsVirtualKeyCode'] == 8 && e['type'] == 'rawKeyDown'),
          isNotEmpty);
    });

    test('salah sudah ada sebelum mulai -> dikoreksi dulu', () async {
      final l = FakeLesson('abcdef');
      l.key('x'); // salah di posisi 0
      final (fake, eng) = await _setup(l);
      await eng.handleStandard(eng.page.mainFrame, 'abcdef');
      expect(fake.lesson!.done, isTrue);
      expect(fake.lesson!.errs, isEmpty);
    });

    test('render progresif (baris berikut muncul telat) tanpa Enter dobel', () async {
      final l = FakeLesson('first line\nsecond line\nthird')
        ..progressive = true
        ..revealDelay = 3;
      final (fake, eng) = await _setup(l);
      await eng.handleStandard(eng.page.mainFrame, l.text);
      expect(fake.lesson!.done, isTrue);
      expect(fake.lesson!.errs, isEmpty);
      expect(fake.typed, l.text);
    });

    test('stage belum siap (5 tombol pertama diabaikan) tetap tuntas', () async {
      final l = FakeLesson('hello world')..ignoreFirst = 5;
      final (fake, eng) = await _setup(l);
      // percobaan pertama bisa gagal konsumsi; supervisor memanggil ulang
      for (var i = 0; i < 4 && !fake.lesson!.done; i++) {
        await eng.handleStandard(eng.page.mainFrame, l.text);
      }
      expect(fake.lesson!.done, isTrue);
      expect(fake.lesson!.errs, isEmpty);
    });

    test('lesson selesai -> layar skor -> Enter -> level berikut', () async {
      final (fake, eng) = await _setup(FakeLesson('abc'));
      fake.nextUrl = 'https://www.edclub.com/student/course/3/lesson/117';
      await eng.handleStandard(eng.page.mainFrame, 'abc');
      expect(fake.enterOnScore, 1);
      expect(fake.url, endsWith('/117'));
    });

    test('STOP di tengah = berhenti mengetik', () async {
      final (fake, eng) = await _setup(FakeLesson('a' * 200));
      var n = 0;
      fake.overrides[''] = () => null; // tidak dipakai; jaga urutan map
      fake.overrides.remove('');
      fake.bridge.handlers['Input.insertText'] = (p, s) => {};
      final orig = fake.bridge.handlers['Input.dispatchKeyEvent']!;
      fake.bridge.handlers['Input.dispatchKeyEvent'] = (p, s) {
        if (++n == 40) eng.st.stop = true;
        return orig(p, s);
      };
      await eng.handleStandard(eng.page.mainFrame, 'a' * 200);
      expect(fake.lesson!.done, isFalse);
      expect(fake.lesson!.pos, lessThan(60));
    });
  });

  group('timing', () {
    test('charDelay: target wpm, overhead dikompensasi, tak pernah > target', () async {
      final (_, eng) = await _setup(FakeLesson('x'), wpm: 140);
      eng.st.loopOverhead = 0.0;
      for (var i = 0; i < 50; i++) {
        final d = eng.charDelay();
        expect(d, inInclusiveRange(12 / 140 * 0.85, 12 / 140 * 1.15));
      }
      // overhead raksasa: jeda min 30% ideal (laju tak melewati target)
      eng.st.loopOverhead = 5.0;
      for (var i = 0; i < 50; i++) {
        expect(eng.charDelay(), greaterThanOrEqualTo(12 / 140 * 0.35 * 0.85));
      }
      // tutorial: batas 140 wpm walau setelan 400
      eng.st.speedWpm = 400;
      eng.st.loopOverhead = 0;
      expect(eng.charDelay(wpmCap: 140), greaterThan(12 / 140 * 0.8));
      expect(eng.charDelay(slow: true), inInclusiveRange(0.14, 0.24));
    });

    test('typeBurst: overhead CDP terukur (EMA) -> laju akhir = target', () async {
      // tiap event tombol makan 6 ms (down+up = 12 ms per huruf)
      final (fake, eng) = await _setup(FakeLesson('z' * 2000), wpm: 200, keyCostMs: 6);
      final clock = fake.clock;
      for (var i = 0; i < 12; i++) {
        await eng.typeBurst('zzzzzzzz');
      }
      expect(eng.st.burstOverheadMs, closeTo(12, 1.5));
      final t0 = clock.now;
      await eng.typeBurst('z' * 100);
      final perChar = (clock.now - t0) / 100 * 1000;
      expect(perChar, closeTo(12000 / 200, 3)); // 60 ms/huruf = 200 wpm
    });

    test('typeBurst: Tab ditekan eksplisit, Enter lewat type()', () async {
      final (fake, eng) = await _setup(FakeLesson('a\tb\nc'));
      await eng.typeBurst('a\tb\nc');
      final downs = fake.keyEvents
          .where((e) => e['type'] != 'keyUp')
          .map((e) => e['windowsVirtualKeyCode'])
          .toList();
      expect(downs, [65, 9, 66, 13, 67]);
    });
  });
}
