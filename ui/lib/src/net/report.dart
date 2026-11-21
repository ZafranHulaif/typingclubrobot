// Lapor bug (port m_report_send sidecar): kirim ke worker /api/lapor
// {versi, akun, isi}; gagal = simpan ke Desktop utk dikirim manual.
import 'dart:io';

import 'api.dart';

String buildReport({
  required String version,
  required String account,
  required String category,
  required String text,
  required List<String> logTail,
  DateTime? at,
}) {
  final t = at ?? DateTime.now();
  String two(int n) => n.toString().padLeft(2, '0');
  final waktu = '${t.year}-${two(t.month)}-${two(t.day)} '
      '${two(t.hour)}:${two(t.minute)}:${two(t.second)}';
  return 'TypingBot laporan bug\nversi: $version\n'
      'akun aktif: $account\nkategori: $category\n'
      'waktu: $waktu\n\n'
      '${text.isNotEmpty ? '=== CERITA USER ===\n$text\n\n' : ''}'
      '=== LOG (400 baris terakhir) ===\n${logTail.join('\n')}\n';
}

/// true = terkirim. false = disimpan ke [savedTo] (Desktop).
Future<({bool sent, String? savedTo})> sendReport(Api api,
    {required String version, required String account, required String isi}) async {
  try {
    final (st, _) = await api.json('POST', '/api/lapor',
        body: {'versi': version, 'akun': account, 'isi': isi},
        timeout: const Duration(seconds: 15));
    if (st == 200) return (sent: true, savedTo: null);
  } on Unreachable {
    // lanjut ke cadangan
  }
  final home = Platform.environment['USERPROFILE'] ?? Platform.environment['HOME'] ?? '.';
  final sep = Platform.pathSeparator;
  var desk = '$home${sep}Desktop';
  if (!Directory(desk).existsSync() && Directory('$home${sep}OneDrive${sep}Desktop').existsSync()) {
    desk = '$home${sep}OneDrive${sep}Desktop';
  }
  try {
    Directory(desk).createSync(recursive: true);
    final t = DateTime.now();
    String two(int n) => n.toString().padLeft(2, '0');
    final p = '$desk${sep}TypingBot-laporan-${t.year}${two(t.month)}${two(t.day)}-'
        '${two(t.hour)}${two(t.minute)}${two(t.second)}.txt';
    File(p).writeAsStringSync(isi);
    return (sent: false, savedTo: p);
  } catch (_) {
    return (sent: false, savedTo: null);
  }
}
