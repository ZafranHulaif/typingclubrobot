// Tes backend native + buku akun tanpa Windows: sisi C++ (web_host.cpp)
// dipalsukan lewat mock MethodChannel.
import 'dart:convert';
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:typingbot/src/bridge/bridge.dart';
import 'package:typingbot/src/native/accounts.dart';
import 'package:typingbot/src/native/native_backend.dart';
import 'package:typingbot/src/web/web_host.dart';

const _chName = 'typingbot/web_host';

/// Host C++ palsu: catat panggilan, jawab seperlunya.
class FakeNative {
  FakeNative({this.version = '131.0.0.0'}) {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(const MethodChannel(_chName), _handle);
  }

  final String version;
  final calls = <MethodCall>[];
  final cdpCalls = <String>[];
  final cdpParams = <String>[];
  String? rt; // kuki rt di jar palsu
  String displayName = '';

  Future<Object?> _handle(MethodCall c) async {
    calls.add(c);
    switch (c.method) {
      case 'version':
        return version;
      case 'create':
        return (c.arguments as Map)['id'];
      case 'cdp':
        final m = '${(c.arguments as Map)['method']}';
        cdpCalls.add(m);
        cdpParams.add('${(c.arguments as Map)['params']}');
        if (m == 'Network.getCookies' && rt != null) {
          return '{"cookies": [{"name": "rt", "value": "$rt"}]}';
        }
        return '{}';
      case 'eval':
        // cek login saat webview dibuka: anggap sudah login
        final js = '${(c.arguments as Map)['js']}';
        if (js.contains('tb:login')) return '"in"';
        if (js.contains('profile-name')) return jsonEncode(displayName);
        return '42';
      case 'info':
        return {'url': 'https://www.edclub.com/', 'title': 't'};
    }
    return null;
  }

  Iterable<MethodCall> named(String m) => calls.where((c) => c.method == m);

