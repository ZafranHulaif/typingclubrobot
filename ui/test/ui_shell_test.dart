// Asap UI: kerangka + panel Rencana (menimpa halaman lewat lubang) +
// editor draf. Backend native asli, host C++ dipalsukan.
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:typingbot/main.dart';
import 'package:typingbot/src/native/accounts.dart';
import 'package:typingbot/src/native/native_backend.dart';
import 'package:typingbot/src/state/store.dart';
import 'package:typingbot/src/ui/widgets/web_layer.dart';
import 'package:typingbot/src/web/web_host.dart';

const _ch = MethodChannel('typingbot/web_host');

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('Rencana: panel menimpa halaman, Tambah = draf, Buat = simpan',
      (t) async {
    final tmp = Directory.systemTemp.createTempSync('tb_ui_');
    final calls = <MethodCall>[];
    t.binding.defaultBinaryMessenger.setMockMethodCallHandler(_ch, (c) async {
      calls.add(c);
      switch (c.method) {
        case 'version':
          return '131.0';
        case 'create':
          return (c.arguments as Map)['id'];
        case 'eval':
          return '"in"';
      }
      return null;
    });
    await t.binding.setSurfaceSize(const Size(1400, 900));
    final be = NativeBackend(
        version: 't',
        host: WebHost(),
        accounts: AccountStore(tmp.path),
        checkLicense: false);
    WebLayer.instance.enabled = true;
    final store = AppStore(be, embedded: true);
    await t.runAsync(be.connect);
    await t.pumpWidget(TypingBotApp(store: store));
    await _settle(t);

    // slot halaman dilaporkan; belum ada lubang
    final rect = calls.lastWhere((c) => c.method == 'setRect').arguments as Map;
    expect(rect['x'], 39); // dpr tes = 3, di dalam garis tepi 1px
    expect(rect['w'], (1400 - 26) * 3);

    await t.tap(find.text('Rencana'));
    await _settle(t);
    // panel terbuka: halaman TIDAK bergeser, panel jadi lubang
    final rect2 = calls.lastWhere((c) => c.method == 'setRect').arguments as Map;
    expect(rect2['x'], 39);
    final holes = calls.lastWhere((c) => c.method == 'setHoles').arguments as Map;
    expect((holes['rects'] as List).length, 4);
    expect((holes['rects'] as List)[2], 296 * 3);

    await t.tap(find.text('Tambah'));
    await _settle(t);
    expect(find.text('Bagian baru'), findsOneWidget);
    expect(store.segments, isEmpty); // draf belum tersimpan
    await t.tap(find.text('Buat'));
    await t.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
    await _settle(t);
    expect(store.segments.single.to, store.segments.single.from + 9);
    expect(find.text('Bagian baru'), findsNothing);

    // tutup panel: lubang hilang
    await t.tap(find.text('Rencana').first);
    await _settle(t);
    final h2 = calls.lastWhere((c) => c.method == 'setHoles').arguments as Map;
    expect(h2['rects'], isEmpty);

    be.close();
    WebLayer.instance.enabled = false;
    tmp.deleteSync(recursive: true);
  });
}

// ada animasi berulang (logo berkedip): pump bertahap, bukan pumpAndSettle
Future<void> _settle(WidgetTester t) async {
  for (var i = 0; i < 10; i++) {
    await t.pump(const Duration(milliseconds: 100));
  }
}
