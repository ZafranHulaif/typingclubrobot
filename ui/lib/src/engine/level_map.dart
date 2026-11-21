// Peta level -> URL lesson + posisi terakhir (port bagian data
// engine/levels.py). File SAMA dgn 3.5.x di %LOCALAPPDATA%/TypingBot:
// level_map.json {"87": url, ...} dan posisi_level.json {"posisi": n}.
import 'dart:convert';
import 'dart:io';

import 'js.dart' show levelPeta;
import 'urls.dart';

class LevelMap {
  /// [dir] = folder data; null = tanpa file (tes).
  LevelMap([this.dir]) {
    for (final e in levelPeta.entries) {
      map['${e.key}'] = 'https://www.edclub.com/student/course/3/lesson/${e.value}';
    }
    _load();
    _rebuild();
  }

  final String? dir;
  final map = <String, String>{};
  final _urlToLevel = <int, int>{};
  int posisi = 0;

  String? _file(String name) =>
      dir == null ? null : '$dir${Platform.pathSeparator}$name';

  void _load() {
    final f = _file('level_map.json');
    if (f == null) return;
    try {
      final data = jsonDecode(File(f).readAsStringSync());
      if (data is Map) {
        // URL .play lama dinormalkan ke rute UI baru saat dimuat
        data.forEach((k, v) => map['$k'] = lessonRouteUrl('$v'));
      }
    } catch (_) {}
  }

  void _rebuild() {
    _urlToLevel.clear();
    map.forEach((n, u) {
      final i = _idOf(u);
      final lv = int.tryParse(n);
      if (i != null && lv != null) _urlToLevel[i] = lv;
    });
  }

  static int? _idOf(String u) {
    final last = u.split('/').last.split('.').first;
    return int.tryParse(last);
  }

  /// Nomor level dari URL .play lewat peta terbalik.
  int? urlToLevel(String? url) {
    final m = RegExp(r'/program-\d+/(\d+)\.play').firstMatch(url ?? '');
    if (m == null) return null;
    return _urlToLevel[int.parse(m[1]!)];
  }

  /// Simpan level -> URL (rute UI baru `/lesson/ID`).
  void record(int nomor, String url) {
    if (nomor <= 0 || url.isEmpty || !url.contains('/lesson/')) return;
    final k = '$nomor';
    if (map[k] == url) return;
    map[k] = url;
    final i = _idOf(url);
    if (i != null) _urlToLevel[i] = nomor;
    final f = _file('level_map.json');
    if (f == null) return;
    try {
      final keys = map.keys.toList()..sort();
      final out = {for (final k in keys) k: map[k]};
      File(f).writeAsStringSync(const JsonEncoder.withIndent(' ').convert(out));
    } catch (_) {}
  }

  /// URL navigasi (rute UI baru) utk level [nomor], '' = belum ada.
  String urlFor(int nomor) {
    final u = map['$nomor'] ?? '';
    return u.isEmpty ? '' : lessonRouteUrl(u);
  }

  /// Level terakhir yang dikerjakan (tidak pernah mundur).
  void catatPosisi(int n) {
    if (n <= 0 || n <= posisi) return;
    posisi = n;
    final f = _file('posisi_level.json');
    if (f == null) return;
    try {
      File(f).writeAsStringSync(jsonEncode({'posisi': n}));
    } catch (_) {}
  }

  int muatPosisi() {
    final f = _file('posisi_level.json');
    if (f == null) return posisi;
    try {
      final m = jsonDecode(File(f).readAsStringSync()) as Map;
      posisi = (m['posisi'] as num?)?.toInt() ?? 0;
    } catch (_) {}
    return posisi;
  }
}
