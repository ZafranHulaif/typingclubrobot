// Buku akun di %LOCALAPPDATA%/TypingBot, format SAMA dgn 3.5.x
// (gui/webview2_host.py) supaya pengguna lama langsung lanjut:
//   akun/aktif.json            {"nama": "..."}  akun aktif
//   akun/akun-<nama>.json      {"nama": ..., ...} buku alamat (cookie lama)
//   profil-akun/<nama aman>/   folder data WebView2 per akun (jar)
//   wv2profile/                folder data kalau belum ada akun aktif
import 'dart:convert';
import 'dart:io';

class AccountStore {
  AccountStore(this.base);

  /// %LOCALAPPDATA%/TypingBot
  final String base;

  static String defaultBase() {
    final la = Platform.environment['LOCALAPPDATA'];
    return _j(la ?? Directory.systemTemp.path, 'TypingBot');
  }

  String get _akunDir => _j(base, 'akun');
  String get _profilDir => _j(base, 'profil-akun');

  /// Nama folder aman (sama persis dgn _folder_profil_akun 3.5.x).
  static String safeName(String name) {
    final s = name.replaceAll(RegExp(r'[<>:"/\\|?*]+'), '_').trim();
    return s.isEmpty ? 'akun' : s;
  }

  /// Folder data WebView2 utk akun [name] (null = profil awal).
  String folderFor(String? name) => name == null
      ? _j(base, 'wv2profile')
      : _j(_profilDir, safeName(name));

  String? active() {
    try {
      final m = jsonDecode(File(_j(_akunDir, 'aktif.json')).readAsStringSync());
      final n = (m as Map)['nama'];
      return n is String && n.trim().isNotEmpty ? n : null;
    } catch (_) {
      return null;
    }
  }

  void setActive(String name) {
    Directory(_akunDir).createSync(recursive: true);
    File(_j(_akunDir, 'aktif.json')).writeAsStringSync(jsonEncode({'nama': name}));
  }

  /// Semua akun: dari buku alamat + folder jar yang ada, urut abjad.
  List<String> list() {
    final names = <String, String>{}; // kunci huruf kecil -> nama
    void add(String n) {
      final t = n.replaceAll(RegExp(r'\s+'), ' ').trim();
      if (t.isNotEmpty) names.putIfAbsent(t.toLowerCase(), () => t);
    }

    try {
      for (final f in Directory(_akunDir).listSync().whereType<File>()) {
        final b = f.uri.pathSegments.last;
        if (!b.endsWith('.json') || b == 'aktif.json') continue;
        try {
          final m = jsonDecode(f.readAsStringSync()) as Map;
          add('${m['nama'] ?? ''}');
        } catch (_) {}
      }
    } catch (_) {}
    try {
      for (final d in Directory(_profilDir).listSync().whereType<Directory>()) {
        add(d.uri.pathSegments.where((s) => s.isNotEmpty).last);
      }
    } catch (_) {}
    final a = active();
    if (a != null) add(a);
    final out = names.values.toList()
      ..sort((x, y) => x.toLowerCase().compareTo(y.toLowerCase()));
    return out;
  }

  /// Nama sementara utk akun baru (nama asli dari profil edclub menyusul
  /// bersama port sesi/login di N3).
  String newName() {
    final ada = list().map((e) => e.toLowerCase()).toSet();
    var n = 1;
    String nama() => n == 1 ? 'Akun baru' : 'Akun baru $n';
    while (ada.contains(nama().toLowerCase())) {
      n++;
    }
    return nama();
  }
}

String _j(String a, String b) =>
    a.endsWith(Platform.pathSeparator) ? '$a$b' : '$a${Platform.pathSeparator}$b';
