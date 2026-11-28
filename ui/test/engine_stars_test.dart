// N7: target bintang - rumus edclub & pacing ketik.
import 'dart:math';

import 'package:flutter_test/flutter_test.dart';
import 'package:typingbot/src/engine/engine.dart';
import 'package:typingbot/src/engine/js.dart';
import 'package:typingbot/src/engine/page.dart';

import 'support/fake_edclub.dart';

const _l1 = 'https://www.edclub.com/student/course/3/lesson/116';

/// rasio edclub dari hasil (akurasi dibulatkan ke bawah, wpm dibulatkan)
double _rasio(int chars, int errors, double wpm, num goal) {
  final acc = (100 * (chars - errors) / chars).floor();
  return min(2.0, acc * acc * min(wpm.round(), 200) / (1e4 * max(1, goal)));
}

int _bintang(double r) => r >= 1 ? 5 : r >= .8 ? 4 : r >= .6 ? 3 : r >= .4 ? 2 : r >= .2 ? 1 : 0;

void main() {
  test('planStars: tiap target jatuh di pita bintangnya & lolos batas minimum', () {
    for (final goal in [10, 15, 20, 30, 45, 60, 75]) {
      for (final chars in [40, 100, 300]) {
        for (var s = 1; s <= 5; s++) {
          final p = planStars(s, goal: goal, minWpm: 3, minAcc: 80, chars: chars)!;
          final r = _rasio(chars, p.errors, p.wpm, goal);
          expect(_bintang(r), s, reason: 'goal $goal chars $chars target $s -> rasio $r');
          expect(p.accuracy, greaterThanOrEqualTo(85));
          expect(p.wpm, greaterThanOrEqualTo(3 * 1.2));
        }
      }
    }
  });

  test('salah ketik tersebar rata, tidak pernah menggerombol', () {
    final rnd = Random(7);
    for (final (chars, acc) in [(400, 85), (148, 85), (441, 90), (320, 95), (60, 85)]) {
      final e = (chars * (100 - acc) / 100).ceil();
      for (var rep = 0; rep < 50; rep++) {
        final pos = spreadErrors(chars, e, rnd).toList()..sort();
        expect(pos.length, e);
        expect(pos.first, greaterThanOrEqualTo(2));
        expect(pos.last, lessThanOrEqualTo(chars - 3));
        final stride = (chars - 4) / e;
        for (var i = 1; i < pos.length; i++) {
          // tidak ada dua salah lebih rapat dari setengah jarak rata2
          expect(pos[i] - pos[i - 1], greaterThanOrEqualTo((stride / 2).floor()),
              reason: '$chars/$acc: $pos');
          expect(pos[i] - pos[i - 1], greaterThan(1), reason: 'salah berturut2: $pos');
        }
      }
    }
    // tetap acak: dua kali panggil tidak sama
    expect(spreadErrors(400, 60, Random(1)), isNot(spreadErrors(400, 60, Random(2))));
  });

  test('planStars: lesson pendek tanpa salah ketik', () {
    final p = planStars(4, goal: 10, minWpm: 3, minAcc: 80, chars: 20)!;
    expect(p.errors, 0);
    expect(_bintang(_rasio(20, 0, p.wpm, 10)), 4);
  });

  test('target 4 bintang: bot mengetik pelan sesuai rumus + salah ketik', () async {
    final text = List.filled(20, 'asdf jkl ').join();
    final fake = FakeEdclub(url: _l1)..lesson = FakeLesson(text);
    fake.lessonGoal = {
      'goal': 10, 'min_wpm': 3, 'min_acc': 80, 'on_error': 'continue',
      'objc': false, 'test': false, 'diff': 0, 'n': text.length, 'pos': 0, 'total': 0,
    };
    final page = Page(fake.bridge, clock: fake.clock);
    await page.attach();
    final logs = <String>[];
    final eng = Engine(page: page, random: Random(3), onLog: logs.add)..st.speedWpm = 400;
    eng.starTarget = (_, _) => 4;
    fake.onEval = (n) {
      if (fake.lesson!.done || n > 200000) eng.st.stop = true;
    };
    await eng.run();
    final l = fake.lesson!;
    expect(l.done, isTrue);
    expect(logs.any((x) => x.contains('[Bintang] target 4')), isTrue);
    final n = text.length, e = l.errs.length;
    expect(e, greaterThan(0));
    final menit = (fake.keyTimes.last - fake.keyTimes.first) / 60;
    final wpm = (n - e) / 5 / menit;
    final r = _rasio(n, e, wpm, 10);
    expect(_bintang(r), 4, reason: 'wpm $wpm salah $e rasio $r');
  });

  test('planGame: kecepatan >= 1.25x goal & target terjangkau', () {
    for (final goal in [5, 10, 15, 20, 30, 45, 60, 70]) {
      for (var s = 1; s <= 5; s++) {
        final p = planGame(s, goal: goal, minWpm: 1)!;
        expect(p.wpm, greaterThanOrEqualTo(1.25 * goal));
        expect(p.wpm, lessThanOrEqualTo(gamePaceMaxWpm));
        expect(p.wpm, p.wpm.roundToDouble());
        // tanpa salah rasionya harus di atas target (ada ruang koreksi)
        expect(p.wpm / goal, greaterThan(starMidRatio[s]!));
        expect(p.realTarget, lessThanOrEqualTo(0.9));
      }
    }
    expect(planGame(0, goal: 10), isNull);
    // goal terlalu tinggi: 5 bintang butuh > 150 wpm -> tidak diatur
    expect(planGame(5, goal: 120), isNull);
  });

  test('gameMiss: loop tertutup mendarat di bintang target (simulasi)', () {
    for (final goal in [8, 10, 20, 40]) {
      for (final n in [40, 60, 150]) {
        for (var s = 1; s <= 5; s++) {
          final p = planGame(s, goal: goal, minWpm: 1)!;
          final g = FakeGame(List.filled(n, 'a').join(), goal: goal);
          while (!g.ended) {
            final st = g.stat();
            final miss = gameMiss(p,
                idx: st['idx'] as int,
                rvBefore: st['rvb'] as int,
                valids: st['v'] as int,
                durationMs: st['d'] as num);
            final dt = p.dt * 1000;
            if (miss) g.key('x', dt * 0.4);
            g.key('a', miss ? dt * 0.6 : dt);
          }
          // target terlalu rendah utk kecepatan minimum game: naik ke
          // bintang terendah yang terjangkau (p.stars)
          expect(p.stars, greaterThanOrEqualTo(s));
          expect(g.stars, p.stars, reason: 'goal $goal n $n target $s -> rasio ${g.ratio}');
        }
      }
    }
  });

  test('planGame: kecepatan minimum game, target terlalu rendah dinaikkan, coba lagi lebih cepat', () {
    for (final goal in [5, 8, 10, 20, 40]) {
      for (var s = 1; s <= 5; s++) {
        final p = planGame(s, goal: goal)!;
        expect(p.wpm, greaterThanOrEqualTo(gameMinWpm));
        // salah disengaja tidak pernah lebih dari batas aman
        expect(p.realTarget, greaterThanOrEqualTo(gameRealAccMin - 1e-9),
            reason: 'goal $goal target $s -> ${p.stars}');
        if (p.stars != s) expect(p.stars, greaterThan(s));
      }
    }
    // goal 10: 1 bintang masih terjangkau di 22 wpm (banyak salah, nyawa
    // aman); goal 5: 1 bintang butuh terlalu banyak salah -> naik
    expect(planGame(3, goal: 10)!.stars, 3);
    expect(planGame(1, goal: 10)!.stars, 1);
    expect(planGame(1, goal: 5)!.stars, greaterThan(1));
    // goal tinggi: tidak ada yang dinaikkan
    expect(planGame(1, goal: 40)!.stars, 1);
    // coba lagi sesudah gagal: lebih cepat
    expect(planGame(3, goal: 10, faster: 1.5)!.wpm, greaterThanOrEqualTo(33));
  });

  Future<(FakeGame, List<String>)> mainGame(FakeGame game, int target) async {
    final fake = FakeEdclub(url: 'https://www.edclub.com/sportal/program-3/2953.play')..game = game;
    final page = Page(fake.bridge, clock: fake.clock);
    await page.attach();
    final logs = <String>[];
    final eng = Engine(page: page, random: Random(5), onLog: logs.add)..st.speedWpm = 400;
    eng.starTarget = (_, _) => target;
    var sesudah = 0;
    fake.onEval = (n) {
      // beberapa putaran setelah tamat supaya log hasil sempat keluar
      if (game.ended) sesudah++;
      if (sesudah > 12 || n > 200000) eng.st.stop = true;
    };
    await eng.run();
    return (game, logs);
  }

  test('game balon: tiap target bintang tercapai, kecepatan di atas goal', () async {
    final text = List.filled(12, 'asdfj').join();
    for (var s = 1; s <= 5; s++) {
      final (g, logs) = await mainGame(FakeGame(text, goal: 10), s);
      final rencana = planGame(s, goal: 10)!.stars;
      expect(g.ended, isTrue);
      expect(g.stars, rencana, reason: 'target $s -> rasio ${g.ratio} wpm ${g.wpm} real ${g.realAccuracy}');
      // kecepatan minimum game (balon tidak lepas)
      expect(g.wpm, greaterThanOrEqualTo(gameMinWpm - 1));
      // tidak pernah lebih pelan dari goal (jeda goal 10 wpm = 1200 ms):
      // balon tidak sempat jatuh
      expect(g.maxGap, lessThan(1200), reason: 'target $s');
      expect(g.wpm, greaterThanOrEqualTo(12));
      // jeda nyata: tidak ada rentetan kilat (game kalah di > 250 wpm)
      expect(g.minDelay, greaterThan(100));
      expect(logs.any((x) => x.contains('[Bintang] game BalloonValley target $s')), isTrue);
      expect(logs.any((x) => x.contains('[Bintang] game selesai') && x.contains('= $rencana bintang')),
          isTrue,
          reason: logs.where((x) => x.contains('[Bintang]')).join('\n'));
    }
  });

  test('game yeti: tamat lebih awal & spasi dilompati tetap di target', () async {
    final text = List.filled(30, 'afraid guess').join(' ');
    for (final s in [2, 4, 5]) {
      final (g, _) = await mainGame(
          FakeGame(text, app: 'typing.games.MonsterAttack', goal: 10, endAfter: 70, spaceStart: true), s);
      expect(g.ended, isTrue);
      expect(g.valids, 70);
      expect(g.stars, planGame(s, goal: 10)!.stars, reason: 'target $s -> rasio ${g.ratio}');
      // huruf2 pertama setelah spasi tidak tersambar rantai cepat
      expect(g.minDelay, greaterThan(100));
    }
  });

  test('game belum teruji / target perak: secepatnya tanpa salah', () async {
    final text = List.filled(8, 'asdfj').join();
    final (g, logs) = await mainGame(FakeGame(text, app: 'typing.games.TempleBash'), 3);
    expect(g.ended, isTrue);
    expect(g.misses, 0);
    expect(logs.any((x) => x.contains('[Bintang]') && x.contains('belum teruji')), isTrue);
    final (g2, logs2) = await mainGame(FakeGame(text), 0);
    expect(g2.ended, isTrue);
    expect(g2.misses, 0);
    expect(logs2.any((x) => x.contains('[Bintang]')), isFalse);
  });

  test('game: data belum terbaca -> ditahan dulu, lalu menyerah dengan log', () async {
    final text = List.filled(8, 'asdfj').join();
    final fake = FakeEdclub(url: 'https://www.edclub.com/sportal/program-3/2953.play')
      ..game = FakeGame(text);
    var nStat = 0;
    fake.overrides[gameStatJs] = () {
      nStat++;
      return null;
    };
    final page = Page(fake.bridge, clock: fake.clock);
    await page.attach();
    final logs = <String>[];
    final eng = Engine(page: page, random: Random(5), onLog: logs.add)..st.speedWpm = 400;
    eng.starTarget = (_, _) => 4;
    fake.onEval = (n) {
      // selama ditahan belum ada huruf yang masuk
      if (nStat <= 15) expect(fake.game!.valids, 0);
      if (fake.game!.ended || n > 200000) eng.st.stop = true;
    };
    await eng.run();
    expect(fake.game!.ended, isTrue);
    expect(logs.any((x) => x.contains('[Bintang]') && x.contains('tidak terbaca')), isTrue);
  });

  test('target perak (0): ketik biasa secepatnya tanpa salah', () async {
    final text = List.filled(5, 'asdf jkl ').join();
    final fake = FakeEdclub(url: _l1)..lesson = FakeLesson(text);
    fake.lessonGoal = {'goal': 10, 'min_wpm': 3, 'min_acc': 80, 'on_error': 'continue', 'n': text.length};
    final page = Page(fake.bridge, clock: fake.clock);
    await page.attach();
    final logs = <String>[];
    final eng = Engine(page: page, random: Random(3), onLog: logs.add)..st.speedWpm = 400;
    eng.starTarget = (_, _) => 0;
    fake.onEval = (n) {
      if (fake.lesson!.done || n > 20000) eng.st.stop = true;
    };
    await eng.run();
    expect(fake.lesson!.errs, isEmpty);
    expect(logs.any((x) => x.contains('[Bintang]')), isFalse);
  });

  // ------------------------------------------------------------ mode Manual
  test('planManual: perkiraan bintang = rumus edclub, platinum hanya tanpa salah', () {
    for (final goal in [10, 20, 30, 45]) {
      for (final wpm in [40, 85, 140, 200, 400]) {
        for (final acc in [85, 90, 95, 100]) {
          final p = planManual(
              wpm: wpm, acc: acc, goal: goal, minWpm: 3, minAcc: 80, chars: 200);
          final r = _rasio(200, p.errors, p.wpm, goal);
          expect(p.stars, _bintang(r), reason: 'goal $goal $wpm wpm $acc%');
          expect(p.acc, greaterThanOrEqualTo(acc));
          expect(p.silver, acc == 100 && r >= 2);
          expect(p.wpmRaised || p.accRaised, isFalse);
        }
      }
    }
  });

  test('planManual: di bawah batas level dinaikkan secukupnya', () {
    final p = planManual(wpm: 40, acc: 85, goal: 50, minWpm: 40, minAcc: 90, chars: 200);
    expect(p.wpmRaised, isTrue);
    expect(p.wpm, 49); // 40 * 1.2 + 0.5, dibulatkan ke atas
    expect(p.accRaised, isTrue);
    expect(p.acc, greaterThanOrEqualTo(95));
    // mode blokir & lesson pendek: selalu 100%
    final b = planManual(wpm: 85, acc: 90, goal: 20, chars: 200, canErr: false);
    expect(b.errors, 0);
    expect(b.accFixed, isTrue);
    expect(planManual(wpm: 85, acc: 90, goal: 20, chars: 20).errors, 0);
    // 100% di 400 wpm = platinum (perilaku lama)
    expect(planManual(wpm: 400, acc: 100, goal: 30, chars: 200).silver, isTrue);
  });

  test('planManualGame: 100% & cepat = jalur lama, selain itu dibatasi', () {
    expect(planManualGame(wpm: 400, acc: 100, goal: 10), isNull);
    expect(planManualGame(wpm: 85, acc: 90, goal: 130), isNull); // goal terlalu tinggi
    final (p, m) = planManualGame(wpm: 400, acc: 90, goal: 20)!;
    expect(p.wpm, gamePaceMaxWpm);
    expect(p.realTarget, closeTo(0.9, 1e-9));
    expect(m.stars, 5);
    final (p2, m2) = planManualGame(wpm: 10, acc: 95, goal: 20)!;
    expect(p2.wpm, 25); // minimal 1.25x goal
    expect(m2.wpmRaised, isTrue);
  });

  test('mode Manual: lesson diketik di kecepatan & akurasi pilihan, perkiraan cocok', () async {
    final text = List.filled(20, 'asdf jkl ').join();
    final fake = FakeEdclub(url: _l1)..lesson = FakeLesson(text);
    fake.lessonGoal = {
      'goal': 10, 'min_wpm': 3, 'min_acc': 80, 'on_error': 'continue',
      'objc': false, 'test': false, 'diff': 0, 'n': text.length, 'pos': 0, 'total': 0,
    };
    final page = Page(fake.bridge, clock: fake.clock);
    await page.attach();
    final logs = <String>[];
    final eng = Engine(page: page, random: Random(3), onLog: logs.add)..st.speedWpm = 40;
    eng.starTarget = (_, _) => 5; // diabaikan: mode Manual menang
    eng.manual = (_) => (wpm: 40, acc: 90);
    Map<String, dynamic>? goal;
    fake.onEval = (n) {
      goal ??= eng.st.lessonGoal;
      if (fake.lesson!.done || n > 200000) eng.st.stop = true;
    };
    await eng.run();
    final l = fake.lesson!;
    expect(l.done, isTrue);
    expect(logs.any((x) => x.contains('[Manual] 40 wpm, akurasi 90%')), isTrue);
    expect(logs.any((x) => x.contains('[Bintang]')), isFalse);
    final n = text.length, e = l.errs.length;
    expect(100 * (n - e) / n, inInclusiveRange(90, 92));
    final menit = (fake.keyTimes.last - fake.keyTimes.first) / 60;
    final wpm = (n - e) / 5 / menit;
    expect(wpm, closeTo(40, 3));
    final guess = guessManual(goal!, 40, 90)!;
    expect(guess.stars, _bintang(_rasio(n, e, wpm, 10)));
  });

  test('mode Manual 100%: jalur ketik biasa tanpa salah', () async {
    final text = List.filled(5, 'asdf jkl ').join();
    final fake = FakeEdclub(url: _l1)..lesson = FakeLesson(text);
    fake.lessonGoal = {'goal': 10, 'min_wpm': 3, 'min_acc': 80, 'on_error': 'continue', 'n': text.length};
    final page = Page(fake.bridge, clock: fake.clock);
    await page.attach();
    final logs = <String>[];
    final eng = Engine(page: page, random: Random(3), onLog: logs.add)..st.speedWpm = 400;
    eng.manual = (_) => (wpm: 400, acc: 100);
    fake.onEval = (n) {
      if (fake.lesson!.done || n > 20000) eng.st.stop = true;
    };
    await eng.run();
    expect(fake.lesson!.errs, isEmpty);
    expect(logs.any((x) => x.contains('[Manual]') && x.contains('5 platinum')), isTrue);
  });

  test('mode Manual di game balon: akurasi asli & bintang sesuai perkiraan', () async {
    final text = List.filled(12, 'asdfj').join();
    final game = FakeGame(text, goal: 10);
    final fake = FakeEdclub(url: 'https://www.edclub.com/sportal/program-3/2953.play')..game = game;
    final page = Page(fake.bridge, clock: fake.clock);
    await page.attach();
    final logs = <String>[];
    final eng = Engine(page: page, random: Random(5), onLog: logs.add)..st.speedWpm = 40;
    eng.manual = (_) => (wpm: 40, acc: 90);
    var sesudah = 0;
    fake.onEval = (n) {
      if (game.ended) sesudah++;
      if (sesudah > 12 || n > 200000) eng.st.stop = true;
    };
    await eng.run();
    expect(game.ended, isTrue);
    expect(logs.any((x) => x.contains('[Manual] game BalloonValley')), isTrue);
    final (_, m) = planManualGame(wpm: 40, acc: 90, goal: 10)!;
    expect(game.stars, m.stars, reason: 'rasio ${game.ratio} wpm ${game.wpm} real ${game.realAccuracy}');
    expect(game.realAccuracy, inInclusiveRange(85, 95));
  });
}
