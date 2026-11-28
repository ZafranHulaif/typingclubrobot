// Asap UI: kerangka + panel Rencana (menimpa halaman lewat lubang) +
// editor draf. Backend native asli, host C++ dipalsukan.
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart' show TextField;
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
    expect(find.text('Peta level'), findsOneWidget);
    await t.tap(find.text('Tambahkan'));
    await t.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
    await _settle(t);
    expect(store.segments.single.to, store.segments.single.from + 9);
    expect(find.text('Bagian baru'), findsNothing);

    // bagian tidak tersambung: celah jadi kotak Tambah, bagian setelahnya abu-abu
    await t.runAsync(() => store.savePlan([Segment(51, 200, 5), Segment(401, 600, 4)]));
    await _settle(t);
    expect(find.text('201-400'), findsOneWidget);
    expect(find.text('tidak tersambung'), findsOneWidget);
    await t.tap(find.text('201-400'));
    await _settle(t);
    expect(find.text('Bagian baru'), findsOneWidget);
    await t.tap(find.text('Tambahkan'));
    await t.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
    await _settle(t);
    expect([for (final g in store.segments) '${g.from}-${g.to}'],
        ['51-200', '201-400', '401-600']);
    expect(find.text('tidak tersambung'), findsNothing);

    // lembar editor: bagian 51-200 jadi pola 2,4,4,3,4 (diketik)
    await t.tap(find.text('51–200'));
    await _settle(t);
    expect(find.text('Bagian 51–200'), findsOneWidget);
    expect(find.text('Belum disimpan'), findsNothing);
    await t.tap(find.text('Pola'));
    await _settle(t);
    await t.enterText(find.byType(TextField).last, '2,4,4,3,4');
    await _settle(t);
    expect(find.text('Belum disimpan'), findsOneWidget);
    // peta level mulai dari level awal bagian
    expect(find.text('51'), findsWidgets);
    expect(find.textContaining('level lagi'), findsOneWidget);
    await t.tap(find.text('Simpan perubahan'));
    await t.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
    await _settle(t);
    expect(store.segments.first.rule.type, 'pattern');
    expect(store.segments.first.rule.pattern, [2, 4, 4, 3, 4]);
    expect(find.text('Bagian 51–200'), findsNothing);

    // aturan khusus game: balon selalu 3 bintang
    await t.tap(find.text('Aturan game'));
    await _settle(t);
    await t.tap(find.text('Tetap').first);
    await _settle(t);
    await t.tap(find.text('Simpan'));
    await t.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
    await _settle(t);
    expect(store.gameRule('balloon').type, 'fixed');
    expect(store.gameRule('monster').follow, isTrue);
    expect(store.anyGameRule, isTrue);

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
