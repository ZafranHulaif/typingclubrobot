// Render logo keycap (digambar kode) jadi PNG per ukuran ikon Windows.
// Jalankan: flutter test tool/render_icon_test.dart  -> build/icon/*.png
// lalu tool/make_ico.py merakit windows/runner/resources/app_icon.ico.
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:typingbot/src/theme/theme.dart';
import 'package:typingbot/src/ui/widgets/logo.dart';

void main() {
  for (final s in const [16, 20, 24, 32, 40, 48, 64, 128, 256]) {
    testWidgets('ikon $s', (t) async {
      t.view.devicePixelRatio = 1;
      t.view.physicalSize = Size(s.toDouble(), s.toDouble());
      final key = GlobalKey();
      await t.pumpWidget(MaterialApp(
        theme: buildTheme(),
        debugShowCheckedModeBanner: false,
        home: ColoredBox(
          color: const Color(0x00000000),
          child: Center(
            child: RepaintBoundary(
              key: key,
              child: KeycapLogo(size: s.toDouble()),
            ),
          ),
        ),
      ));
      await t.pump();
      final b = key.currentContext!.findRenderObject()! as RenderRepaintBoundary;
      await t.runAsync(() async {
        final img = await b.toImage(pixelRatio: 1);
        final data = await img.toByteData(format: ui.ImageByteFormat.png);
        Directory('build/icon').createSync(recursive: true);
        File('build/icon/$s.png').writeAsBytesSync(data!.buffer.asUint8List());
      });
      t.view.reset();
    });
  }
}
