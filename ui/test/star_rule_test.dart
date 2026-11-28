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

  test('peta level: mulai dari level awal, video dilewati, giliran tersimpan dipakai', () {
    final r = StarRule(type: 'pattern', pattern: [2, 4, 3]);
    final sig = r.sig('p377');
    final sel = levelMap(
      from: 377,
      to: 386,
      lastLevel: 685,
      rule: r,
      key: 'p377',
      acct: 'a',
      kinds: {'378': 'free', '380': 'balloon'},
      // level 377 sudah dapat giliran ke-1 (indeks 0)
      seq: {
        sig: {
          'n': 1,
          'lv': {'377': 0}
        }
      },
    );
    expect(sel.first.level, 377);
    expect(sel.length, 10);
    expect([for (final x in sel) x.code], [2, null, 4, 3, 2, 4, 3, 2, 4, 3]);
    expect(sel[0].assigned, isTrue);
    expect(sel[2].assigned, isFalse);
    expect(sel[1].kind, 'free');
    expect(sel[3].known, isTrue);
    expect(sel[4].known, isFalse);
    // game balon dgn aturan khusus: urutannya sendiri, tidak memakai giliran bagian
    final g = levelMap(
      from: 377,
      to: 386,
      lastLevel: 685,
      rule: r,
      key: 'p377',
      acct: 'a',
      kinds: {'378': 'free', '380': 'balloon'},
      seq: const {},
      games: {'balloon': StarRule.fixed(3)},
    );
    expect([for (final x in g) x.code], [2, null, 4, 3, 3, 2, 4, 3, 2, 4]);
    expect(g[3].game, 'balloon');
    // jendela mulai di tengah (rencana jalan) tetap menghitung dari awal
    final w = levelMap(
      from: 377,
      to: 0,
      lastLevel: 685,
      rule: r,
      key: 'p377',
      acct: 'a',
      kinds: const {},
      seq: const {},
      start: 380,
      count: 3,
    );
    expect([for (final x in w) x.level], [380, 381, 382]);
    expect([for (final x in w) x.code], [2, 4, 3]);
  });

  test('peta level: level selesai tetap menunjukkan hasilnya, jenis lewati rinci', () {
    final r = StarRule.fixed(2);
    final sel = levelMap(
      from: 80,
      to: 86,
      lastLevel: 685,
      rule: r,
      key: 'p80',
      acct: 'a',
      kinds: {'82': 'video', '83': 'premium', '84': 'tutorial'},
      seq: const {},
      done: {
        '80': {'c': 5},
        '81': {'c': 4, 'e': 3},
        '82': {'c': 0},
      },
    );
    // aturan diganti jadi tetap 2: yang selesai tidak ikut berubah
    expect([for (final x in sel) x.code], [5, 3, null, null, null, 2, 2]);
    expect([for (final x in sel) x.done], [true, true, true, false, false, false, false]);
    expect(sel[0].planned, 2);
    expect(sel[3].skip, isTrue);
    expect(sel[4].kind, 'tutorial');
    expect(isSkipKind('free'), isTrue);
    expect(isSkipKind('star'), isFalse);
  });
}
