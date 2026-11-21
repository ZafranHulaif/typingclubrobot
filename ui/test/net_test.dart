// N4: port net/ (spesifikasi = _test_net.py 3.5.x + server/API.md).
// Vektor uji: RFC 8032, tanda tangan dari node (crypto ed25519), dan kode
// mesin/kunci lama dihitung dgn kode python asli.
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:typingbot/src/net/api.dart';
import 'package:typingbot/src/net/ed25519.dart';
import 'package:typingbot/src/net/license.dart';
import 'package:typingbot/src/net/machine.dart';
import 'package:typingbot/src/net/report.dart';
import 'package:typingbot/src/net/updater.dart';

const _nodePub = '930a5b298ca910f4b559e87443df9c3d886b99a11065f18dd29c775be13046cb';
const _tok1 = {
  'mc': 'ABCDE-FGHIJ',
  'exp': 1790000000,
  'sig': 'a621b1f35dd160e2c8e705c0633018e7bfd4c74e8eb472d2a3da53919a6178fd'
      '7abd8ed3e224955b84484fa637db94e593353e85a3b6f556e04c8b80e148ad0e',
};
const _tok2 = {
  'mc': 'ZZZZZ-22222',
  'exp': 4102444800,
  'sig': 'eac068a225a00db683fbece806cb4390a588c36de08fa53ee801bfe8cd0fc4c3'
      'e8562f9f0279bcbdba6e453b445b56e1a302f1e72c2f063f39386f24ffb6bf0a',
};

