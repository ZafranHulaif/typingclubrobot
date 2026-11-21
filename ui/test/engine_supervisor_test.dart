// N3: transisi state loop utama (supervisor) dgn edclub palsu.
import 'dart:math';

import 'package:flutter_test/flutter_test.dart';
import 'package:typingbot/src/engine/engine.dart';
import 'package:typingbot/src/engine/js.dart';
import 'package:typingbot/src/engine/js_inline.dart';
import 'package:typingbot/src/engine/page.dart';

import 'support/fake_edclub.dart';

const _l1 = 'https://www.edclub.com/student/course/3/lesson/116'; // L1
const _l2 = 'https://www.edclub.com/student/course/3/lesson/117'; // L2

Future<(FakeEdclub, Engine, List<String>)> _setup({String url = _l1, FakeLesson? lesson}) async {
  final fake = FakeEdclub(url: url)..lesson = lesson;
  final page = Page(fake.bridge, clock: fake.clock);
  await page.attach();
  final logs = <String>[];
  final eng = Engine(page: page, random: Random(3), onLog: logs.add)..st.speedWpm = 400;
  return (fake, eng, logs);
}

/// Jalankan loop sampai [until] benar atau anggaran evaluate habis.
Future<void> _runUntil(FakeEdclub fake, Engine eng, bool Function() until, {int budget = 20000}) async {
  fake.onEval = (n) {
    if (until() || n > budget) eng.st.stop = true;
  };
  await eng.run();
}

void main() {
  test('belum login: tidak mengetik apa pun; setelah login langsung kerja', () async {
    final (fake, eng, logs) = await _setup(url: 'https://www.edclub.com/signin', lesson: FakeLesson('abc'));
    fake.profile = 'out';
    var flipped = false;
    fake.onEval = (n) {
      if (!flipped && eng.st.needsLogin) {
        // tidak boleh ada ketikan selama perlu login
        expect(fake.keyEvents, isEmpty);
        flipped = true;
        fake.profile = 'in';
        fake.url = _l1;
        fake.bridge.emit('Page.frameNavigated', {
          'frame': {'id': 'MAIN', 'url': _l1}
        });
      }
      if (fake.lesson!.done || n > 20000) eng.st.stop = true;
    };
    await eng.run();
    expect(flipped, isTrue);
    expect(logs.any((l) => l.contains('Sesi edclub tidak aktif')), isTrue);
    expect(logs.any((l) => l.contains('aktif kembali')), isTrue);
    expect(fake.lesson!.done, isTrue);
    expect(fake.lesson!.errs, isEmpty);
  });

  test('lesson -> skor -> level berikut; label & posisi tercatat', () async {
    final (fake, eng, logs) = await _setup(lesson: FakeLesson('abc def', label: 'L1'));
    fake.nextUrl = _l2;
    fake.nextLesson = FakeLesson('ghi', label: 'L2');
    await _runUntil(fake, eng, () => fake.url == _l2 && fake.lesson!.done);
    expect(fake.lesson!.errs, isEmpty);
    expect(eng.levels.posisi, greaterThanOrEqualTo(1));
    expect(logs.any((l) => l.startsWith('[PROGRES]')), isTrue);
    expect(eng.st.stats['std'], 2);
  });

  test('melewati akhir rentang -> berhenti & rangeDone', () async {
    final (fake, eng, logs) = await _setup(url: _l2, lesson: FakeLesson('zzz', label: 'L2'));
    eng.st
      ..rangeReady = true
      ..levelStart = 1
      ..levelEnd = 1;
    await _runUntil(fake, eng, () => false, budget: 5000);
    expect(eng.st.rangeDone, isTrue);
    expect(fake.keyEvents, isEmpty);
    expect(logs.any((l) => l.contains('melewati akhir rentang')), isTrue);
  });

  test('lesson yang sudah terbuka saat mulai dikerjakan dulu (tanpa lompat)', () async {
    final (fake, eng, logs) = await _setup(url: _l1, lesson: FakeLesson('aaa', label: 'L1'));
    eng.st
      ..rangeReady = true
      ..levelStart = 5;
    eng.levels.posisi = 10;
    await _runUntil(fake, eng, () => fake.lesson!.done, budget: 8000);
    expect(fake.lesson!.done, isTrue);
    expect(logs.any((l) => l.contains('lompatan ke level 5 dilewati')), isTrue);
  });

  test('di daftar & user diam -> buka level awal rentang lewat peta', () async {
    final (fake, eng, _) = await _setup(url: 'https://www.edclub.com/student/course/3');
    eng.st
      ..rangeReady = true
      ..levelStart = 5
      ..levelEnd = 0;
    eng.levels.posisi = 10; // akun sudah sampai 10: level 5 pasti terbuka
    fake.overrides[lessonHidupJs] = () => {'c': 1, 'u': fake.url};
    await _runUntil(fake, eng, () => fake.navigations.isNotEmpty, budget: 5000);
    expect(fake.navigations.first, 'https://www.edclub.com/student/course/3/lesson/120');
    expect(eng.st.rangeJumpDone, isTrue);
  });

  test('renderer tak menjawab 2x -> berhenti (webview tak dibunuh)', () async {
    final (fake, eng, logs) = await _setup(lesson: FakeLesson('abc'));
    fake.alive = false;
    eng.page = eng.page; // halaman sama
    final page = eng.page;
    // evaluate menggantung -> alive() timeout pendek
    await eng.run().timeout(const Duration(seconds: 30));
    expect(eng.st.stop, isTrue);
    expect(logs.any((l) => l.contains('tidak boleh dibunuh')), isTrue);
    expect(page.closed, isFalse);
  }, timeout: const Timeout(Duration(seconds: 40)));

  test('halaman dibawa ke Stripe -> kembali ke lesson terakhir', () async {
    final (fake, eng, logs) = await _setup(lesson: FakeLesson('abcdef'));
    var hijacked = false;
    fake.onEval = (n) {
      if (!hijacked && eng.st.lastUrl.contains('.play')) {
        hijacked = true;
        fake.lesson = null;
        fake.url = 'https://checkout.stripe.com/pay/cs_live_x';
        fake.bridge.emit('Page.frameNavigated', {
          'frame': {'id': 'MAIN', 'url': fake.url}
        });
      }
      if (fake.navigations.isNotEmpty || n > 20000) eng.st.stop = true;
    };
    await eng.run();
    expect(fake.navigations.first, _l1);
    expect(logs.any((l) => l.contains('dibajak Stripe')), isTrue);
  });

  test('modal premium baru ditutup kapan pun', () async {
    final (fake, eng, logs) = await _setup(lesson: null);
    fake.premiumSkip = true;
    await _runUntil(fake, eng, () => logs.any((l) => l.contains('kapan pun')), budget: 5000);
    expect(logs.any((l) => l.contains("'Skip this lesson' (kapan pun)")), isTrue);
  });

  test('payload yang dikirim = JS verbatim dari python', () async {
    final (fake, eng, _) = await _setup(lesson: FakeLesson('ab'));
    await _runUntil(fake, eng, () => fake.lesson!.done);
    final sent = fake.bridge.named('Runtime.evaluate').map((c) => '${c.params['expression']}').toList();
    expect(sent.any((e) => e.contains(detectJs)), isTrue);
    expect(sent.any((e) => e.contains(stateJs)), isTrue);
    expect(sent.any((e) => e.contains(profileCheckJs)), isTrue);
    expect(sent.any((e) => e.contains(antiPauseJs)), isTrue);
  });
}
