// Aturan bintang: pola, acak stabil, format lama, teks pola.
import 'package:flutter_test/flutter_test.dart';
import 'package:typingbot/src/state/star_rule.dart';

void main() {
  test('format lama {stars, silver} = target tetap', () {
    final r = StarRule.fromJson({'from': 1, 'stars': 5, 'silver': true});
    expect(r.type, 'fixed');
    expect(r.code, platinumCode);
    expect(engineTarget(r.code), 0);
    expect(StarRule.fromJson({'stars': 3}).code, 3);
    // pola kosong / rusak = tetap
    expect(StarRule.fromJson({'rule': 'pattern', 'pattern': [], 'stars': 4}).type, 'fixed');
    // tetap menulis stars/silver utk versi lama
    final j = StarRule(type: 'pattern', pattern: [2, 4, 6]).toJson();
    expect(j['pattern'], [2, 4, 6]);
    expect(j.containsKey('stars'), isTrue);
  });

  test('pola berputar per giliran', () {
    final r = StarRule(type: 'pattern', pattern: [2, 4, 4, 3, 4]);
    expect([for (var i = 0; i < 7; i++) r.at(i, 's')], [2, 4, 4, 3, 4, 2, 4]);
  });

  test('acak: di dalam rentang, stabil, beda tiap akun, tidak berurutan', () {
    final r = StarRule(type: 'random', min: 3, max: platinumCode);
    final a = [for (var i = 0; i < 200; i++) r.at(i, 'akunA|x')];
    expect(a.every((c) => c >= 3 && c <= platinumCode), isTrue);
    expect([for (var i = 0; i < 200; i++) r.at(i, 'akunA|x')], a);
    expect([for (var i = 0; i < 200; i++) r.at(i, 'akunB|x')], isNot(a));
    // semua nilai muncul, kurang lebih rata
    for (var c = 3; c <= platinumCode; c++) {
      expect(a.where((x) => x == c).length, inInclusiveRange(25, 80), reason: 'kode $c');
    }
    // bukan deret 3,4,5,6,3,4,...
    var urut = 0;
    for (var i = 1; i < a.length; i++) {
      if (a[i] == a[i - 1] + 1) urut++;
    }
    expect(urut, lessThan(100));
    // min > max dirapikan
    final b = StarRule.fromJson({'rule': 'random', 'min': 5, 'max': 2});
    expect((b.min, b.max), (2, 5));
  });

  test('tanda aturan berubah = urutan baru', () {
    final a = StarRule(type: 'pattern', pattern: [2, 4]);
    final b = StarRule(type: 'pattern', pattern: [2, 4, 5]);
    expect(a.sig('p1'), isNot(b.sig('p1')));
    expect(a.sig('p1'), a.copy().sig('p1'));
    expect(a.sig('p1'), isNot(a.sig('p2')));
  });

  test('teks pola', () {
    expect(parsePattern('2,4,4,3,4'), [2, 4, 4, 3, 4]);
    expect(parsePattern('3 5 3 3 4'), [3, 5, 3, 3, 4]);
    expect(parsePattern('24434'), [2, 4, 4, 3, 4]);
    expect(parsePattern('4, p, 3'), [4, platinumCode, 3]);
    expect(parsePattern(''), isEmpty);
    expect(parsePattern('2,9'), isNull);
    expect(parsePattern('abc'), isNull);
    expect(patternText([4, platinumCode, 3]), '4, p, 3');
    expect(parsePattern(List.filled(30, '3').join(','))!.length, maxPatternLen);
  });
}
