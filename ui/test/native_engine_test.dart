// N3: backend native + mesin bot: Mulai/Stop, snapshot (fase, level,
// kemajuan), kunci rencana, kecepatan, ask, log. Host C++ dipalsukan
// lewat mock MethodChannel; CDP lewat edclub palsu.
import 'dart:convert';
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
  var memCalls = 0;
  final awake = <bool>[];

  setUp(() async {
    tmp = Directory.systemTemp.createTempSync('tb_ne_');
    awake.clear();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(_ch, (c) async {
      switch (c.method) {
        case 'version':
          return '131.0';
        case 'create':
          return (c.arguments as Map)['id'];
        case 'info':
          return {'url': fake.url, 'title': ''};
        case 'keepAwake':
          awake.add((c.arguments as Map)['on'] == true);
          return null;
        case 'memInfo':
          const mb = 1048576;
          // waktu CPU renderer naik tiap sampel
          final cpu = 1000000 * ++memCalls;
          return [
            {'kind': 'browser', 'pid': 1, 'private': 100 * mb, 'ws': 0, 'cpu': 0},
            {'kind': 'renderer', 'pid': 2, 'private': 300 * mb, 'ws': 0, 'cpu': cpu},
            {'kind': 'renderer', 'pid': 3, 'private': 200 * mb, 'ws': 0, 'cpu': 0},
            {'kind': 'gpu', 'pid': 4, 'private': 150 * mb, 'ws': 0, 'cpu': 0},
          ];
        case 'eval':
          // cek login (penanda DOM) mengikuti edclub palsu
          if ('${(c.arguments as Map)['js']}'.contains('tb:login')) {
            return jsonEncode(fake.profile);
          }
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
    final r = await be.request('bot.start', {'mode': 'plan'});
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

  test('memori: buffer Network kecil, rincian memori WebView2 masuk bot.log', () async {
    fake.lesson = FakeLesson('hello world', label: 'L1');
    await be.request('plan.set', {
      'segments': [
        {'from': 1, 'to': 5, 'stars': 5},
      ]
    });
    await be.request('bot.start', {'mode': 'plan'});
    await waitFor(() => fake.bridge.named('Network.enable').isNotEmpty);
    final p = fake.bridge.named('Network.enable').first.params;
    expect(p['maxTotalBufferSize'], lessThanOrEqualTo(1000000));
    // komputer dijaga tetap bangun selama bot jalan
    expect(awake, [true]);
    await be.request('bot.stop');
    await be.stopped;
    expect(awake, [true, false]);
    final log = File('${tmp.path}/bot.log');
    await waitFor(() => log.readAsStringSync().contains('[mem]'));
    expect(log.readAsStringSync(),
        contains('[mem] WebView2 750 MB: renderer 2x 500, gpu 150, browser 100'));
    expect(log.readAsStringSync(), matches(RegExp(r'\[cpu\] WebView2 \d+%: renderer \d+')));
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
    await be.request('bot.start', {'mode': 'plan'});
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
    // rencana = mode bintang: dial tersimpan, mesin tetap secepatnya
    await be.request('speed.set', {'wpm': 140});
    expect(be.engine!.st.speedWpm, 400);
    expect(File('${tmp.path}/typingbot_settings.json').readAsStringSync(), contains('"speed": 140'));
    expect((last['speed'] as Map)['locked'], true);
    // ganti akun saat jalan = ditolak
    expect(() => be.request('acct.switch', {'name': 'budi'}), throwsA(isA<RpcException>()));
    expect(() => be.request('bot.start'), throwsA(isA<RpcException>()));
  });

  test('belum login: Mulai menunggu login (mesin belum jalan), lalu lanjut', () async {
    fake.url = 'https://www.edclub.com/signin';
    fake.profile = 'out';
    await be.request('bot.start', {'mode': 'free'});
    await pumpEventQueue();
    expect(bot()['phase'], 'waiting');
    expect(bot()['wait'], 'login');
    expect(bot()['needs_login'], true);
    expect(be.engine, isNull);
    // user login & membuka lesson -> mesin mulai di lesson itu
    fake.profile = 'in';
    fake.lesson = FakeLesson('abc', label: 'L1');
    fake.url = _l1;
    await waitFor(() => be.running, ms: 3000);
    expect(be.engine!.st.levelEnd, 0);
  });

  test('mode Manual: dial berlaku langsung, perkiraan bintang level ini di snapshot', () async {
    final text = List.filled(20, 'asdf jkl ').join();
    fake.lesson = FakeLesson(text, label: 'L1');
    fake.lessonGoal = {
      'goal': 10, 'min_wpm': 3, 'min_acc': 80, 'on_error': 'continue',
      'objc': false, 'test': false, 'diff': 0, 'n': text.length, 'pos': 0, 'total': 0,
    };
    await be.request('free.set', {'mode': 'manual'});
    await be.request('speed.set', {'wpm': 140, 'acc': 95});
    Map sp() => last['speed'] as Map;
    expect(sp()['manual'], true);
    expect(sp()['locked'], false);
    expect(sp()['guess'], isNull); // belum ada level
    await be.request('bot.start', {'mode': 'free'});
    await waitFor(() => be.running);
    expect(be.engine!.st.speedWpm, 140);
    await waitFor(() => sp()['guess'] != null);
    // goal 10, 140 wpm, 95% -> rasio penuh, ada salah = 5 (bukan platinum)
    expect((sp()['guess'] as Map)['stars'], 5);
    expect((sp()['guess'] as Map)['silver'], false);
    // geser ke 100% -> perkiraan ikut berubah (platinum)
    await be.request('speed.set', {'acc': 100});
    await waitFor(() => (sp()['guess'] as Map)['silver'] == true);
    await be.request('speed.set', {'wpm': 85});
    expect(be.engine!.st.speedWpm, 85);
    // balik ke mode bintang = dial terkunci, mesin secepatnya
    await be.request('free.set', {'mode': 'stars'});
    expect(be.engine!.st.speedWpm, 400);
    await waitFor(() => sp()['locked'] == true && sp()['guess'] == null);
    expect(logs.any((l) => l.startsWith('[Manual] 140 wpm, akurasi 95%')), isTrue);
  });

  test('rencana pola: tiap level berbintang dapat giliran, tersimpan & sama saat diulang', () async {
    final text = List.filled(8, 'asdf jkl ').join();
    fake.lesson = FakeLesson(text, label: 'L1');
    fake.nextUrl = _l2;
    fake.nextLesson = FakeLesson(text, label: 'L2');
    fake.lessonGoal = {
      'goal': 10, 'min_wpm': 3, 'min_acc': 80, 'on_error': 'continue',
      'objc': false, 'test': false, 'diff': 0, 'n': text.length, 'pos': 0, 'total': 0,
    };
    await be.request('plan.set', {
      'segments': [
        {'from': 1, 'to': 20, 'rule': 'pattern', 'pattern': [2, 4]},
      ]
    });
    expect((plan()['segments'] as List).single['pattern'], [2, 4]);
    await be.request('bot.start', {'mode': 'plan'});
    await waitFor(() => fake.url == _l2 && fake.lesson!.done, ms: 20000);
    await be.request('bot.stop');
    await be.stopped;
    expect(logs.any((l) => l.startsWith('[Bintang] level 1: pola 2,4, level berbintang ke-1 -> target 2')), isTrue,
        reason: logs.where((l) => l.startsWith('[Bintang]')).join('\n'));
    expect(logs.any((l) => l.startsWith('[Bintang] level 2: pola 2,4, level berbintang ke-2 -> target 4')), isTrue);
    expect(logs.any((l) => l.startsWith('[Bintang] target 2: goal 10')), isTrue);
    expect(logs.any((l) => l.startsWith('[Bintang] target 4: goal 10')), isTrue);
    final sig = ((plan()['seq'] as Map).keys).single;
    expect((plan()['seq'] as Map)[sig]['n'], 2);
    expect((plan()['seq'] as Map)[sig]['lv'], {'1': 0, '2': 1});
    // jenis level tercatat utk peta level editor
    expect((last['catalog'] as Map)['1'], 'star');
    expect((last['catalog'] as Map)['2'], 'star');
    // level 1 selesai (bot maju ke level 2): target yang dipakai tercatat
    expect(((plan()['done'] as Map)['1'] as Map)['c'], 2);
    // level 2 diulang: tetap target 4, tidak mengambil giliran baru
    logs.clear();
    fake.lesson = FakeLesson(text, label: 'L2');
    await be.request('bot.start', {'mode': 'plan'});
    await waitFor(() => fake.lesson!.done, ms: 20000);
    await be.request('bot.stop');
    await be.stopped;
    expect(logs.any((l) => l.contains('ke-3')), isFalse);
    expect(logs.any((l) => l.startsWith('[Bintang] target 4: goal 10')), isTrue);
    // pola diubah = urutan lama dibuang
    await be.request('plan.set', {
      'segments': [
        {'from': 1, 'to': 20, 'rule': 'pattern', 'pattern': [3]},
      ]
    });
    await pumpEventQueue();
    expect(plan()['seq'], isEmpty);
    // pola kosong ditolak
    expect(
        () => be.request('plan.set', {
              'segments': [
                {'from': 1, 'to': 20, 'rule': 'pattern', 'pattern': []},
              ]
            }),
        throwsA(isA<RpcException>()));
  });

  test('level tanpa nilai bintang (tes/objektif) tidak memakai giliran', () async {
    final text = List.filled(8, 'asdf jkl ').join();
    fake.lesson = FakeLesson(text, label: 'L1');
    fake.lessonGoal = {
      'goal': 10, 'min_wpm': 3, 'min_acc': 80, 'on_error': 'continue',
      'objc': true, 'test': false, 'diff': 0, 'n': text.length, 'pos': 0, 'total': 0,
    };
    await be.request('plan.set', {
      'segments': [
        {'from': 1, 'to': 20, 'rule': 'random', 'min': 2, 'max': 4},
      ]
    });
    await be.request('bot.start', {'mode': 'plan'});
    await waitFor(() => fake.lesson!.done, ms: 20000);
    await be.request('bot.stop');
    await be.stopped;
    await pumpEventQueue();
    expect(plan()['seq'], isEmpty);
    expect(logs.any((l) => l.contains('level berbintang ke-')), isFalse);
    expect((last['catalog'] as Map)['1'], 'test');
  });

  test('aturan khusus game: tersimpan, ikut rencana = default', () async {
    Map games() => last['games'] as Map;
    expect(games()['balloon']['rule'], 'follow');
    await be.request('games.set', {
      'balloon': {'rule': 'fixed', 'stars': 3},
      'monster': {'rule': 'random', 'min': 3, 'max': 6},
    });
    expect(games()['balloon']['stars'], 3);
    expect(games()['monster']['max'], 6);
    final saved = jsonDecode(File('${tmp.path}/typingbot_settings.json').readAsStringSync());
    expect(saved['game_rules']['balloon']['rule'], 'fixed');
    expect(
        () => be.request('games.set', {'balloon': {'rule': 'pattern', 'pattern': []}}),
        throwsA(isA<RpcException>()));
  });

  test('game balon selalu 3 bintang saat rencana jalan: aturan khusus menang', () async {
    final game = FakeGame(List.filled(12, 'asdfj').join(), goal: 10);
    fake.url = 'https://www.edclub.com/sportal/program-3/2953.play';
    fake.game = game;
    await be.request('games.set', {'balloon': {'rule': 'fixed', 'stars': 3}});
    await be.request('plan.set', {
      'segments': [
        {'from': 62, 'to': 62, 'stars': 5, 'silver': true},
      ]
    });
    await be.request('bot.start', {'mode': 'plan'});
    await waitFor(() => game.ended, ms: 20000);
    await be.request('bot.stop');
    await be.stopped;
    expect(game.stars, 3, reason: 'rasio ${game.ratio}');
    expect(logs.any((l) => l.startsWith('[Bintang] game BalloonValley target 3')), isTrue);
    expect((last['catalog'] as Map)['62'], 'balloon');
  });

  test('aturan khusus game tidak berlaku tanpa rencana', () async {
    final game = FakeGame(List.filled(12, 'asdfj').join(), goal: 10);
    fake.url = 'https://www.edclub.com/sportal/program-3/2953.play';
    fake.game = game;
    await be.request('games.set', {'balloon': {'rule': 'fixed', 'stars': 3}});
    await be.request('bot.start', {'mode': 'free'});
    await waitFor(() => game.ended, ms: 20000);
    await be.request('bot.stop');
    await be.stopped;
    expect(logs.any((l) => l.startsWith('[Bintang] game BalloonValley target 3')), isFalse);
    expect(game.stars, isNot(3), reason: 'rasio ${game.ratio}');
    // tetap tercatat jenisnya walau platinum
    expect((last['catalog'] as Map)['62'], 'balloon');
  });

  test('Stop saat menunggu = kembali siap', () async {
    fake.url = 'https://www.edclub.com/student/course/3';
    await be.request('bot.start', {'mode': 'free'});
    await pumpEventQueue();
    expect(bot()['wait'], 'pick');
    await be.request('bot.stop');
    await pumpEventQueue();
    expect(bot()['phase'], 'idle');
    expect(be.busy, isFalse);
  });

  test('rencana kosong: Mulai rencana ditolak dgn pesan', () async {
    expect(() => be.request('bot.start', {'mode': 'plan'}),
        throwsA(isA<RpcException>().having((e) => e.code, 'code', 'empty')));
  });

  test('level di atas 685 ditolak', () async {
    expect(
        () => be.request('plan.set', {
              'segments': [
                {'from': 600, 'to': 690, 'stars': 5},
              ]
            }),
        throwsA(isA<RpcException>()));
  });

  test('ask level.next: jawab Berhenti -> bot berhenti', () async {
    fake.url = 'https://www.edclub.com/student/course/3';
    await be.request('plan.set', {
      'segments': [
        {'from': 1, 'to': 0, 'stars': 5},
      ]
    });
    await be.request('bot.start', {'mode': 'plan'});
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

  test('tanpa rencana: menunggu user memilih level, lalu mulai di situ', () async {
    fake.url = 'https://www.edclub.com/student/course/3';
    await be.request('bot.start', {'mode': 'free'});
    await pumpEventQueue();
    expect(bot()['phase'], 'waiting');
    expect(bot()['wait'], 'pick');
    expect(bot()['mode'], 'free');
    fake.lesson = FakeLesson('abc', label: 'L1');
    fake.url = _l1;
    await waitFor(() => be.running, ms: 3000);
    // tanpa rencana: kotak rencana tidak aktif/terkunci
    await waitFor(() => bot()['phase'] == 'running');
    expect(plan()['lock_until'], isNull);
  });

  test('lesson sudah terbuka saat Mulai: langsung jalan', () async {
    fake.lesson = FakeLesson('abc', label: 'L1');
    await be.request('bot.start', {'mode': 'free'});
    expect(be.running, isTrue);
  });

  test('rencana per akun: ganti akun = rencana sendiri-sendiri', () async {
    await be.request('plan.set', {
      'segments': [
        {'from': 3, 'to': 9, 'stars': 5},
      ]
    });
    await be.request('acct.switch', {'name': 'budi'});
    await pumpEventQueue();
    expect(plan()['segments'], isEmpty);
    await be.request('plan.set', {
      'segments': [
        {'from': 20, 'to': 30, 'stars': 4},
      ]
    });
    await be.request('acct.switch', {'name': 'sari'});
    await pumpEventQueue();
    expect(plan()['segments'], isEmpty);
    await be.request('acct.switch', {'name': 'budi'});
    await pumpEventQueue();
    expect((plan()['segments'] as List).single['from'], 20);
  });

  test('rencana lama > 685 dirapikan saat dimuat', () async {
    File('${tmp.path}/typingbot_settings.json').writeAsStringSync(
        '{"plan": [{"from": 364, "to": 695, "stars": 5}, {"from": 700, "to": 0, "stars": 5}]}');
    final b2 = NativeBackend(
        version: 't', host: WebHost(), accounts: AccountStore(tmp.path), checkLicense: false);
    final got = <String, dynamic>{};
    b2.events.listen((e) {
      if (e.name == 'snapshot') got.addAll(Map<String, dynamic>.from(e.data as Map));
    });
    await b2.connect();
    await Future<void>.delayed(Duration.zero);
    final segs = (got['plan'] as Map)['segments'] as List;
    expect(segs.length, 1);
    expect(segs.single['to'], 685);
    b2.close();
  });

  test('Mulai rencana di atas level terbuka = ditolak', () async {
    be.close();
    File('${tmp.path}/typingbot_settings.json').writeAsStringSync(
        '{"unlocked": {"": 10}, "plans": {"": [{"from": 364, "to": 400, "stars": 5}]}}');
    final b2 = NativeBackend(
        version: 't', host: WebHost(), accounts: AccountStore(tmp.path),
        checkLicense: false, bridgeFor: (_) => fake.bridge, clock: fake.clock);
    await b2.connect();
    expect(() => b2.request('bot.start', {'mode': 'plan'}),
        throwsA(isA<RpcException>().having((e) => e.code, 'code', 'locked_level')));
    b2.close();
  });

  test('pindah ke 4.1: platinum + kecepatan diturunkan = mode Manual 100%', () async {
    Future<Map<String, dynamic>> buka(String json) async {
      File('${tmp.path}/typingbot_settings.json').writeAsStringSync(json);
      final b2 = NativeBackend(
          version: 't', host: WebHost(), accounts: AccountStore(tmp.path), checkLicense: false);
      final got = <String, dynamic>{};
      b2.events.listen((e) {
        if (e.name == 'snapshot') got.addAll(Map<String, dynamic>.from(e.data as Map));
      });
      await b2.connect();
      await Future<void>.delayed(Duration.zero);
      b2.close();
      return got;
    }

    var g = await buka('{"speed": 140, "free": {"stars": 5, "silver": true}}');
    expect((g['free'] as Map)['mode'], 'manual');
    expect((g['speed'] as Map)['acc'], 100);
    expect((g['speed'] as Map)['locked'], false);
    // kecepatan maksimal / target bintang lain = tetap mode bintang
    g = await buka('{"speed": 400, "free": {"stars": 5, "silver": true}}');
    expect((g['free'] as Map)['mode'], 'stars');
    expect((g['speed'] as Map)['auto_wpm'], 400);
    g = await buka('{"speed": 140, "free": {"stars": 3, "silver": false}}');
    expect((g['free'] as Map)['mode'], 'stars');
    // pilihan yang sudah tersimpan dihormati
    g = await buka('{"speed": 400, "acc": 90, "free": {"stars": 4, "mode": "manual"}}');
    expect((g['free'] as Map)['mode'], 'manual');
    expect((g['speed'] as Map)['acc'], 90);
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