void main() {
  group('ed25519', () {
    test('RFC 8032 test 1 & 2', () {
      expect(
          ed25519Verify(
              hexBytes('d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a'),
              const [],
              hexBytes('e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155'
                  '5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b')),
          isTrue);
      expect(
          ed25519Verify(
              hexBytes('3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c'),
              const [0x72],
              hexBytes('92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da'
                  '085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00')),
          isTrue);
    });

    test('tanda tangan node sah; pesan/sig diubah = ditolak', () {
      final pub = hexBytes(_nodePub);
      expect(ed25519Verify(pub, tokenMessage(_tok1), hexBytes(_tok1['sig'] as String)), isTrue);
      expect(ed25519Verify(pub, utf8.encode('v1|ABCDE-FGHIJ|1790000001'), hexBytes(_tok1['sig'] as String)),
          isFalse);
      final bad = hexBytes(_tok1['sig'] as String)..[5] ^= 1;
      expect(ed25519Verify(pub, tokenMessage(_tok1), bad), isFalse);
      expect(ed25519Verify(pub.sublist(1), tokenMessage(_tok1), bad), isFalse);
    });
  });

  group('token lisensi', () {
    test('verifyToken: sah, kedaluwarsa, bentuk rusak', () {
      expect(verifyToken(_tok1, now: 1700000000, pubHex: _nodePub), isTrue);
      expect(verifyToken(_tok1, now: 1790000001, pubHex: _nodePub), isFalse);
      expect(verifyToken(_tok2, pubHex: _nodePub), isTrue);
      expect(verifyToken({'mc': 'x'}, pubHex: _nodePub), isFalse);
      expect(verifyToken('teks', pubHex: _nodePub), isFalse);
      // kunci server asli tidak cocok dgn token uji
      expect(verifyToken(_tok2), isFalse);
    });

    test('sisa hari', () {
      expect(daysLeft(_tok1, now: 1790000000 - 3 * 86400 - 5), 3);
      expect(daysLeft(_tok1, now: 1800000000), 0);
      expect(daysLeft(null), 0);
    });

    test('license.dat: simpan/muat token, kunci lama HMAC', () {
      final d = Directory.systemTemp.createTempSync('tb_lic_');
      try {
        final p = '${d.path}/license.dat';
        saveToken(p, _tok2);
        expect(File(p).readAsStringSync(), startsWith('{"v":1,"token":{'));
        expect(loadToken(p), _tok2);
        // kunci teks lama
        const mc = 'ABCDE-FGHIJ';
        File(p).writeAsStringSync('${makeKey(mc, 's')}\n');
        expect(loadToken(p), isNull);
        expect(licenseValid(p, mc, secret: 's'), isTrue);
        expect(licenseValid(p, 'ZZZZZ-ZZZZZ', secret: 's'), isFalse);
        File(p).writeAsStringSync('');
        expect(licenseValid(p, mc, secret: 's'), isFalse);
      } finally {
        d.deleteSync(recursive: true);
      }
    });

    test('kunci HMAC & kode mesin sama persis dgn python', () {
      expect(makeKey('ABCDE-FGHIJ', 'DEV-ONLY-BUKAN-SECRET-ASLI'), 'PF2ZZ-U6ZLG-3HM52-CXQUG');
      expect(makeKey('abcde fghij', 's3cret'), 'TOJNY-7DOEY-IOAYX-CMXXH');
      expect(norm('ab-c1d8 e'), 'ABCDE');
      expect(machineCodeFrom('mac=001a2b3c4d5e|host=DESKTOP-ACER|vol=2864434397'), 'V7ESI-TTQC4');
      expect(machineCodeFrom('host=LAPTOP'), 'DFQPL-RTCOL');
    });

    test('sidik jari mesin: format & MAC acak dilewati', () {
      expect(nodeFromGuid(List.generate(16, (i) => i)), 0x0a0b0c0d0e0f);
      expect(machineDataFrom(node: 0x001a2b3c4d5e, host: 'desktop-acer', vol: 2864434397),
          'mac=001a2b3c4d5e|host=DESKTOP-ACER|vol=2864434397');
      // bit multicast = MAC acak -> tidak dipakai
      expect(machineDataFrom(node: 0x011a2b3c4d5e, host: 'pc'), 'host=PC');
      expect(machineCode(), matches(RegExp(r'^[A-Z2-7]{5}-[A-Z2-7]{5}$')));
    });

    test('parameter unduh = base64 JSON token, di-URL-encode', () {
      final p = downloadParam({'mc': 'A', 'exp': 1, 'sig': 'ff'});
      expect(jsonDecode(utf8.decode(base64.decode(Uri.decodeComponent(p)))),
          {'mc': 'A', 'exp': 1, 'sig': 'ff'});
    });
  });

  group('updater', () {
    test('parse_version buang -devN, bandingkan panjang beda', () {
      expect(parseVersion('3.5.5-dev5'), [3, 5, 5]);
      expect(parseVersion('4.0.0-dev1'), [4, 0, 0]);
      expect(parseVersion('x'), [0]);
      expect(isNewer('3.5.5', '3.5.5-dev21'), isFalse);
      expect(isNewer('3.5.6', '3.5.5-dev21'), isTrue);
      expect(isNewer('3.6', '3.5.9'), isTrue);
      expect(isNewer('3.5', '3.5.0'), isFalse);
      expect(isNewer('3.5.5', '4.0.0-dev1'), isFalse);
    });
  });

  group('api (server lokal)', () {
    late HttpServer srv;
    late Api api;
    final seen = <HttpRequest>[];
    final bodies = <String>[];

    setUp(() async {
      seen.clear();
      bodies.clear();
      srv = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      srv.listen((req) async {
        seen.add(req);
        bodies.add(await utf8.decoder.bind(req).join());
        final path = req.uri.path;
        req.response.headers.contentType = ContentType.json;
        if (path == '/api/latest') {
          req.response.write(jsonEncode({'version': '4.1.0', 'notes': 'n', 'size': 3}));
        } else if (path == '/api/license/status') {
          req.response.write(jsonEncode({'status': 'approved', 'token': _tok2, 'mc': req.uri.queryParameters['mc']}));
        } else if (path == '/api/license/request') {
          req.response.write(jsonEncode({'status': 'pending'}));
        } else if (path == '/api/lapor') {
          req.response.statusCode = 429;
          req.response.write('{"error":"rate_limited"}');
        } else if (path == '/bin') {
          req.response.headers.contentType = ContentType.binary;
          req.response.add([1, 2, 3]);
        } else {
          req.response.statusCode = 404;
        }
        await req.response.close();
      });
      api = Api(baseUrl: 'http://127.0.0.1:${srv.port}', version: '4.0.0-dev1');
    });
    tearDown(() => srv.close(force: true));

    test('UA mirip browser, kontrak status/request tetap', () async {
      final st = await fetchStatus(api, 'ABCDE-FGHIJ');
      expect(st['status'], 'approved');
      expect(st['mc'], 'ABCDE-FGHIJ');
      // python menulis %2D; Uri Dart menormalkannya ke '-' (server
      // men-decode keduanya jadi nilai yang sama)
      expect(seen.single.uri.queryParameters['mc'], 'ABCDE-FGHIJ');
      expect(seen.single.headers.value('user-agent'), startsWith('Mozilla/5.0'));
      expect(seen.single.headers.value('user-agent'), contains('TypingBot/4.0.0-dev1'));
      final r = await requestApproval(api, 'ABCDE-FGHIJ', 'Ucok', '4.0.0-dev1');
      expect(r['status'], 'pending');
      expect(jsonDecode(bodies.last), {'mc': 'ABCDE-FGHIJ', 'nickname': 'Ucok', 'app_version': '4.0.0-dev1'});
    });

    test('cek pembaruan hanya kalau lebih baru', () async {
      expect((await checkUpdate(api, '4.0.0-dev1'))?['version'], '4.1.0');
      expect(await checkUpdate(api, '4.1.0'), isNull);
    });

    test('server mati = Unreachable; checkUpdate jadi null', () async {
      final dead = Api(baseUrl: 'http://127.0.0.1:1', version: 'x');
      expect(() => dead.json('GET', '/api/latest'), throwsA(isA<Unreachable>()));
      expect(await checkUpdate(dead, '1.0'), isNull);
    });

    test('unduh: sha256 & rename', () async {
      final d = Directory.systemTemp.createTempSync('tb_dl_');
      try {
        final h = await api.download('/bin', '${d.path}/x.bin');
        expect(File('${d.path}/x.bin').readAsBytesSync(), [1, 2, 3]);
        expect(h, '039058c6f2c0cb492c533b0a4d14ef77cc0f78abccced5287d84a1a2011cfb81');
        expect(File('${d.path}/x.bin.part').existsSync(), isFalse);
      } finally {
        d.deleteSync(recursive: true);
      }
    });

    test('lapor: ditolak server -> simpan ke Desktop', () async {
      final d = Directory.systemTemp.createTempSync('tb_home_');
      // HOME/USERPROFILE tak bisa diubah di proses tes; cukup cek isi laporan
      final isi = buildReport(
          version: '4.0.0-dev1',
          account: 'budi',
          category: 'bot',
          text: 'macet di level 5',
          logTail: ['a', 'b'],
          at: DateTime(2026, 11, 22, 3, 4, 5));
      expect(isi, contains('versi: 4.0.0-dev1'));
      expect(isi, contains('waktu: 2026-11-22 03:04:05'));
      expect(isi, contains('=== CERITA USER ===\nmacet di level 5'));
      expect(isi, endsWith('=== LOG (400 baris terakhir) ===\na\nb\n'));
      final r = await sendReport(api, version: 'v', account: 'a', isi: isi);
      expect(r.sent, isFalse);
      expect(jsonDecode(bodies.last)['akun'], 'a');
      if (r.savedTo != null) File(r.savedTo!).deleteSync();
      d.deleteSync(recursive: true);
    });
  });
}
