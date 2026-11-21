// Uji mandiri di CI Windows (TB_SELFTEST=<folder>): app menjalankan
// langkah2 UI sendiri; tiap langkah menulis <n>.ready lalu menunggu
// <n>.done dari skrip CI (yang memotret layar). Tanpa env = tidak aktif.
import 'dart:async';
import 'dart:io';

import '../state/store.dart';

String? selfTestDir() {
  final d = Platform.environment['TB_SELFTEST'];
  return d == null || d.isEmpty ? null : d;
}

Future<void> runSelfTest(AppStore s, String dir) async {
  Directory(dir).createSync(recursive: true);
  var n = 0;
  Future<void> shot(String name) async {
    n++;
    final id = '${n.toString().padLeft(2, '0')}-$name';
    File('$dir/$id.ready').writeAsStringSync('${DateTime.now()}');
    final done = File('$dir/$id.done');
    final sw = Stopwatch()..start();
    while (!done.existsSync() && sw.elapsed < const Duration(seconds: 30)) {
      await Future<void>.delayed(const Duration(milliseconds: 200));
    }
  }

  Future<void> tunggu(int detik) =>
      Future<void>.delayed(Duration(seconds: detik));

  try {
    await tunggu(25); // webview + halaman edclub + cek login
    await shot('buka');
    s.togglePlan();
    await tunggu(2);
    await shot('rencana-buka');
    s.togglePlan();
    await tunggu(2);
    await shot('rencana-tutup');
    await s.call('bot.start', {'mode': 'free'});
    await tunggu(4);
    await shot('mulai');
    await s.call('bot.stop');
    await tunggu(2);
    await shot('stop');
    File('$dir/state.txt').writeAsStringSync('${s.snap}');
  } catch (e) {
    File('$dir/error.txt').writeAsStringSync('$e');
  }
  File('$dir/selesai').writeAsStringSync('ok');
}
