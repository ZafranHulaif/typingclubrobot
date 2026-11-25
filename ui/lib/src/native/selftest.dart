// Uji mandiri di CI Windows (TB_SELFTEST=<folder>): app menjalankan
// langkah2 UI sendiri; tiap langkah menulis <n>.ready lalu menunggu
// <n>.done dari skrip CI (yang memotret layar). Tanpa env = tidak aktif.
import 'dart:async';
import 'dart:io';

import '../state/store.dart';
import '../web/web_host.dart';

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
    // TB_SELFTEST_LEVEL=<n>: mulai dari level n (rentang n..n+4), spt
    // user memilih rentang; tanpa itu = mulai bebas dari halaman
    final lv = int.tryParse(Platform.environment['TB_SELFTEST_LEVEL'] ?? '') ?? 0;
    // TB_SELFTEST_STARS=<1-5>: target bintang mode bebas (uji pacing)
    final bintang = int.tryParse(Platform.environment['TB_SELFTEST_STARS'] ?? '') ?? 0;
    // TB_SELFTEST_END=<n>: akhir rentang (default level+4)
    final akhir = int.tryParse(Platform.environment['TB_SELFTEST_END'] ?? '') ?? 0;
    // TB_SELFTEST_HIDE=1: app disembunyikan selama bot jalan (uji latar)
    final sembunyi = Platform.environment['TB_SELFTEST_HIDE'] == '1';
    if (bintang > 0) await s.call('free.set', {'stars': bintang, 'silver': false});
    await s.call('bot.start', {
      'mode': 'free',
      if (lv > 0) 'range': {'mode': 'custom', 'start': lv, 'end': akhir > lv ? akhir : lv + 4},
    });
    await tunggu(4);
    await shot('mulai');
    // TB_SELFTEST_RUN=<detik>: biarkan bot jalan sungguhan (uji live
    // dgn akun tes), potret tiap 20 dtk
    final run = int.tryParse(Platform.environment['TB_SELFTEST_RUN'] ?? '') ?? 0;
    if (sembunyi) {
      await webHost.setAppHidden(true);
      File('$dir/sembunyi.txt').writeAsStringSync('${DateTime.now()} disembunyikan\n',
          mode: FileMode.append);
    }
    // tersembunyi: potret jarang (layar kosong), cukup tiap 2 menit
    final jeda = sembunyi ? 120 : 20;
    for (var t = 0; t < run; t += jeda) {
      await tunggu(jeda);
      await shot('jalan-${(t + jeda).toString().padLeft(4, '0')}s');
    }
    if (sembunyi) {
      await webHost.setAppHidden(false);
      File('$dir/sembunyi.txt').writeAsStringSync('${DateTime.now()} ditampilkan\n',
          mode: FileMode.append);
      await tunggu(3);
      await shot('tampil-lagi');
    }
    await s.call('bot.stop');
    await tunggu(2);
    await shot('stop');
    File('$dir/state.txt').writeAsStringSync('${s.snap}');
  } catch (e) {
    File('$dir/error.txt').writeAsStringSync('$e');
  }
  File('$dir/selesai').writeAsStringSync('ok');
}
