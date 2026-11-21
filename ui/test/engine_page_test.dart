// N2: API halaman ala Playwright di atas CDP, diuji dgn bridge palsu.
import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:typingbot/src/engine/clock.dart';
import 'package:typingbot/src/engine/page.dart';

import 'support/fake_bridge.dart';

Map<String, dynamic> _tree(String url, [List<Map<String, dynamic>> kids = const []]) => {
      'frameTree': {
        'frame': {'id': 'MAIN', 'url': url, 'name': ''},
        'childFrames': kids,
      }
    };

Future<(FakeBridge, Page, FakeClock)> _page({String url = 'https://www.edclub.com/student/course/3'}) async {
  final b = FakeBridge();
  final clock = FakeClock();
  b.handlers['Page.getFrameTree'] = (p, s) => s.isEmpty
      ? _tree(url)
      : {
          'frameTree': {
            'frame': {'id': 'OOP1', 'url': 'https://phaser01balloonvalley.edclub.app/', 'name': 'g', 'parentId': 'MAIN'}
          }
        };
  final page = Page(b, clock: clock);
  await page.attach();
  return (b, page, clock);
}

void main() {
  group('ekspresi evaluate (semantik Playwright)', () {
    test('string fungsi dipanggil, argumen JSON', () {
      expect(Page.buildExpression('() => location.href', null, false),
          '(() => location.href)()');
      expect(Page.buildExpression('(n) => n + 1', 5, true), '((n) => n + 1)(5)');
      expect(Page.buildExpression('async () => { return 1; }', null, false),
          '(async () => { return 1; })()');
      expect(Page.buildExpression('(arg) => {x}', {'a': 'b'}, true),
          '((arg) => {x})({"a":"b"})');
      expect(Page.buildExpression('function () { return 2 }', null, false),
          '(function () { return 2 })()');
    });
    test('selain fungsi = ekspresi apa adanya', () {
      expect(Page.buildExpression('1', null, false), '1');
      expect(Page.buildExpression(' document.title ', 3, true), 'document.title');
    });
  });

  group('attach & frame', () {
    test('aktifkan domain, baca pohon frame, url utama', () async {
      final (b, page, _) = await _page();
      expect(b.named('Page.enable'), isNotEmpty);
      expect(b.named('Runtime.enable'), isNotEmpty);
      expect(b.named('Target.setAutoAttach').first.params['flatten'], isTrue);
      expect(page.url, 'https://www.edclub.com/student/course/3');
      expect(page.mainFrame.isMain, isTrue);
      expect(page.frames.single, page.mainFrame);
    });

    test('url ikut navigasi & SPA', () async {
      final (b, page, _) = await _page();
      b.emit('Page.frameNavigated', {
        'frame': {'id': 'MAIN', 'url': 'https://www.edclub.com/signin'}
      });
      expect(page.url, 'https://www.edclub.com/signin');
      b.emit('Page.navigatedWithinDocument',
          {'frameId': 'MAIN', 'url': 'https://www.edclub.com/student/course/3/lesson/116'});
      expect(page.url, endsWith('/lesson/116'));
    });

    test('iframe satu proses dievaluasi lewat contextId', () async {
      final (b, page, _) = await _page();
      b.emit('Page.frameAttached', {'frameId': 'F2', 'parentFrameId': 'MAIN'});
      b.emit('Page.frameNavigated', {
        'frame': {'id': 'F2', 'parentId': 'MAIN', 'url': 'https://www.edclub.com/x'}
      });
      b.emit('Runtime.executionContextCreated', {
        'context': {'id': 7, 'auxData': {'frameId': 'F2', 'isDefault': true}}
      });
      b.emit('Runtime.executionContextCreated', {
        'context': {'id': 8, 'auxData': {'frameId': 'F2', 'isDefault': false}}
      });
      b.handlers['Runtime.evaluate'] = (p, s) => {
            'result': {'type': 'number', 'value': p['contextId']}
          };
      final f = page.frames.firstWhere((f) => !f.isMain);
      expect(f.url, 'https://www.edclub.com/x');
      expect(await f.evaluate('() => 1'), 7);
      // konteks hancur -> frame tak bisa dievaluasi lagi
      b.emit('Runtime.executionContextDestroyed', {'executionContextId': 7});
      expect(page.frames.length, 1);
    });

    test('iframe lintas origin = sesi anak (Target.attachedToTarget)', () async {
      final (b, page, _) = await _page();
      b.emit('Target.attachedToTarget', {
        'sessionId': 'S1',
        'targetInfo': {'targetId': 'OOP1', 'type': 'iframe', 'url': 'https://phaser01balloonvalley.edclub.app/'},
      });
      await pumpEventQueue();
      expect(b.sent.where((c) => c.session == 'S1').map((c) => c.method),
          containsAll(['Page.enable', 'Runtime.enable', 'Runtime.runIfWaitingForDebugger']));
      b.handlers['Runtime.evaluate'] = (p, s) => {
            'result': {'type': 'string', 'value': 'dari $s ${p['contextId']}'}
          };
      final g = page.frames.firstWhere((f) => !f.isMain);
      expect(g.url, contains('balloonvalley'));
      expect(await g.evaluate('() => 1'), 'dari S1 null');
      b.emit('Target.detachedFromTarget', {'sessionId': 'S1'});
      expect(page.frames.length, 1);
    });
  });

  group('evaluate', () {
    test('nilai, undefined, error JS', () async {
      final (b, page, _) = await _page();
      var mode = 0;
      b.handlers['Runtime.evaluate'] = (p, s) => switch (mode) {
            0 => {'result': {'type': 'object', 'value': {'a': 1}}},
            1 => {'result': {'type': 'undefined'}},
            _ => {
                'result': {'type': 'object'},
                'exceptionDetails': {'text': 'Uncaught', 'exception': {'description': 'ReferenceError: x'}}
              },
          };
      expect(await page.evaluate('() => ({a: 1})'), {'a': 1});
      final call = b.named('Runtime.evaluate').last.params;
      expect(call['returnByValue'], isTrue);
      expect(call['awaitPromise'], isTrue);
      expect(call.containsKey('contextId'), isFalse);
      mode = 1;
      expect(await page.evaluate('() => undefined'), isNull);
      mode = 2;
      expect(() => page.evaluate('() => x'), throwsA(isA<EvalError>()));
    });

    test('renderer menggantung = alive false (batas waktu)', () async {
      final (b, page, _) = await _page();
      b.handlers['Runtime.evaluate'] = (p, s) => Completer<Map<String, dynamic>>().future;
      expect(await page.alive(timeout: 0.05), isFalse);
      b.handlers['Runtime.evaluate'] = (p, s) => {'result': {'type': 'number', 'value': 1}};
      expect(await page.alive(), isTrue);
    });
  });

  group('keyboard (event sama dgn Playwright)', () {
    test('type huruf, kapital, spasi, Enter', () async {
      final (b, page, clock) = await _page();
      await page.keyboard.type('aA \n', delayMs: 30);
      final ev = b.named('Input.dispatchKeyEvent').map((c) => c.params).toList();
      expect(ev.length, 8);
      expect(ev[0], containsPair('type', 'keyDown'));
      expect(ev[0], containsPair('key', 'a'));
      expect(ev[0], containsPair('code', 'KeyA'));
      expect(ev[0], containsPair('windowsVirtualKeyCode', 65));
      expect(ev[0], containsPair('text', 'a'));
      expect(ev[1], containsPair('type', 'keyUp'));
      expect(ev[2], containsPair('key', 'A'));
      expect(ev[2], containsPair('text', 'A'));
      expect(ev[2], containsPair('modifiers', 0));
      expect(ev[4], containsPair('code', 'Space'));
      expect(ev[4], containsPair('text', ' '));
      expect(ev[6], containsPair('key', 'Enter'));
      expect(ev[6], containsPair('text', '\r'));
      // jeda di antara down & up tiap tombol (keyboard.type delay)
      expect(clock.sleeps, [0.03, 0.03, 0.03, 0.03]);
    });

    test('Tab/Backspace tanpa teks = rawKeyDown', () async {
      final (b, page, _) = await _page();
      await page.keyboard.press('Tab');
      await page.keyboard.press('Backspace');
      final ev = b.named('Input.dispatchKeyEvent').map((c) => c.params).toList();
      expect(ev[0]['type'], 'rawKeyDown');
      expect(ev[0]['windowsVirtualKeyCode'], 9);
      expect(ev[2]['type'], 'rawKeyDown');
      expect(ev[2]['windowsVirtualKeyCode'], 8);
    });

    test('Shift ditahan -> huruf jadi kapital, modifier 8; lepas = bersih', () async {
      final (b, page, _) = await _page();
      await page.keyboard.down('Shift');
      await page.keyboard.type('f');
      await page.keyboard.up('Shift');
      final ev = b.named('Input.dispatchKeyEvent').map((c) => c.params).toList();
      expect(ev[0], containsPair('key', 'Shift'));
      expect(ev[0], containsPair('code', 'ShiftLeft'));
      expect(ev[1], containsPair('key', 'F'));
      expect(ev[1], containsPair('modifiers', 8));
      expect(ev.last, containsPair('modifiers', 0));
      expect(page.keyboard.modifiers, 0);
    });

    test('tahan tombol yang sama 2x = autoRepeat', () async {
      final (b, page, _) = await _page();
      await page.keyboard.down('j');
      await page.keyboard.down('j');
      final ev = b.named('Input.dispatchKeyEvent').map((c) => c.params).toList();
      expect(ev[0]['autoRepeat'], isFalse);
      expect(ev[1]['autoRepeat'], isTrue);
    });

    test('karakter di luar layout lewat insertText', () async {
      final (b, page, _) = await _page();
      await page.keyboard.type('é');
      expect(b.named('Input.insertText').single.params['text'], 'é');
    });
  });

  test('mouse.click = moved, pressed, released', () async {
    final (b, page, _) = await _page();
    await page.mouse.click(10, 20);
    final ev = b.named('Input.dispatchMouseEvent').map((c) => c.params['type']).toList();
    expect(ev, ['mouseMoved', 'mousePressed', 'mouseReleased']);
    expect(b.named('Input.dispatchMouseEvent').elementAt(1).params,
        allOf(containsPair('x', 10), containsPair('button', 'left'), containsPair('clickCount', 1)));
  });

  group('navigasi', () {
    test('goto menunggu load; SPA langsung; error dilempar', () async {
      final (b, page, _) = await _page();
      b.handlers['Page.navigate'] = (p, s) {
        if ('${p['url']}'.contains('bad')) return {'errorText': 'net::ERR_NAME_NOT_RESOLVED'};
        if ('${p['url']}'.contains('spa')) return {'frameId': 'MAIN'};
        scheduleMicrotask(() => b.emit('Page.loadEventFired', {'timestamp': 1}));
        return {'frameId': 'MAIN', 'loaderId': 'L1'};
      };
      await page.goto('https://www.edclub.com/a');
      await page.goto('https://www.edclub.com/spa');
      expect(page.url, 'https://www.edclub.com/spa');
      expect(() => page.goto('https://bad'), throwsA(isA<PageError>()));
    });

    test('goto tanpa load = timeout', () async {
      final (b, page, _) = await _page();
      b.handlers['Page.navigate'] = (p, s) => {'frameId': 'MAIN', 'loaderId': 'L1'};
      expect(() => page.goto('https://www.edclub.com/a', timeout: 0.05),
          throwsA(isA<TimeoutException>()));
    });

    test('goBack lewat riwayat', () async {
      final (b, page, _) = await _page();
      b.handlers['Page.getNavigationHistory'] = (p, s) => {
            'currentIndex': 1,
            'entries': [
              {'id': 11, 'url': 'a'},
              {'id': 12, 'url': 'b'}
            ]
          };
      b.handlers['Page.navigateToHistoryEntry'] = (p, s) {
        scheduleMicrotask(() => b.emit('Page.frameNavigated', {
              'frame': {'id': 'MAIN', 'url': 'a'}
            }));
        return {};
      };
      await page.goBack();
      expect(b.named('Page.navigateToHistoryEntry').single.params['entryId'], 11);
      expect(page.url, 'a');
    });
  });

  group('locator', () {
    test('click = klik mouse di tengah elemen + offset iframe', () async {
      final (b, page, _) = await _page();
      b.emit('Page.frameAttached', {'frameId': 'F2', 'parentFrameId': 'MAIN'});
      b.emit('Page.frameNavigated', {
        'frame': {'id': 'F2', 'parentId': 'MAIN', 'url': 'https://www.edclub.com/v'}
      });
      b.emit('Runtime.executionContextCreated', {
        'context': {'id': 5, 'auxData': {'frameId': 'F2', 'isDefault': true}}
      });
      b.handlers['Runtime.evaluate'] = (p, s) => {
            'result': {'type': 'object', 'value': {'x': 50, 'y': 40}}
          };
      b.handlers['DOM.getFrameOwner'] = (p, s) => {'backendNodeId': 99};
      b.handlers['DOM.getBoxModel'] = (p, s) => {
            'model': {'content': [100, 200, 300, 200, 300, 400, 100, 400]}
          };
      final f = page.frames.firstWhere((f) => !f.isMain);
      await f.locator('.vjs-big-play-button').first.click(timeout: 2);
      final press = b.named('Input.dispatchMouseEvent').elementAt(1).params;
      expect(press['x'], 150);
      expect(press['y'], 240);
      // argumen langkah locator terkirim ke JS
      final expr = '${b.named('Runtime.evaluate').first.params['expression']}';
      expect(expr, contains('.vjs-big-play-button'));
      expect(expr, contains('"i":0'));
    });

    test('click menunggu elemen tampil, lalu timeout', () async {
      final (b, page, _) = await _page();
      b.handlers['Runtime.evaluate'] = (p, s) => {'result': {'type': 'object', 'value': null}};
      expect(() => page.locator('.navbar-continue').first.click(timeout: 0.5),
          throwsA(isA<TimeoutException>()));
    });

    test('count / isVisible / has_text dikirim ke JS', () async {
      final (b, page, _) = await _page();
      b.handlers['Runtime.evaluate'] = (p, s) {
        final e = '${p['expression']}';
        if (e.contains('return els.length')) return {'result': {'type': 'number', 'value': 2}};
        return {'result': {'type': 'boolean', 'value': true}};
      };
      final loc = page.locator('[role="dialog"]').first.locator('button', hasText: 'Confirm');
      expect(await loc.count(), 2);
      expect(await loc.first.isVisible(), isTrue);
      final expr = '${b.named('Runtime.evaluate').first.params['expression']}';
      expect(expr, contains('"t":"Confirm"'));
    });

    test('fill = fokus lalu insertText', () async {
      final (b, page, _) = await _page();
      b.handlers['Runtime.evaluate'] = (p, s) => {'result': {'type': 'boolean', 'value': true}};
      await page.locator('input[name="year"]').fill('2000', timeout: 1);
      expect(b.named('Input.insertText').single.params['text'], '2000');
    });
  });

  test('waitForSelector polling sampai tampil', () async {
    final (b, page, clock) = await _page();
    var n = 0;
    b.handlers['Runtime.evaluate'] = (p, s) => {
          'result': {'type': 'boolean', 'value': ++n >= 3}
        };
    await page.waitForSelector("a[aria-label^='Lesson ']", timeout: 5);
    expect(n, 3);
    expect(clock.sleeps.length, 2);
  });
}
