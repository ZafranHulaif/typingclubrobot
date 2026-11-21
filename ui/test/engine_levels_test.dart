// N3: urutan level (lompat daftar URUT KETAT), aturan URL, peta level.
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:typingbot/src/engine/engine.dart';
import 'package:typingbot/src/engine/js.dart';
import 'package:typingbot/src/engine/level_map.dart';
import 'package:typingbot/src/engine/urls.dart';

/// Jalankan [fnJs] (string fungsi) di node dgn DOM tiruan berisi baris
/// daftar lesson UI baru. null = node tak ada (tes dilewati).
Future<dynamic> _runDaftar(String fnJs, List<Map<String, Object>> rows, Map arg) async {
  final dir = Directory.systemTemp.createTempSync('tb_daftar_');
  try {
    final f = File('${dir.path}/t.js');
    f.writeAsStringSync('''
const rows = ${jsonEncode(rows)}.map(r => ({
  getAttribute: (n) => n === 'aria-label'
     ? ('Lesson ' + r.no + ': Judul' + (r.locked ? '. Lesson is locked' : '')) : null,
  className: ''
}));
globalThis.document = { querySelectorAll: (s) => s.startsWith('a[aria-label') ? rows : [] };
console.log(JSON.stringify(($fnJs)(${jsonEncode(arg)})));
''');
    final r = await Process.run('node', [f.path]);
    if (r.exitCode != 0) throw StateError('node: ${r.stderr}');
    return jsonDecode('${r.stdout}'.trim());
  } on ProcessException {
    return null;
  } finally {
    dir.deleteSync(recursive: true);
  }
}

List<Map<String, Object>> _rows(int n, {Set<int> locked = const {}}) =>
    [for (var i = 1; i <= n; i++) {'no': i, 'locked': locked.contains(i)}];

void main() {
  bool hasNode() {
    try {
      return Process.runSync('node', ['-v']).exitCode == 0;
    } catch (_) {
      return false;
    }
  }

  final node = hasNode();

  group('lompat daftar urut ketat (_DAFTAR_JS)', () {
    test('perbaikan regex: \\\\d -> \\d', () {
      expect(daftarJs, contains(r'(\\d+)'));
      expect(daftarJsFixed, isNot(contains(r'(\\d+)')));
      expect(daftarJsFixed, contains(r'/Lesson (\d+)/'));
    });

    test('baris terbuka pertama SETELAH level sekarang, lewati yang terkunci', () async {
      final r = await _runDaftar(daftarJsFixed, _rows(10, locked: {6}), {'awal': 0, 'cari': 5});
      expect(r, 6); // indeks baris Lesson 7
    }, skip: node ? false : 'node tidak ada');

    test('tidak pernah mundur ke baris sebelum posisi', () async {
      final r = await _runDaftar(daftarJsFixed, _rows(10), {'awal': 0, 'cari': 8});
      expect(r, 8); // Lesson 9, bukan Lesson 1
    }, skip: node ? false : 'node tidak ada');

    test('semua sesudahnya terkunci -> baris terkunci pertama (modal Skip anyways)', () async {
      final r = await _runDaftar(daftarJsFixed, _rows(6, locked: {4, 5, 6}), {'awal': 0, 'cari': 3});
      expect(r, 3);
    }, skip: node ? false : 'node tidak ada');

    test('versi verbatim 3.5.x memang salah (mundur ke baris awal)', () async {
      final r = await _runDaftar(daftarJs, _rows(10), {'awal': 0, 'cari': 8});
      expect(r, 0); // bug yang diperbaiki daftarJsFixed
    }, skip: node ? false : 'node tidak ada');
  });

  group('aturan URL', () {
    test('rute lesson baru <-> .play', () {
      const route = 'https://www.edclub.com/student/course/3/lesson/116';
      const play = 'https://www.edclub.com/sportal/program-3/116.play';
      expect(lessonPlayUrl(route), play);
      expect(lessonRouteUrl(play), route);
      expect(lessonPlayUrl('https://www.edclub.com/student/course/3'),
          'https://www.edclub.com/student/course/3');
      expect(lessonId(play), 116);
      expect(diLesson(route), isTrue);
      expect(diLesson(play), isTrue);
      expect(diLesson('https://www.edclub.com/student/course/3'), isFalse);
    });

    test('host asli, bukan substring (Stripe menyebut edclub.com)', () {
      expect(isEdclubUrl('https://www.edclub.com/x'), isTrue);
      expect(isEdclubUrl('https://checkout.stripe.com/?r=https://edclub.com'), isFalse);
      expect(isEdclubFrameUrl('https://corevideo.edclub.app/p'), isTrue);
      expect(isEdclubFrameUrl('about:blank'), isTrue);
      expect(isEdclubFrameUrl('https://js.stripe.com/v3'), isFalse);
    });

    test('alur OAuth dikenali', () {
      expect(isOauthUrl('https://accounts.google.com/o/oauth2/auth?x'), isTrue);
      expect(isOauthUrl('https://www.edclub.com/auth_callback/google'), isTrue);
      expect(isOauthUrl('https://www.edclub.com/signin'), isFalse);
    });
  });

  group('peta level', () {
    late Directory tmp;
    setUp(() => tmp = Directory.systemTemp.createTempSync('tb_lv_'));
    tearDown(() => tmp.deleteSync(recursive: true));

    test('peta bawaan 685 level, peta terbalik dari URL .play', () {
      final m = LevelMap();
      expect(m.map.length, 685);
      expect(m.urlFor(1), 'https://www.edclub.com/student/course/3/lesson/116');
      expect(m.urlToLevel('https://www.edclub.com/sportal/program-3/116.play'), 1);
      expect(m.urlToLevel('https://www.edclub.com/sportal/program-3/2937.play'), 8);
    });

    test('level_map.json user menimpa bawaan (URL .play dinormalkan)', () {
      File('${tmp.path}/level_map.json').writeAsStringSync(
          jsonEncode({'1': 'https://www.edclub.com/sportal/program-3/999.play'}));
      final m = LevelMap(tmp.path);
      expect(m.urlFor(1), 'https://www.edclub.com/student/course/3/lesson/999');
      expect(m.urlToLevel('https://www.edclub.com/sportal/program-3/999.play'), 1);
    });

    test('record tersimpan; posisi tidak pernah mundur', () {
      final m = LevelMap(tmp.path);
      m.record(700, 'https://www.edclub.com/student/course/3/lesson/77777');
      m.record(701, 'https://www.edclub.com/sportal/program-3/1.play'); // bukan rute baru: abaikan
      final again = LevelMap(tmp.path);
      expect(again.urlFor(700), endsWith('/77777'));
      expect(again.map.containsKey('701'), isFalse);
      m.catatPosisi(12);
      m.catatPosisi(9);
      expect(m.posisi, 12);
      expect(LevelMap(tmp.path).muatPosisi(), 12);
    });
  });
}
