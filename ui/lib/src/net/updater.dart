// Port bagian cek versi net/updater.py. Unduh & pasang menyusul di N6
// (v4 = folder, bukan satu exe; jalur pembaruan dari 3.5.x belum diputus).
import 'api.dart';

/// "3.5.5-dev5" -> [3, 5, 5] (akhiran -devN dibuang).
List<int> parseVersion(String s) {
  final teks = s.trim().split('-').first;
  final out = <int>[];
  for (final x in teks.split('.')) {
    final n = int.tryParse(x);
    if (n == null) break;
    out.add(n);
  }
  return out.isEmpty ? [0] : out;
}

bool isNewer(String remote, String local) {
  final a = parseVersion(remote), b = parseVersion(local);
  final n = a.length > b.length ? a.length : b.length;
  for (var i = 0; i < n; i++) {
    final x = i < a.length ? a[i] : 0, y = i < b.length ? b[i] : 0;
    if (x != y) return x > y;
  }
  return false;
}

/// Info rilis baru bila ada & lebih baru dari [appVersion], selain itu null.
Future<Map<String, dynamic>?> checkUpdate(Api api, String appVersion) async {
  Map<String, dynamic>? info;
  try {
    info = await api.fetchLatest();
  } on Unreachable {
    return null;
  }
  final v = '${info?['version'] ?? ''}';
  if (info == null || v.isEmpty || !isNewer(v, appVersion)) return null;
  return info;
}
