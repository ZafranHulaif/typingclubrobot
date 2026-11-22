// macOS: peniru CDP di atas primitif WKWebView, diuji lewat Page asli.
import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:typingbot/src/engine/page.dart';
import 'package:typingbot/src/web/wk_cdp.dart';

class _Host implements WkHost {
  final calls = <(String, Map<String, Object?>)>[];
  // fid -> nilai yang dikembalikan evalFrame (sudah JSON)
  final evalResult = <String, Object?>{};
  @override
  Future<dynamic> call(String method, Map<String, Object?> args) async {
    calls.add((method, args));
    if (method == 'evalFrame') {
      final fid = '${args['fid']}';
      if (fid == 'mati') throw WkJsError('ReferenceError: x');
      final v = evalResult[fid];
      return v == null ? null : jsonEncode(v);
    }
    if (method == 'cookies') {
      return [
        {'name': 'rt', 'value': 'abc', 'domain': '.edclub.com'}
      ];
    }
    return null;
  }
}

class _Bridge implements CdpBridge {
  _Bridge(this.wk, this.ctl);
  final WkCdp wk;
  final StreamController<CdpEvent> ctl;
  @override
  Future<Map<String, dynamic>> send(String method,
          [Map<String, dynamic>? params, String session = '']) =>
      wk.send(method, params ?? const {});
  @override
  Stream<CdpEvent> listen(String method) =>
      ctl.stream.where((e) => e.method == method);
}

void main() {
  late _Host host;
  late WkCdp wk;
  late StreamController<CdpEvent> ctl;
  late Page page;

  setUp(() async {
    host = _Host();
    ctl = StreamController<CdpEvent>.broadcast(sync: true);
    wk = WkCdp(host, (m, p) => ctl.add(CdpEvent(m, p)));
    page = Page(_Bridge(wk, ctl));
    await page.attach();
  });

  void hello(String fid, String url, {bool main = false}) =>
      wk.onHostEvent('frame', {'fid': fid, 'phase': 'hello', 'url': url, 'main': main});

  test('frame utama + iframe lintas origin jadi Frame yang bisa dievaluasi', () async {
    hello('M1', 'https://www.edclub.com/student/course/3/lesson/405', main: true);
    hello('G1', 'https://phaser01balloonvalley.edclub.app/?nst=1', main: false);
    await Future<void>.delayed(Duration.zero);
    expect(page.url, contains('/lesson/405'));
    final fr = page.frames;
    expect(fr.map((f) => f.id), ['M1', 'G1']);
    expect(fr[1].url, contains('balloonvalley'));

    host.evalResult[''] = 7;
    host.evalResult['G1'] = {'ok': true};
    expect(await page.evaluate('() => 7'), 7);
    expect(await fr[1].evaluate('() => ({ok: true})'), {'ok': true});
    // frame utama = fid kosong (host pakai frame utama webview)
    final evals = host.calls.where((c) => c.$1 == 'evalFrame').toList();
    expect(evals.first.$2['fid'], '');
    expect(evals.last.$2['fid'], 'G1');
    expect('${evals.last.$2['body']}', contains('JSON.stringify'));
  });

  test('dokumen utama baru membuang frame lama; bye melepas iframe', () async {
    hello('M1', 'https://www.edclub.com/a', main: true);
    hello('G1', 'https://x.edclub.app/', main: false);
    wk.onHostEvent('frame', {'fid': 'G1', 'phase': 'bye'});
    await Future<void>.delayed(Duration.zero);
    expect(page.frames.map((f) => f.id), ['M1']);
    hello('M2', 'https://www.edclub.com/b', main: true);
    await Future<void>.delayed(Duration.zero);
    expect(page.url, 'https://www.edclub.com/b');
    expect(page.frames.map((f) => f.id), ['M2']);
  });

  test('pushState = navigatedWithinDocument, url halaman ikut', () async {
    hello('M1', 'https://www.edclub.com/student/course/3', main: true);
    wk.onHostEvent('frame', {
      'fid': 'M1',
      'phase': 'hash',
      'url': 'https://www.edclub.com/student/course/3/lesson/9'
    });
    await Future<void>.delayed(Duration.zero);
    expect(page.url, endsWith('/lesson/9'));
  });

  test('exception JS jadi EvalError', () async {
    hello('M1', 'https://www.edclub.com/', main: true);
    hello('mati', 'https://x.edclub.app/', main: false);
    await Future<void>.delayed(Duration.zero);
    final f = page.frames.last;
    expect(() => f.evaluate('() => x'), throwsA(isA<EvalError>()));
  });

  test('tombol & mouse diteruskan ke host', () async {
    hello('M1', 'https://www.edclub.com/', main: true);
    await page.keyboard.type('a');
    await page.mouse.click(10, 20);
    final keys = host.calls.where((c) => c.$1 == 'key').toList();
    expect(keys.map((c) => c.$2['type']), ['down', 'up']);
    expect(keys.first.$2['text'], 'a');
    expect(keys.first.$2['code'], 'KeyA');
    final mice = host.calls.where((c) => c.$1 == 'mouse').map((c) => c.$2['type']);
    expect(mice, ['move', 'down', 'up']);
  });

  test('goto menunggu nav done dari host', () async {
    hello('M1', 'https://www.edclub.com/', main: true);
    final f = page.goto('https://www.edclub.com/student/course/3', timeout: 5);
    await Future<void>.delayed(Duration.zero);
    hello('M2', 'https://www.edclub.com/student/course/3', main: true);
    wk.onHostEvent('nav', {'phase': 'done', 'url': 'https://www.edclub.com/student/course/3'});
    await f;
    expect(host.calls.any((c) => c.$1 == 'navigate'), isTrue);
    expect(page.url, endsWith('/course/3'));
  });

  test('kuki rt terbaca lewat Network.getCookies', () async {
    final r = await wk.send('Network.getCookies', {
      'urls': ['https://api.edclub.com/']
    });
    expect((r['cookies'] as List).first['value'], 'abc');
  });
}
