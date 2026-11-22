// Buku akun di %LOCALAPPDATA%/TypingBot, format SAMA dgn 3.5.x
// (gui/webview2_host.py) supaya pengguna lama langsung lanjut:
//   akun/aktif.json            {"nama": "..."}  akun aktif
//   akun/akun-NAMA.json      {"nama": ..., ...} buku alamat (cookie lama)
//   profil-akun/<nama aman>/   folder data WebView2 per akun (jar)
//   wv2profile/                folder data kalau belum ada akun aktif
//   akun/label.json            (v4) {id: nama tampil dari edclub}
//   akun/baru.json             (v4) [id] akun baru yang BELUM berhasil login
import 'dart:convert';
import 'dart:io';

class AccountStore {
  AccountStore(this.base);

  /// %LOCALAPPDATA%/TypingBot
  final String base;

  static String defaultBase() {
    if (Platform.isMacOS) {
      // macOS: ~/Library/Application Support/TypingBot
      final home = Platform.environment['HOME'] ?? Directory.systemTemp.path;
      return _j(_j(_j(home, 'Library'), 'Application Support'), 'TypingBot');
    }
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

  /// N5: kuki edclub akun ini dari 3.5.x (akun/akun-NAMA.json, cocok
  /// lewat "nama"), atau sesi_edclub.json untuk akun yang terakhir aktif
  /// (maks 60 hari). null = tidak ada.
  List<Map<String, dynamic>>? legacyCookies(String? name) {
    String norm(String x) => x.replaceAll(RegExp(r'\s+'), ' ').trim().toLowerCase();
    List<Map<String, dynamic>>? ambil(dynamic m) {
      final c = m is Map ? m['cookies'] : null;
      if (c is! List || c.isEmpty) return null;
      return [for (final x in c) if (x is Map) x.cast<String, dynamic>()];
    }

    if (name != null) {
      try {
        for (final f in Directory(_akunDir).listSync().whereType<File>()) {
          final b = f.uri.pathSegments.last;
          if (!b.startsWith('akun-') || !b.endsWith('.json')) continue;
          try {
            final m = jsonDecode(f.readAsStringSync());
            if (m is Map && norm('${m['nama'] ?? ''}') == norm(name)) {
              final c = ambil(m);
              if (c != null) return c;
            }
          } catch (_) {}
        }
      } catch (_) {}
    }
    final a = active();
    if (name == null || (a != null && norm(a) == norm(name))) {
      try {
        final m = jsonDecode(File(_j(base, 'sesi_edclub.json')).readAsStringSync());
        final t = (m is Map ? m['t'] as num? : null) ?? 0;
        if (DateTime.now().millisecondsSinceEpoch / 1000 - t < 60 * 86400) return ambil(m);
      } catch (_) {}
    }
    return null;
  }

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
    // akun baru yang belum login disembunyikan (kecuali yang sedang dibuka)
    for (final id in pending()) {
      if (id.toLowerCase() != a?.toLowerCase()) names.remove(id.toLowerCase());
    }
    final out = names.values.toList()
      ..sort((x, y) => x.toLowerCase().compareTo(y.toLowerCase()));
    return out;
  }

  // ---- nama tampil (v4): id = nama folder, label = nama dari edclub
  Map<String, String> labels() {
    try {
      final m = jsonDecode(File(_j(_akunDir, 'label.json')).readAsStringSync()) as Map;
      return {for (final e in m.entries) '${e.key}': '${e.value}'};
    } catch (_) {
      return {};
    }
  }

  String labelOf(String id) => labels()[id] ?? id;

  void setLabel(String id, String label) {
    final m = labels()..[id] = label;
    Directory(_akunDir).createSync(recursive: true);
    File(_j(_akunDir, 'label.json')).writeAsStringSync(jsonEncode(m));
  }

  // ---- akun baru yang belum login: tidak tampil di daftar, dibuang
  // kalau ditinggal (biar tidak numpuk "Akun baru 2, 3, ...")
  Set<String> pending() {
    try {
      return {for (final e in jsonDecode(File(_j(_akunDir, 'baru.json')).readAsStringSync()) as List) '$e'};
    } catch (_) {
      return {};
    }
  }

  void _savePending(Set<String> p) {
    Directory(_akunDir).createSync(recursive: true);
    File(_j(_akunDir, 'baru.json')).writeAsStringSync(jsonEncode(p.toList()));
  }

  void addPending(String id) => _savePending(pending()..add(id));
  bool isPending(String id) => pending().contains(id);
  void clearPending(String id) => _savePending(pending()..remove(id));

  /// Buang akun baru yang ditinggal (folder jar ikut). Folder yang masih
  /// dikunci WebView2 dicoba lagi saat app dibuka berikutnya.
  void dropPending({String? except}) {
    final p = pending();
    for (final id in p.toList()) {
      if (id == except) continue;
      try {
        final d = Directory(folderFor(id));
        if (d.existsSync()) d.deleteSync(recursive: true);
        p.remove(id);
      } catch (_) {}
    }
    _savePending(p);
  }

  void clearActive() {
    try {
      File(_j(_akunDir, 'aktif.json')).deleteSync();
    } catch (_) {}
  }

  /// Hapus akun: folder jar, nama tampil, buku alamat 3.5.x. Folder yang
  /// masih dikunci WebView2 ditandai & dibuang saat app dibuka lagi.
  /// true = folder sudah hilang.
  Future<bool> delete(String id) async {
    final m = labels()..remove(id);
    try {
      Directory(_akunDir).createSync(recursive: true);
      File(_j(_akunDir, 'label.json')).writeAsStringSync(jsonEncode(m));
    } catch (_) {}
    try {
      for (final f in Directory(_akunDir).listSync().whereType<File>()) {
        final b = f.uri.pathSegments.last;
        if (!b.startsWith('akun-') || !b.endsWith('.json')) continue;
        try {
          final j = jsonDecode(f.readAsStringSync()) as Map;
          if ('${j['nama']}'.toLowerCase() == id.toLowerCase()) f.deleteSync();
        } catch (_) {}
      }
    } catch (_) {}
    final d = Directory(folderFor(id));
    for (var i = 0; i < 10; i++) {
      try {
        if (d.existsSync()) d.deleteSync(recursive: true);
        clearPending(id);
        return true;
      } catch (_) {
        await Future<void>.delayed(const Duration(milliseconds: 300));
      }
    }
    addPending(id); // tersembunyi dari daftar & dibuang nanti
    return false;
  }

  /// Nama sementara utk akun baru (nama asli dari profil edclub menyusul
  /// bersama port sesi/login di N3).
  String newName() {
    final ada = {...list(), ...pending()}.map((e) => e.toLowerCase()).toSet();
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