  /// Kirim event dari "C++" ke Dart.
  Future<void> emit(int id, String type, Map<String, Object?> data) async {
    final msg = const StandardMethodCodec()
        .encodeMethodCall(MethodCall('event', {'id': id, 'type': type, ...data}));
    await TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .handlePlatformMessage(_chName, msg, (_) {});
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late Directory tmp;

  setUp(() => tmp = Directory.systemTemp.createTempSync('tb_native_'));
  tearDown(() => tmp.deleteSync(recursive: true));

  group('AccountStore (format 3.5.x)', () {
    test('nama folder aman sama dgn python', () {
      expect(AccountStore.safeName('Zafran: H?'), 'Zafran_ H_');
      expect(AccountStore.safeName('  '), 'akun');
      expect(AccountStore.safeName('a/b\\c'), 'a_b_c');
    });

    test('folder: tanpa akun aktif = wv2profile', () {
      final a = AccountStore(tmp.path);
      expect(a.active(), isNull);
      expect(a.folderFor(null), endsWith('wv2profile'));
      expect(a.folderFor('Budi'),
          endsWith('profil-akun${Platform.pathSeparator}Budi'));
    });

    test('daftar = buku alamat + folder jar, aktif tersimpan', () {
      final a = AccountStore(tmp.path);
      Directory('${tmp.path}/akun').createSync();
      File('${tmp.path}/akun/akun-Zafran H.json')
          .writeAsStringSync(jsonEncode({'nama': 'Zafran  H', 'cookies': []}));
      Directory('${tmp.path}/profil-akun/budi').createSync(recursive: true);
      Directory('${tmp.path}/profil-akun/Zafran H').createSync(recursive: true);
      a.setActive('budi');
      expect(a.active(), 'budi');
      expect(a.list(), ['budi', 'Zafran H']);
      expect(jsonDecode(File('${tmp.path}/akun/aktif.json').readAsStringSync()),
          {'nama': 'budi'});
    });

    test('nama akun baru tidak bentrok', () {
      final a = AccountStore(tmp.path);
      expect(a.newName(), 'Akun baru');
      Directory('${tmp.path}/profil-akun/Akun baru').createSync(recursive: true);
      expect(a.newName(), 'Akun baru 2');
    });
  });

  group('NativeBackend', () {
    late FakeNative fake;
    late NativeBackend be;

    setUp(() {
      fake = FakeNative();
      be = NativeBackend(
        version: 'test',
      checkLicense: false,
        host: WebHost(),
        accounts: AccountStore(tmp.path),
        revealTimeout: const Duration(seconds: 5),
      );
    });

    Map<String, dynamic> cover() {
      // state terakhir 'cover' dari event
      return Map<String, dynamic>.from(_last['cover'] as Map);
    }

    test('boot: webview dgn init script, cover turun setelah halaman siap',
        () async {
      _listen(be);
      await be.connect();
      await _flush();
      final create = fake.named('create').single.arguments as Map;
      expect(create['folder'], endsWith('wv2profile'));
      // dibuat kosong, kuki sesi dipasang, baru navigasi
      expect(create['url'], '');
      expect(fake.named('navigate').first.arguments['url'], homeUrl);
      expect((create['scripts'] as List).length, initScripts.length);
      expect(create['scripts'][0], contains('window.open'));
      expect(cover()['visible'], true);
      expect(fake.named('setVisible').every((c) => c.arguments['on'] == false),
          true);

      await fake.emit(1, 'nav', {'phase': 'done', 'ok': true, 'url': homeUrl});
      await _flush();
      expect(cover()['visible'], false);
      expect(fake.named('setVisible').last.arguments['on'], true);
    });

    test('target bintang selain perak mengunci kecepatan', () async {
      _listen(be);
      await be.connect();
      await _flush();
      // default perak: kecepatan bebas
      expect((_last['speed'] as Map)['auto'], 0);
      await be.request('free.set', {'stars': 4});
      await _flush();
      expect((_last['speed'] as Map)['auto'], 4);
      await be.request('free.set', {'stars': 5, 'silver': true});
      await _flush();
      expect((_last['speed'] as Map)['auto'], 0);
    });

    test('tanpa runtime WebView2: pesan, tak ada webview', () async {
      fake = FakeNative(version: '');
      _listen(be);
      await be.connect();
      await _flush();
      expect(fake.named('create'), isEmpty);
      expect('${cover()['text']}', contains('WebView2'));
    });

    test('ganti akun: jar baru, lama dibuang, aktif.json ikut', () async {
      _listen(be);
      await be.connect();
      await _flush();
      await be.request('acct.switch', {'name': 'budi'});
      await _flush();
      final creates = fake.named('create').toList();
      expect(creates.length, 2);
      expect((creates[1].arguments as Map)['folder'],
          endsWith('profil-akun${Platform.pathSeparator}budi'));
      expect(fake.named('dispose').single.arguments['id'], 1);
      expect(AccountStore(tmp.path).active(), 'budi');
      expect((_last['account'] as Map)['active'], 'budi');
      // event webview lama diabaikan, yang baru menurunkan cover
      await fake.emit(1, 'nav', {'phase': 'done', 'url': homeUrl});
      await _flush();
      expect(cover()['visible'], true);
      await fake.emit(2, 'nav', {'phase': 'done', 'url': homeUrl});
      await _flush();
      expect(cover()['visible'], false);
    });

    test('tambah akun: buka /signin di jar baru', () async {
      _listen(be);
      await be.connect();
      await _flush();
      await be.request('acct.add');
      await _flush();
      final c = fake.named('create').last.arguments as Map;
      expect(fake.named('navigate').last.arguments['url'], signinUrl);
      expect(c['folder'], endsWith('Akun baru'));
      expect((_last['account'] as Map)['active'], 'Akun baru');
      expect((_last['account'] as Map)['pending'], true);
    });

    test('sesi edclub (kuki rt): disimpan saat login, dipasang lagi saat buka', () async {
      _listen(be);
      await be.connect();
      await _flush();
      // login: halaman lesson + penanda 'in', jar punya rt
      fake.rt = 'RT-1';
      await fake.emit(1, 'nav', {'phase': 'done', 'url': homeUrl});
      await Future<void>.delayed(const Duration(milliseconds: 3300));
      await _flush();
      final f = File('${AccountStore(tmp.path).folderFor(null)}/tb_sesi.json');
      expect(jsonDecode(f.readAsStringSync())['rt'], 'RT-1');
      be.close();
      // buka lagi (jar kosong, kuki sesi hilang): rt dipasang SEBELUM navigasi
      fake.rt = null;
      fake.calls.clear();
      final b2 = NativeBackend(
          version: 't', host: WebHost(), accounts: AccountStore(tmp.path),
          checkLicense: false, revealTimeout: const Duration(seconds: 5));
      await b2.connect();
      await _flush();
      final i = fake.cdpCalls.lastIndexOf('Network.setCookie');
      expect(i, greaterThanOrEqualTo(0));
      expect(fake.cdpParams[i], contains('RT-1'));
      final names = fake.calls.map((c) => c.method).toList();
      expect(names.lastIndexOf('cdp'), lessThan(names.indexOf('navigate')));
      b2.close();
    });

    test('hapus akun aktif: pindah ke akun lain, folder & nama hilang', () async {
      _listen(be);
      await be.connect();
      await _flush();
      await be.request('acct.switch', {'name': 'budi'});
      await _flush();
      await be.request('acct.switch', {'name': 'sari'});
      await _flush();
      final st = AccountStore(tmp.path);
      Directory(st.folderFor('budi')).createSync(recursive: true);
      Directory(st.folderFor('sari')).createSync(recursive: true);
      st.setLabel('sari', 'Sari W');
      await be.request('acct.delete', {'name': 'sari'});
      await _flush();
      expect(st.active(), 'budi');
      expect(Directory(st.folderFor('sari')).existsSync(), false);
      expect(st.labels().containsKey('sari'), false);
      final names = [for (final a in (_last['account'] as Map)['list'] as List) a['name']];
      expect(names, ['budi']);
    });

    test('nama akun ikut nama edclub begitu login', () async {
      fake.displayName = 'Zafran Tes';
      _listen(be);
      await be.connect();
      await _flush();
      await be.request('acct.switch', {'name': 'Akun baru 2'});
      await _flush();
      final id = (fake.named('create').last.arguments as Map)['id'] as int;
      await fake.emit(id, 'nav', {'phase': 'done', 'url': homeUrl});
      await Future<void>.delayed(const Duration(milliseconds: 1700));
      await _flush();
      expect((_last['account'] as Map)['active_label'], 'Zafran Tes');
      expect(((_last['account'] as Map)['list'] as List).single['label'], 'Zafran Tes');
    });

    test('akun baru ditinggal sebelum login = dibuang; login = tersimpan', () async {
      _listen(be);
      await be.connect();
      await _flush();
      await be.request('acct.switch', {'name': 'budi'});
      await _flush();
      await be.request('acct.add');
      await _flush();
      Directory(AccountStore(tmp.path).folderFor('Akun baru')).createSync(recursive: true);
      // balik ke budi tanpa login -> "Akun baru" hilang dari daftar & disk
      await be.request('acct.switch', {'name': 'budi'});
      await _flush();
      final names = [for (final a in (_last['account'] as Map)['list'] as List) a['name']];
      expect(names, isNot(contains('Akun baru')));
      expect(Directory(AccountStore(tmp.path).folderFor('Akun baru')).existsSync(), false);
      // tambah lagi: nama tetap "Akun baru" (bukan "Akun baru 2")
      await be.request('acct.add');
      await _flush();
      expect((_last['account'] as Map)['active'], 'Akun baru');
      // login berhasil (halaman lesson, penanda 'in') -> resmi tersimpan
      final id = (fake.named('create').last.arguments as Map)['id'] as int;
      await fake.emit(id, 'nav', {'phase': 'done', 'url': homeUrl});
      await Future<void>.delayed(const Duration(milliseconds: 1700));
      await _flush();
      expect((_last['account'] as Map)['pending'], false);
      expect(AccountStore(tmp.path).pending(), isEmpty);
    });

    test('popup Flutter di atas halaman = webview disembunyikan', () async {
      _listen(be);
      await be.connect();
      await _flush();
      await fake.emit(1, 'nav', {'phase': 'done', 'url': homeUrl});
      await _flush();
      await be.request('web.visible', {'on': false});
      await _flush();
      expect(fake.named('setVisible').last.arguments['on'], false);
      await be.request('web.visible', {'on': true});
      await _flush();
      expect(fake.named('setVisible').last.arguments['on'], true);
    });

    test('keluar: hapus kuki lewat CDP lalu ke /signin', () async {
      _listen(be);
      await be.connect();
      await _flush();
      await be.request('acct.logout');
      await _flush();
      expect(fake.cdpCalls.first, 'Network.clearBrowserCookies');
      expect(fake.cdpCalls, contains('Storage.clearDataForOrigin'));
      expect(fake.named('navigate').last.arguments['url'], signinUrl);
      expect((_last['bot'] as Map)['needs_login'], true);
    });

    test('halaman /signin = tanda perlu login', () async {
      _listen(be);
      await be.connect();
      await _flush();
      await fake.emit(1, 'source', {'url': signinUrl});
      await _flush();
      expect((_last['bot'] as Map)['needs_login'], true);
      await fake.emit(1, 'source', {'url': homeUrl});
      await _flush();
      expect((_last['bot'] as Map)['needs_login'], false);
    });

    test('fitur yang belum diport menjawab ramah', () async {
      await be.connect();
      await _flush();
      expect(() => be.request('dev.simulate'), throwsA(isA<RpcException>()));
    });
  });

  group('WebView API', () {
    test('cdp/eval decode JSON, event CDP difilter per nama', () async {
      final fake = FakeNative();
      final host = WebHost();
      final v = await host.create(folder: tmp.path);
      expect(await v.eval('6*7'), 42);
      expect(await v.cdp('Page.enable'), isEmpty);
      final got = <Map>[];
      final sub = v.on('Page.loadEventFired').listen(got.add);
      final sub2 = v.on('Page.loadEventFired').listen((_) {});
      await Future<void>.delayed(Duration.zero);
      expect(fake.named('cdpSubscribe').length, 1);
      await fake.emit(v.id, 'cdp',
          {'event': 'Page.loadEventFired', 'params': '{"timestamp":1}'});
      await fake.emit(v.id, 'cdp', {'event': 'Other', 'params': '{}'});
      await Future<void>.delayed(Duration.zero);
      expect(got, [
        {'timestamp': 1}
      ]);
      await sub.cancel();
      expect(fake.named('cdpUnsubscribe'), isEmpty);
      await sub2.cancel();
      expect(fake.named('cdpUnsubscribe').length, 1);
    });
  });
}

Future<void> _flush() => Future<void>.delayed(Duration.zero);

// state terakhir per kunci dari event backend
final _last = <String, dynamic>{};

void _listen(Backend be) {
  _last.clear();
  be.events.listen((e) {
    if (e.name == 'snapshot') _last.addAll(Map<String, dynamic>.from(e.data as Map));
    if (e.name == 'state') _last.addAll(Map<String, dynamic>.from(e.data as Map));
  });
}
