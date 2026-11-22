// macOS: pilih rilis GitHub ber-aset TypingBot-mac.zip + skrip pasang.
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:typingbot/src/native/native_backend.dart';
import 'package:typingbot/src/net/api.dart';

Map<String, dynamic> _rel(String tag, {bool mac = true, bool pre = false}) => {
      'tag_name': tag,
      'draft': false,
      'prerelease': pre,
      'body': 'catatan $tag',
      'assets': [
        {'name': 'TypingBot.exe', 'size': 1, 'browser_download_url': 'x'},
        if (mac)
          {
            'name': 'TypingBot-mac.zip',
            'size': 123,
            'digest': 'sha256:abc',
            'browser_download_url': 'https://github.com/r/$tag/TypingBot-mac.zip',
          },
      ],
    };

void main() {
  test('rilis tertinggi yang punya zip mac, prarilis dilewati', () {
    final r = Api.pickMacRelease([
      _rel('v4.1.0', mac: false),
      _rel('v4.2.0', pre: true),
      _rel('v4.0.2'),
      _rel('v4.0.10'),
    ]);
    expect(r!['version'], '4.0.10');
    expect(r['sha256'], 'abc');
    expect(r['size'], 123);
    expect(r['url'], contains('v4.0.10'));
  });

  test('tanpa zip mac = null', () {
    expect(Api.pickMacRelease([_rel('v4.0.0', mac: false)]), isNull);
    expect(Api.pickMacRelease('bukan list'), isNull);
  });

  test('skrip pasang: tunggu pid, simpan app lama, balikkan kalau gagal', () {
    final s = macInstallScript(
        app: "/Applications/Typing Bot's.app", zip: '/tmp/u.zip', pid: 4242);
    expect(s, startsWith('#!/bin/bash\n'));
    expect(s, contains("APP='/Applications/Typing Bot'\\''s.app'"));
    expect(s, contains('kill -0 4242'));
    expect(s, contains(r'for i in $(seq 1 100)'));
    expect(s, contains(r'T=$(mktemp -d)'));
    expect(s, contains(r'mv "$APP.lama" "$APP"'));
    expect(s, contains(r'open "$APP"'));
  });

  // CI mac: tulis skrip sungguhan utk uji tukar app (TB_TULIS_SKRIP=dir)
  final d = Platform.environment['TB_TULIS_SKRIP'];
  if (d != null && d.isNotEmpty) {
    test('tulis skrip pasang utk CI', () {
      File('$d/pasang.sh').writeAsStringSync(macInstallScript(
          app: '$d/Apps/TypingBot.app',
          zip: '$d/u.zip',
          pid: int.parse(Platform.environment['TB_PID'] ?? '1')));
    });
  }
}
