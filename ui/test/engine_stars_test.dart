// N7: target bintang - rumus edclub & pacing ketik.
import 'dart:math';

import 'package:flutter_test/flutter_test.dart';
import 'package:typingbot/src/engine/engine.dart';
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
    eng.starTarget = () => 4;
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

  test('target perak (0): ketik biasa secepatnya tanpa salah', () async {
    final text = List.filled(5, 'asdf jkl ').join();
    final fake = FakeEdclub(url: _l1)..lesson = FakeLesson(text);
    fake.lessonGoal = {'goal': 10, 'min_wpm': 3, 'min_acc': 80, 'on_error': 'continue', 'n': text.length};
    final page = Page(fake.bridge, clock: fake.clock);
    await page.attach();
    final logs = <String>[];
    final eng = Engine(page: page, random: Random(3), onLog: logs.add)..st.speedWpm = 400;
    eng.starTarget = () => 0;
    fake.onEval = (n) {
      if (fake.lesson!.done || n > 20000) eng.st.stop = true;
    };
    await eng.run();
    expect(fake.lesson!.errs, isEmpty);
    expect(logs.any((x) => x.contains('[Bintang]')), isFalse);
  });
}
