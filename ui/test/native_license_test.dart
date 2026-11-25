// N4: alur lisensi/update/lapor di backend native (port engine_backend.py)
// dgn worker palsu lokal. Kontrak = server/API.md.
import 'dart:convert';
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:typingbot/src/bridge/bridge.dart';
import 'package:typingbot/src/native/accounts.dart';
import 'package:typingbot/src/native/native_backend.dart';
import 'package:typingbot/src/net/api.dart';
import 'package:typingbot/src/net/license.dart' as lic;
import 'package:typingbot/src/web/web_host.dart';

const _nodePub = '930a5b298ca910f4b559e87443df9c3d886b99a11065f18dd29c775be13046cb';
const _tokOk = {
  'mc': 'ZZZZZ-22222',
  'exp': 4102444800,
  'sig': 'eac068a225a00db683fbece806cb4390a588c36de08fa53ee801bfe8cd0fc4c3'
      'e8562f9f0279bcbdba6e453b445b56e1a302f1e72c2f063f39386f24ffb6bf0a',
};

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late Directory tmp;
  late HttpServer srv;
  late int port;
  late Map<String, dynamic> last;
  final hits = <String>[];
  String status = 'unknown';
  String latest = '3.5.5';
  bool reqApprove = false; // /api/license/request langsung approved
  bool reqBroken = false; // /api/license/request dijawab halaman galat (bukan JSON)

  setUpAll(() {
    lic.debugPublicKeyHex = _nodePub;
    // binding tes Flutter memalsukan semua HTTP (selalu 400): pakai asli
    HttpOverrides.global = null;
  });
  tearDownAll(() => lic.debugPublicKeyHex = null);

  setUp(() async {
    tmp = Directory.systemTemp.createTempSync('tb_lic_');
    hits.clear();
    status = 'unknown';
    latest = '3.5.5';
    reqApprove = false;
    reqBroken = false;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(const MethodChannel('typingbot/web_host'), (c) async {
      if (c.method == 'version') return ''; // tanpa webview: cukup uji jaringan
      return null;
    });
    srv = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    port = srv.port;
    srv.listen((req) async {
      final body = await utf8.decoder.bind(req).join();
      hits.add('${req.method} ${req.uri.path}?${req.uri.query} $body');
      req.response.headers.contentType = ContentType.json;
      switch (req.uri.path) {
        case '/api/license/status':
          req.response.write(jsonEncode(status == 'approved'
              ? {'status': 'approved', 'token': _tokOk}
              : {'status': status}));
        case '/api/license/request' when reqBroken:
          req.response.statusCode = 403;
          req.response.headers.contentType = ContentType.html;
          req.response.write('<html>Access denied</html>');
        case '/api/license/request':
          req.response.write(jsonEncode(reqApprove
              ? {'status': 'approved', 'token': {..._tokOk, 'mc': 'a854363933'}}
              : {'status': 'pending'}));
        case '/api/latest':
          req.response.write(jsonEncode({
            'version': latest,
            'notes': 'catatan',
            'size': 5,
            'sha256': sha256.convert(utf8.encode('BUNDL')).toString(),
          }));
        case '/api/download':
          req.response.headers.contentType = ContentType.binary;
          req.response.write('BUNDL');
        case '/api/lapor':
          req.response.write('{"ok": true}');
        default:
          req.response.statusCode = 404;
      }
      await req.response.close();
    });
    last = {};
  });

  tearDown(() async {
    await srv.close(force: true);
    tmp.deleteSync(recursive: true);
  });

  Future<NativeBackend> boot({String mc = 'ZZZZZ-22222', String version = '4.0.0-dev2'}) async {
    final be = NativeBackend(
      version: version,
      host: WebHost(),
      accounts: AccountStore(tmp.path),
      api: Api(baseUrl: 'http://127.0.0.1:$port', version: version),
      machineCode: () => mc,
    );
    be.events.listen((e) {
      if (e.name == 'snapshot' || e.name == 'state') {
        last.addAll(Map<String, dynamic>.from(e.data as Map));
      }
    });
    await be.connect();
    return be;
  }

  Map licState() => last['license'] as Map;

  Future<void> waitFor(bool Function() ok) async {
    final sw = Stopwatch()..start();
    while (!ok()) {
      if (sw.elapsedMilliseconds > 4000) fail('tidak tercapai: $last / $hits');
      await Future<void>.delayed(const Duration(milliseconds: 10));
    }
  }

  test('lisensi mesin: token diperbarui di latar, UI tidak dikunci saat buka', () async {
    lic.saveToken('${tmp.path}/license.dat', _tokOk);
    status = 'approved';
    final be = await boot();
    await waitFor(() => hits.any((h) => h.startsWith('GET /api/license/status?mc=ZZZZZ-22222')));
    expect(licState()['state'], 'ok');
    be.close();
  });

  test('mesin baru tanpa lisensi: tetap bisa buka app (lisensi diminta saat Mulai)', () async {
    final be = await boot(mc: 'NEWWW-MACHN');
    await waitFor(() => hits.isNotEmpty);
    expect(licState()['state'], 'ok');
    expect(hits.where((h) => h.contains('/api/license/request')), isEmpty);
    be.close();
  });

  // ---------------------------------------------- lisensi per akun
  Future<NativeBackend> bootWeb({String mc = 'ZZZZZ-22222'}) async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(const MethodChannel('typingbot/web_host'), (c) async {
      switch (c.method) {
        case 'version':
          return '131.0';
        case 'create':
          return (c.arguments as Map)['id'];
        case 'cdp':
          // user_id edclub dari refresh-tokens
          if ((c.arguments as Map)['method'] == 'Runtime.evaluate') {
            return '{"result": {"type": "object", "value": {"id": 854363933, "name": "Zafran Tes"}}}';
          }
          return '{}';
        case 'eval':
          return '"in"';
      }
      return null;
    });
    return boot(mc: mc);
  }

  Future<void> mulaiRencana(NativeBackend be) async {
    await be.request('plan.set', {
      'segments': [
        {'from': 1, 'to': 5, 'stars': 5, 'silver': true}
      ]
    });
    await be.request('bot.start', {'mode': 'plan'});
  }

  test('akun baru tanpa nama panggilan: Mulai -> minta nama -> pending utk id akun', () async {
    final be = await bootWeb(mc: 'NEWWW-MACHN');
    await mulaiRencana(be);
    await waitFor(() => licState()['state'] == 'need');
    expect(() => be.request('license.request', {'nickname': 'a'}), throwsA(isA<RpcException>()));
    await be.request('license.request', {'nickname': 'Ucok'});
    await waitFor(() => licState()['state'] == 'pending');
    final req = hits.lastWhere((h) => h.contains('/api/license/request'));
    expect(req, contains('"mc":"a854363933"'));
    expect(req, contains('"nickname":"Ucok"'));
    expect(req, contains('"account_name":"Zafran Tes"'));
    expect(jsonDecode(File('${tmp.path}/typingbot_settings.json').readAsStringSync())['nickname'], 'Ucok');
    be.close();
  });

  test('permintaan izin dijawab halaman galat: BUKAN "terkirim", galat + log', () async {
    reqBroken = true;
    final be = await bootWeb(mc: 'NEWWW-MACHN');
    await mulaiRencana(be);
    await waitFor(() => licState()['state'] == 'need');
    await be.request('license.request', {'nickname': 'Ucok'});
    await waitFor(() => '${(last['bot'] as Map?)?['error'] ?? ''}'.contains('HTTP 403'));
    expect(licState()['state'], 'need');
    expect(File('${tmp.path}/bot.log').readAsStringSync(),
        contains('[LISENSI] permintaan akun'));
    be.close();
  });

  test('lisensi mesin 3.5.x ikut dikirim (jatah akun pertama); disetujui -> token akun tersimpan', () async {
    lic.saveToken('${tmp.path}/license.dat', _tokOk);
    status = 'approved';
    reqApprove = true;
    final be = await bootWeb();
    await waitFor(() => hits.any((h) => h.contains('status?mc=ZZZZZ-22222')));
    await mulaiRencana(be);
    await waitFor(() => hits.any((h) => h.contains('/api/license/request')));
    final req = hits.lastWhere((h) => h.contains('/api/license/request'));
    expect(req, contains('"mc":"a854363933"'));
    expect(req, contains('"mtok"'));
    await waitFor(() => File('${tmp.path}/lisensi-akun.json').existsSync());
    expect(jsonDecode(File('${tmp.path}/lisensi-akun.json').readAsStringSync()), contains('a854363933'));
    be.close();
  });

  test('kunci HMAC lama -> ok + minta token di latar', () async {
    File('${tmp.path}/license.dat').writeAsStringSync('${lic.makeKey('OLDKY-MACHN')}\n');
    final be = await boot(mc: 'OLDKY-MACHN');
    await waitFor(() => licState()['state'] == 'ok' && hits.any((h) => h.contains('/api/license/request')));
    expect(hits.firstWhere((h) => h.contains('/request')), contains('pemilik-lama'));
    be.close();
  });

  test('update: lebih baru + token sah -> ditawarkan; lapor terkirim', () async {
    lic.saveToken('${tmp.path}/license.dat', _tokOk);
    status = 'approved';
    latest = '4.1.0';
    final be = await boot();
    await waitFor(() => (last['update'] as Map?)?['available'] == true);
    expect((last['update'] as Map)['version'], '4.1.0');
    // unduh lewat server (token) -> hash cocok -> siap dipasang
    await be.request('update.download');
    await waitFor(() => (last['update'] as Map?)?['phase'] == 'ready');
    expect(hits.any((h) => h.startsWith('GET /api/download?t=')), true);
    expect(File('${tmp.path}/update/TypingBot-4.1.0.exe').readAsStringSync(), 'BUNDL');
    final r = await be.request('report.send', {'category': 'bot', 'text': 'macet'});
    expect(r, {'sent': true});
    final lapor = jsonDecode(hits.last.substring(hits.last.indexOf('{')));
    expect(lapor['versi'], '4.0.0-dev2');
    expect('${lapor['isi']}', contains('=== CERITA USER ===\nmacet'));
    be.close();
  });

  test('update: rilis baru saat app terbuka muncul lewat cek berkala', () async {
    lic.saveToken('${tmp.path}/license.dat', _tokOk);
    status = 'approved';
    latest = '4.0.0-dev2'; // sama = belum ada
    final be = await boot();
    await waitFor(() => hits.any((h) => h.startsWith('GET /api/latest')));
    await Future<void>.delayed(const Duration(milliseconds: 50));
    expect((last['update'] as Map?)?['available'], isNot(true));
    latest = '4.1.0'; // dirilis saat app masih terbuka
    await be.updateTickForTest();
    await waitFor(() => (last['update'] as Map?)?['available'] == true);
    expect((last['update'] as Map)['version'], '4.1.0');
    // cek manual dari menu = jawab status yang sama
    final r = await be.request('update.check');
    expect((r as Map)['available'], true);
    be.close();
  });
}
