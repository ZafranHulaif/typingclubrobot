// N3: backend native + mesin bot: Mulai/Stop, snapshot (fase, level,
// kemajuan), kunci rencana, kecepatan, ask, log. Host C++ dipalsukan
// lewat mock MethodChannel; CDP lewat edclub palsu.
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:typingbot/src/bridge/bridge.dart';
import 'package:typingbot/src/native/accounts.dart';
import 'package:typingbot/src/native/native_backend.dart';
import 'package:typingbot/src/web/web_host.dart';

import 'support/fake_edclub.dart';

const _ch = MethodChannel('typingbot/web_host');
const _l1 = 'https://www.edclub.com/student/course/3/lesson/116';
const _l2 = 'https://www.edclub.com/student/course/3/lesson/117';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late Directory tmp;
  late FakeEdclub fake;
  late NativeBackend be;
  late Map<String, dynamic> last;
  late List<SidecarAsk> asks;
  late List<String> logs;

  setUp(() async {
    tmp = Directory.systemTemp.createTempSync('tb_ne_');
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(_ch, (c) async {
      switch (c.method) {
        case 'version':
          return '131.0';
        case 'create':
          return (c.arguments as Map)['id'];
      }
      return null;
    });
    fake = FakeEdclub(url: _l1);
    be = NativeBackend(
      version: 'test',
      checkLicense: false,
      host: WebHost(),
      accounts: AccountStore(tmp.path),
      bridgeFor: (_) => fake.bridge,
      clock: fake.clock,
      pollInterval: const Duration(milliseconds: 5),
    );
    last = {};
    asks = [];
    logs = [];
    be.events.listen((e) {
      if (e.name == 'snapshot' || e.name == 'state') {
        last.addAll(Map<String, dynamic>.from(e.data as Map));
      }
      if (e.name == 'log') logs.add('${(e.data as Map)['raw']}');
    });
    be.asks.listen(asks.add);
    await be.connect();
  });

  tearDown(() async {
    be.engine?.st.stop = true;
    await be.stopped;
    tmp.deleteSync(recursive: true);
  });

  Map bot() => last['bot'] as Map;
  Map plan() => last['plan'] as Map;

  Future<void> waitFor(bool Function() ok, {int ms = 3000}) async {
    final sw = Stopwatch()..start();
    while (!ok()) {
      if (sw.elapsedMilliseconds > ms) fail('tidak tercapai dalam ${ms}ms');
      await Future<void>.delayed(const Duration(milliseconds: 5));
    }
  }

  test('Mulai: lesson diketik, level & kemajuan di snapshot, Stop = idle', () async {
    fake.lesson = FakeLesson('hello world', label: 'L1');
    fake.nextUrl = _l2;
    fake.nextLesson = FakeLesson('second', label: 'L2');
    await be.request('plan.set', {
      'segments': [
        {'from': 1, 'to': 5, 'stars': 5},
        {'from': 6, 'to': 20, 'stars': 4},
      ]
    });
    final r = await be.request('bot.start');
    expect(r, {'started': true});
    // halaman difokuskan dulu (blur = dianggap user aktif)
    await waitFor(() => fake.url == _l2 && fake.lesson!.done);
    await waitFor(() => (last['level'] as Map)['num'] == 2);
    expect(bot()['phase'], 'running');
    expect(plan()['active'], 0);
    expect(plan()['lock_until'], 4);
    expect(plan()['done_in_active'], 1);
    await waitFor(() => (last['level'] as Map)['progress'] == 1.0);
    expect((last['range'] as Map)['start'], 1);
    expect((last['range'] as Map)['end'], 20);
    expect(be.engine!.st.levelEnd, 20);

    await be.request('bot.stop');
    await be.stopped;
    await pumpEventQueue();
    expect(bot()['phase'], 'idle');
    expect(plan()['lock_until'], isNull);
    expect(logs.any((l) => l.startsWith('[Standard]')), isTrue);
    expect(File('${tmp.path}/bot.log').readAsStringSync(), contains('Bot berhenti.'));
  });

  test('kunci rencana: bagian aktif + 2 level ke depan tak boleh diubah', () async {
    fake.lesson = FakeLesson('a' * 50000, label: 'L1'); // lesson panjang: tetap jalan
    await be.request('plan.set', {
      'segments': [
        {'from': 1, 'to': 2, 'stars': 5},
        {'from': 3, 'to': 9, 'stars': 5},
        {'from': 10, 'to': 30, 'stars': 3},
      ]
    });
    await be.request('bot.start');
    await waitFor(() => plan()['lock_until'] == 3);
    // ubah bagian ke-2 (mulai 3 <= kunci 3) = ditolak
    expect(
        () => be.request('plan.set', {
              'segments': [
                {'from': 1, 'to': 2, 'stars': 5},
                {'from': 3, 'to': 9, 'stars': 4},
              ]
            }),
        throwsA(isA<RpcException>().having((e) => e.code, 'code', 'locked')));
    // ubah bagian yang belum terkunci = boleh, akhir rentang ikut
    await be.request('plan.set', {
      'segments': [
        {'from': 1, 'to': 2, 'stars': 5},
        {'from': 3, 'to': 9, 'stars': 5},
        {'from': 10, 'to': 50, 'stars': 2},
      ]
    });
    expect(be.engine!.st.levelEnd, 50);
    // kecepatan langsung berlaku di mesin & tersimpan
    await be.request('speed.set', {'wpm': 140});
    expect(be.engine!.st.speedWpm, 140);
    expect(File('${tmp.path}/typingbot_settings.json').readAsStringSync(), contains('"speed": 140'));
    // ganti akun saat jalan = ditolak
    expect(() => be.request('acct.switch', {'name': 'budi'}), throwsA(isA<RpcException>()));
    expect(() => be.request('bot.start'), throwsA(isA<RpcException>()));
  });

  test('sesi mati saat jalan -> needs_login di snapshot', () async {
    fake.url = 'https://www.edclub.com/signin';
    fake.profile = 'out';
    await be.request('bot.start');
    await waitFor(() => be.engine!.st.needsLogin);
    await waitFor(() => bot()['needs_login'] == true);
    expect(fake.keyEvents, isEmpty);
  });

  test('ask level.next: jawab Berhenti -> bot berhenti', () async {
    fake.url = 'https://www.edclub.com/student/course/3';
    await be.request('bot.start');
    await waitFor(() => be.engine != null && be.running);
    be.engine!.st.askNextLevel = true;
    await waitFor(() => asks.isNotEmpty);
    expect(asks.single.method, 'level.next');
    asks.single.answer({'wait': false});
    await waitFor(() => be.engine!.st.stop);
    await be.stopped;
    await pumpEventQueue();
    expect(bot()['phase'], 'idle');
  });

  test('pengaturan lama (speed/plan) dimuat saat buka', () async {
    File('${tmp.path}/typingbot_settings.json').writeAsStringSync(
        '{"speed": 225, "plan": [{"from": 4, "to": 9, "stars": 5, "silver": true}]}');
    final b2 = NativeBackend(
        version: 't', host: WebHost(), accounts: AccountStore(tmp.path), checkLicense: false);
    final got = <String, dynamic>{};
    b2.events.listen((e) {
      if (e.name == 'snapshot') got.addAll(Map<String, dynamic>.from(e.data as Map));
    });
    await b2.connect();
    await Future<void>.delayed(Duration.zero);
    expect((got['speed'] as Map)['wpm'], 225);
    expect(((got['plan'] as Map)['segments'] as List).single['from'], 4);
    b2.close();
  });
}
