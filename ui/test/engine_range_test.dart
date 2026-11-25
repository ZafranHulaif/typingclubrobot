// Rentang level: berhenti sendiri sesudah level terakhir kursus, juga
// tanpa batas akhir ('akhir kursus'). Live 4.0.7: sesudah level 685 edclub
// balik ke halaman kursus dan bot diam di sana ~1 jam.
import 'package:flutter_test/flutter_test.dart';
import 'package:typingbot/src/engine/engine.dart';
import 'package:typingbot/src/engine/page.dart';

import 'support/fake_edclub.dart';

const _l685 = 'https://www.edclub.com/sportal/program-3/52748.play';
const _l600 = 'https://www.edclub.com/sportal/program-3/3184.play';
const _kursus = 'https://www.edclub.com/student/course/3';

void main() {
  Future<(Engine, List<String>)> mesin({int mulai = 1, int akhir = 0}) async {
    final fake = FakeEdclub(url: _kursus);
    final page = Page(fake.bridge, clock: fake.clock);
    final logs = <String>[];
    final eng = Engine(page: page, onLog: logs.add);
    eng.st
      ..rangeReady = true
      ..levelStart = mulai
      ..levelEnd = akhir
      ..rangeJumpDone = mulai <= 1;
    return (eng, logs);
  }

  test('rentang sampai akhir kursus: keluar dari level 685 = selesai', () async {
    final (eng, logs) = await mesin(mulai: 505);
    expect(await eng.rangeCheck(_l685), isFalse);
    expect(eng.st.rangeMaxSeen, 685);
    expect(await eng.rangeCheck(_kursus), isTrue);
    expect(eng.st.rangeDone, isTrue);
    expect(eng.st.stop, isTrue);
    expect(logs.last, contains('level akhir 685 selesai'));
  });

  test('tanpa rentang sama sekali: sesudah level 685 juga selesai', () async {
    final (eng, _) = await mesin();
    await eng.rangeCheck(_l685);
    expect(await eng.rangeCheck(_kursus), isTrue);
    expect(eng.st.rangeDone, isTrue);
  });

  test('tanpa rentang, keluar dari level biasa: bukan selesai', () async {
    final (eng, _) = await mesin();
    expect(await eng.rangeCheck(_l600), isFalse);
    expect(eng.st.rangeMaxSeen, 600);
    expect(await eng.rangeCheck(_kursus), isFalse);
    expect(eng.st.rangeDone, isFalse);
    expect(eng.st.stop, isFalse);
  });
}
