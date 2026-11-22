// N2: API "halaman" ala Playwright di atas CDP, utk mesin bot hasil port.
//
// engine 3.5.x memakai Playwright (connect_over_cdp). Bagian yang benar2
// dipakai (grep 2026-11-21): evaluate, keyboard type/press/down/up,
// mouse.click, goto, reload, go_back, wait_for_selector,
// add_init_script, url, frames/main_frame, locator. Semua diterjemahkan
// ke panggilan CDP biasa lewat [CdpBridge] (WebView2 native di Windows,
// bridge palsu di tes).
//
// Frame: iframe satu proses dievaluasi lewat contextId (Runtime.enable),
// iframe lintas origin (game balon, video corevideo.edclub.app) = target
// anak lewat Target.setAutoAttach(flatten) + sessionId.
import 'dart:async';
import 'dart:convert';

import 'clock.dart';
import 'keys.dart';

class CdpEvent {
  CdpEvent(this.method, this.params, [this.session = '']);
  final String method;
  final Map<String, dynamic> params;
  final String session;
}

/// Yang dibutuhkan [Page] dari host browser.
abstract interface class CdpBridge {
  /// Panggil metode CDP. [session] '' = halaman utama.
  Future<Map<String, dynamic>> send(String method,
      [Map<String, dynamic>? params, String session = '']);

  /// Aliran event CDP [method] dari semua sesi.
  Stream<CdpEvent> listen(String method);
}

class PageError implements Exception {
  PageError(this.message);
  final String message;
  @override
  String toString() => 'PageError: $message';
}

class EvalError extends PageError {
  EvalError(super.message);
}

String _short(Object? o, [int n = 120]) {
  final s = '$o';
  return s.length > n ? s.substring(0, n) : s;
}

class Page {
  Page(this.bridge, {Clock? clock, this.evalTimeout = 8.0})
      : clock = clock ?? SystemClock() {
    keyboard = Keyboard._(this);
    mouse = Mouse._(this);
  }

  final CdpBridge bridge;
  final Clock clock;
  final double evalTimeout;
  late final Keyboard keyboard;
  late final Mouse mouse;

  final _subs = <StreamSubscription<CdpEvent>>[];
  bool _attached = false;
  bool _closed = false;

  String _mainId = '';
  String _url = '';
  // frameId -> info (url, name, parent) dari event Page.* sesi mana pun
  final _info = <String, _FrameInfo>{};
  // sesi -> (frameId -> contextId default)
  final _ctx = <String, Map<String, int>>{'': {}};
  // sesi anak -> targetId (= frameId utk target iframe)
  final _sessionTarget = <String, String>{};
  final _frameObjs = <String, Frame>{};
  final _loadWaiters = <Completer<void>>[];
  final _navWaiters = <Completer<void>>[];

  bool get closed => _closed;
  String get url => _url;

  // ------------------------------------------------------------ siklus
  /// Pasang pendengar + aktifkan domain CDP. Aman dipanggil ulang.
  Future<void> attach() async {
    if (_attached) return;
    _attached = true;
    _closed = false;
    void on(String m, void Function(CdpEvent) f) =>
        _subs.add(bridge.listen(m).listen(f, onError: (_) {}));
    on('Runtime.executionContextCreated', _onCtxCreated);
    on('Runtime.executionContextDestroyed', _onCtxDestroyed);
    on('Runtime.executionContextsCleared',
        (e) => _ctx[e.session]?.clear());
    on('Page.frameNavigated', _onFrameNavigated);
    on('Page.navigatedWithinDocument', _onWithinDoc);
    on('Page.frameAttached', (e) {
      final id = '${e.params['frameId'] ?? ''}';
      if (id.isEmpty) return;
      final i = _info.putIfAbsent(id, _FrameInfo.new);
      i.parentId = '${e.params['parentFrameId'] ?? ''}';
    });
    on('Page.frameDetached', (e) {
      final id = '${e.params['frameId'] ?? ''}';
      // 'swap' = pindah ke proses lain (OOPIF), frame-nya tetap ada
      if (e.params['reason'] == 'swap') return;
      _info.remove(id);
      _frameObjs.remove(id);
      for (final m in _ctx.values) {
        m.remove(id);
      }
    });
    on('Page.loadEventFired', (e) {
      if (e.session.isNotEmpty) return;
      for (final c in _loadWaiters) {
        if (!c.isCompleted) c.complete();
      }
      _loadWaiters.clear();
    });
    on('Target.attachedToTarget', _onAttached);
    on('Target.detachedFromTarget', (e) {
      final s = '${e.params['sessionId'] ?? ''}';
      _ctx.remove(s);
      _sessionTarget.remove(s);
    });
    await _enable('');
  }

  Future<void> _enable(String session) async {
    Future<void> tryCall(String m, [Map<String, dynamic>? p]) async {
      try {
        await _send(m, p, session, 10);
      } catch (_) {}
    }

    await tryCall('Page.enable');
    // halaman selalu merasa punya fokus, seperti Playwright di 3.5.x
    // (CRPage selalu memasang ini): klik tombol app di luar webview
    // tidak mem-blur lesson (banner pause, 'user aktif' palsu).
    await tryCall('Emulation.setFocusEmulationEnabled', {'enabled': true});
    // Sesi CDP WebView2 hidup terus, sedangkan Page dibuat baru tiap
    // Mulai. Runtime.enable / setAutoAttach yang SUDAH aktif = no-op:
    // konteks iframe & target anak yang sudah ada tidak diumumkan lagi
    // -> iframe lesson/game tak terlihat (bot diam sampai reload; log
    // 05:36:57 & 07:25:23). Matikan dulu supaya diumumkan ulang.
    await tryCall('Runtime.disable');
    _ctx[session]?.clear();
    await tryCall('Runtime.enable');
    try {
      final tree = await _send('Page.getFrameTree', null, session, 10);
      _walkTree(tree['frameTree'], session.isEmpty);
    } catch (_) {}
    await tryCall('Target.setAutoAttach', {
      'autoAttach': false,
      'waitForDebuggerOnStart': false,
      'flatten': true,
    });
    await tryCall('Target.setAutoAttach', {
      'autoAttach': true,
      'waitForDebuggerOnStart': false,
      'flatten': true,
    });
    if (session.isNotEmpty) await tryCall('Runtime.runIfWaitingForDebugger');
  }

  /// Baca ulang frame/konteks/target anak dari nol (jaring pengaman
  /// saat bot macet: mungkin ada iframe yang tak terlihat).
  Future<void> resync() async {
    if (!_attached || _closed) return;
    await _enable('');
  }

  void _walkTree(dynamic node, bool root) {
    if (node is! Map) return;
    final f = node['frame'];
    if (f is Map) {
      final id = '${f['id'] ?? ''}';
      if (id.isNotEmpty) {
        final i = _info.putIfAbsent(id, _FrameInfo.new);
        i.url = '${f['url'] ?? ''}${f['urlFragment'] ?? ''}';
        i.name = '${f['name'] ?? ''}';
        if (f['parentId'] != null) i.parentId = '${f['parentId']}';
        if (root && f['parentId'] == null) {
          _mainId = id;
          _url = i.url;
        }
      }
    }
    for (final c in (node['childFrames'] as List? ?? const [])) {
      _walkTree(c, false);
    }
  }

  void _onCtxCreated(CdpEvent e) {
    final c = e.params['context'];
    if (c is! Map) return;
    final aux = c['auxData'];
    if (aux is! Map || aux['isDefault'] != true) return;
    final fid = '${aux['frameId'] ?? ''}';
    if (fid.isEmpty) return;
    (_ctx[e.session] ??= {})[fid] = (c['id'] as num).toInt();
  }

  void _onCtxDestroyed(CdpEvent e) {
    final id = (e.params['executionContextId'] as num?)?.toInt();
    final m = _ctx[e.session];
    if (id == null || m == null) return;
    m.removeWhere((_, v) => v == id);
  }

  void _onFrameNavigated(CdpEvent e) {
    final f = e.params['frame'];
    if (f is! Map) return;
    final id = '${f['id'] ?? ''}';
    if (id.isEmpty) return;
    final i = _info.putIfAbsent(id, _FrameInfo.new);
    i.url = '${f['url'] ?? ''}${f['urlFragment'] ?? ''}';
    i.name = '${f['name'] ?? ''}';
    if (f['parentId'] != null) i.parentId = '${f['parentId']}';
    if (e.session.isEmpty && f['parentId'] == null) {
      _mainId = id;
      _url = i.url;
      _wakeNav();
    }
  }

  void _onWithinDoc(CdpEvent e) {
    final id = '${e.params['frameId'] ?? ''}';
    final u = '${e.params['url'] ?? ''}';
    final i = _info[id];
    if (i != null) i.url = u;
    if (e.session.isEmpty && id == _mainId) {
      _url = u;
      _wakeNav();
    }
  }

  void _wakeNav() {
    for (final c in _navWaiters) {
      if (!c.isCompleted) c.complete();
    }
    _navWaiters.clear();
  }

  Future<void> _onAttached(CdpEvent e) async {
    final s = '${e.params['sessionId'] ?? ''}';
    final t = e.params['targetInfo'];
    if (s.isEmpty || t is! Map) return;
    final type = '${t['type'] ?? ''}';
    if (type != 'iframe') {
      // worker dll: lepas saja biar tak menahan apa pun
      try {
        await _send('Runtime.runIfWaitingForDebugger', null, s, 5);
      } catch (_) {}
      return;
    }
    final tid = '${t['targetId'] ?? ''}';
    // sesi lama utk target yang sama = basi (detach-nya bisa telat atau
    // tak pernah datang): buang, supaya evaluate tak nyasar ke sesi mati
    final basi = [
      for (final e in _sessionTarget.entries)
        if (e.value == tid && e.key != s) e.key
    ];
    for (final k in basi) {
      _sessionTarget.remove(k);
      _ctx.remove(k);
    }
    _sessionTarget[s] = tid;
    _ctx[s] ??= {};
    final i = _info.putIfAbsent(_sessionTarget[s]!, _FrameInfo.new);
    if ('${t['url'] ?? ''}'.isNotEmpty) i.url = '${t['url']}';
    await _enable(s);
  }

  /// Lepas pendengar (halaman diganti / bot berhenti).
  Future<void> detach() async {
    for (final s in _subs) {
      await s.cancel();
    }
    _subs.clear();
    _attached = false;
    _wakeNav();
    for (final c in _loadWaiters) {
      if (!c.isCompleted) {
        c.future.ignore();
        c.completeError(PageError('halaman ditutup'));
      }
    }
    _loadWaiters.clear();
  }

  /// Tandai halaman mati (webview dibuang / ganti akun).
  void markClosed() => _closed = true;

  // ------------------------------------------------------------ cdp
  Future<Map<String, dynamic>> _send(String method,
      [Map<String, dynamic>? params,
      String session = '',
      double timeout = 15]) {
    if (_closed) throw PageError('halaman sudah ditutup');
    return bridge.send(method, params, session).timeout(
        Duration(milliseconds: (timeout * 1000).round()),
        onTimeout: () => throw TimeoutException('CDP $method'));
  }

  /// Panggil CDP langsung (halaman utama).
  Future<Map<String, dynamic>> cdp(String method,
          [Map<String, dynamic>? params]) =>
      _send(method, params);

  // ------------------------------------------------------------ frame
  Frame get mainFrame => _frame(_mainId);

  Frame _frame(String id) {
    final f = _frameObjs.putIfAbsent(id, () => Frame._(this, id));
    return f;
  }

  String _ownerSession(String frameId) {
    if (frameId == _mainId || frameId.isEmpty) return '';
    for (final e in _sessionTarget.entries) {
      if (e.value == frameId) return e.key;
    }
    for (final e in _ctx.entries) {
      if (e.value.containsKey(frameId)) return e.key;
    }
    return '';
  }

  /// Semua frame yang bisa dievaluasi (utama dulu). Frame tanpa konteks
  /// JS belum ikut (belum siap dievaluasi).
  List<Frame> get frames {
    final out = <Frame>[mainFrame];
    final seen = <String>{_mainId};
    for (final m in _ctx.values) {
      for (final id in m.keys) {
        if (seen.add(id) && _info.containsKey(id)) out.add(_frame(id));
      }
    }
    for (final t in _sessionTarget.values) {
      if (seen.add(t)) out.add(_frame(t));
    }
    return out;
  }

  // ------------------------------------------------------------ eval
  /// Ekspresi JS ala Playwright: string fungsi dipanggil (dgn [arg]),
  /// selain itu dievaluasi apa adanya.
  static String buildExpression(String js, Object? arg, bool hasArg) {
    final t = js.trim();
    final isFn = RegExp(r'^(async\s+)?(\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>')
            .hasMatch(t) ||
        RegExp(r'^(async\s+)?function\b').hasMatch(t);
    if (!isFn) return t;
    return '($t)(${hasArg ? jsonEncode(arg) : ''})';
  }

  Future<dynamic> _evaluate(Frame fr, String js, Object? arg, bool hasArg,
      double? timeout) async {
    final session = _ownerSession(fr.id);
    final ctx = _ctx[session]?[fr.id];
    final params = <String, dynamic>{
      'expression': buildExpression(js, arg, hasArg),
      'returnByValue': true,
      'awaitPromise': true,
      'userGesture': true,
    };
    // frame utama sesi (atau target iframe) cukup konteks default sesi
    final isRoot = fr.id == _mainId || _sessionTarget[session] == fr.id;
    if (ctx != null && !isRoot) params['contextId'] = ctx;
    if (!isRoot && ctx == null) {
      throw EvalError('frame ${fr.id} belum punya konteks JS');
    }
    final r = await _send('Runtime.evaluate', params, session,
        timeout ?? evalTimeout);
    final ex = r['exceptionDetails'];
    if (ex is Map) {
      final d = ex['exception'];
      throw EvalError(_short(d is Map
          ? (d['description'] ?? d['value'] ?? ex['text'])
          : ex['text']));
    }
    final res = r['result'];
    if (res is! Map) return null;
    if (res.containsKey('value')) return res['value'];
    final un = res['unserializableValue'];
    if (un != null) return double.tryParse('$un');
    return null;
  }

  Future<dynamic> evaluate(String js, [Object? arg]) =>
      mainFrame.evaluate(js, arg);

  /// Renderer masih menjawab? (pengganti _page_alive: evaluate '1'
  /// dgn batas waktu pendek; renderer suspend tidak menjawab).
  Future<bool> alive({double timeout = 2.5}) async {
    try {
      final r = await _evaluate(mainFrame, '1', null, false, timeout);
      return r == 1;
    } catch (_) {
      return false;
    }
  }

  /// location.href asli (page.url bisa basi).
  Future<String> realUrl() async {
    try {
      final u = await evaluate('() => location.href');
      if (u is String && u.isNotEmpty) return u;
    } catch (_) {}
    return _url;
  }

  // ------------------------------------------------------------ navigasi
  Future<void> _waitLoad(Completer<void> c, double timeout) async {
    try {
      await c.future.timeout(Duration(milliseconds: (timeout * 1000).round()),
          onTimeout: () => throw TimeoutException('menunggu halaman'));
    } finally {
      // penunggu yang habis waktu jangan tertinggal di daftar
      _loadWaiters.remove(c);
      _navWaiters.remove(c);
    }
  }

  Future<void> goto(String url, {double timeout = 30}) async {
    final c = Completer<void>();
    _loadWaiters.add(c);
    final r = await _send('Page.navigate', {'url': url}, '', timeout);
    final err = r['errorText'];
    if (err is String && err.isNotEmpty) {
      _loadWaiters.remove(c);
      throw PageError('goto $url: $err');
    }
    if (r['loaderId'] == null) {
      // navigasi dalam dokumen (SPA): tak ada load baru
      _loadWaiters.remove(c);
      _url = url;
      return;
    }
    await _waitLoad(c, timeout);
    await _sesudahMuat();
  }

  /// Dokumen baru = iframe lesson baru (target anak baru). Di WebView2
  /// pengumumannya sering tak sampai sesudah navigasi penuh: mesin buta
  /// ~5 dtk sampai jaring pengaman membaca ulang (log 08:06:28-33).
  /// Baca ulang langsung begitu halaman selesai dimuat.
  Future<void> _sesudahMuat() async {
    try {
      await resync();
    } catch (_) {}
  }

  Future<void> reload({double timeout = 30}) async {
    final c = Completer<void>();
    _loadWaiters.add(c);
    await _send('Page.reload', const {}, '', timeout);
    await _waitLoad(c, timeout);
    await _sesudahMuat();
  }

  Future<void> goBack({double timeout = 30}) async {
    final h = await _send('Page.getNavigationHistory');
    final i = (h['currentIndex'] as num?)?.toInt() ?? 0;
    final es = (h['entries'] as List?) ?? const [];
    if (i <= 0 || i > es.length - 1) return;
    final entry = es[i - 1] as Map;
    final c = Completer<void>();
    _navWaiters.add(c);
    await _send('Page.navigateToHistoryEntry', {'entryId': entry['id']});
    try {
      await _waitLoad(c, timeout);
    } on TimeoutException {
      rethrow;
    }
  }

  Future<String> addInitScript(String source) async {
    final r = await _send(
        'Page.addScriptToEvaluateOnNewDocument', {'source': source});
    return '${r['identifier'] ?? ''}';
  }

  /// Tunggu elemen [selector] tampil di frame utama.
  Future<void> waitForSelector(String selector, {double timeout = 30}) =>
      mainFrame.waitForSelector(selector, timeout: timeout);

  Locator locator(String selector, {String? hasText}) =>
      mainFrame.locator(selector, hasText: hasText);

  // ------------------------------------------------------------ offset
  /// Posisi pojok kiri-atas isi frame [fr] di viewport halaman utama.
  Future<({double x, double y})> frameOffset(Frame fr, [int depth = 0]) async {
    if (fr.id == _mainId || depth > 6) return (x: 0.0, y: 0.0);
    final parent = _info[fr.id]?.parentId ?? '';
    if (parent.isEmpty) return (x: 0.0, y: 0.0);
    final ps = _ownerSession(parent);
    try {
      final owner = await _send('DOM.getFrameOwner', {'frameId': fr.id}, ps);
      final box = await _send('DOM.getBoxModel',
          {'backendNodeId': owner['backendNodeId']}, ps);
      final q = ((box['model'] as Map)['content'] as List)
          .map((e) => (e as num).toDouble())
          .toList();
      var base = (x: 0.0, y: 0.0);
      if (ps.isNotEmpty) {
        final root = _sessionTarget[ps];
        if (root != null) base = await frameOffset(_frame(root), depth + 1);
      }
      return (x: base.x + q[0], y: base.y + q[1]);
    } catch (_) {
      return (x: 0.0, y: 0.0);
    }
  }
}

class _FrameInfo {
  String url = '';
  String name = '';
  String? parentId;
}

class Frame {
  Frame._(this.page, this.id);
  final Page page;
  final String id;

  String get url => page._info[id]?.url ?? '';
  String get name => page._info[id]?.name ?? '';
  bool get isMain => id == page._mainId;

  /// evaluate ala Playwright (string fungsi dipanggil dgn [arg]).
  Future<dynamic> evaluate(String js, [Object? arg]) =>
      page._evaluate(this, js, arg, arg != null, null);

  Future<dynamic> evaluateWith(String js, Object? arg, {double? timeout}) =>
      page._evaluate(this, js, arg, true, timeout);

  Future<void> waitForSelector(String selector, {double timeout = 30}) async {
    final js = '(s) => { const e = document.querySelector(s); if (!e) return false;'
        ' const r = e.getBoundingClientRect();'
        ' return r.width > 0 && r.height > 0'
        ' && getComputedStyle(e).visibility !== "hidden"; }';
    final end = page.clock.now + timeout;
    while (true) {
      try {
        if (await evaluateWith(js, selector) == true) return;
      } catch (_) {}
      if (page.clock.now >= end) {
        throw TimeoutException('waitForSelector $selector');
      }
      await page.clock.sleep(0.1);
    }
  }

  Locator locator(String selector, {String? hasText}) =>
      Locator._(this, [_Step(selector, hasText, null)]);

  @override
  bool operator ==(Object other) =>
      other is Frame && other.id == id && identical(other.page, page);
  @override
  int get hashCode => id.hashCode;
}

class Keyboard {
  Keyboard._(this.page);
  final Page page;
  int _mods = 0;
  final _pressed = <String>{};

  int get modifiers => _mods;

  Future<void> down(String key) async {
    final d = describeKey(key, _mods);
    if (d == null) throw PageError('tombol tidak dikenal: $key');
    final auto = _pressed.contains(d.code);
    _pressed.add(d.code);
    _mods |= modifierBit(d.key);
    await page._send('Input.dispatchKeyEvent', {
      'type': d.text.isNotEmpty ? 'keyDown' : 'rawKeyDown',
      'modifiers': _mods,
      'windowsVirtualKeyCode': d.keyCode,
      'code': d.code,
      'key': d.key,
      'text': d.text,
      'unmodifiedText': d.text,
      'autoRepeat': auto,
      'location': d.location,
      'isKeypad': d.location == 3,
    });
  }

  Future<void> up(String key) async {
    final d = describeKey(key, _mods);
    if (d == null) throw PageError('tombol tidak dikenal: $key');
    _mods &= ~modifierBit(d.key);
    _pressed.remove(d.code);
    await page._send('Input.dispatchKeyEvent', {
      'type': 'keyUp',
      'modifiers': _mods,
      'key': d.key,
      'windowsVirtualKeyCode': d.keyCode,
      'code': d.code,
      'location': d.location,
    });
  }

  /// down -> (jeda) -> up, seperti keyboard.press Playwright.
  Future<void> press(String key, {double delayMs = 0}) async {
    await down(key);
    if (delayMs > 0) await page.clock.sleep(delayMs / 1000);
    await up(key);
  }

  /// Ketik teks; huruf di luar layout US lewat Input.insertText.
  Future<void> type(String text, {double delayMs = 0}) async {
    for (final ch in text.split('')) {
      if (keyDef(ch) != null) {
        await press(ch, delayMs: delayMs);
      } else {
        if (delayMs > 0) await page.clock.sleep(delayMs / 1000);
        await insertText(ch);
      }
    }
  }

  Future<void> insertText(String text) =>
      page._send('Input.insertText', {'text': text});
}

class Mouse {
  Mouse._(this.page);
  final Page page;

  Future<void> click(num x, num y, {int clickCount = 1}) async {
    final p = {'x': x, 'y': y};
    await page._send('Input.dispatchMouseEvent',
        {'type': 'mouseMoved', ...p, 'button': 'none'});
    await page._send('Input.dispatchMouseEvent', {
      'type': 'mousePressed',
      ...p,
      'button': 'left',
      'buttons': 1,
      'clickCount': clickCount,
    });
    await page._send('Input.dispatchMouseEvent', {
      'type': 'mouseReleased',
      ...p,
      'button': 'left',
      'buttons': 0,
      'clickCount': clickCount,
    });
  }
}

class _Step {
  const _Step(this.selector, this.hasText, this.index);
  final String selector;
  final String? hasText;
  final int? index;
  Map<String, dynamic> toJson() =>
      {'s': selector, 't': hasText, 'i': index};
}

/// Locator ala Playwright (subset yang dipakai engine).
class Locator {
  Locator._(this.frame, this._steps);
  final Frame frame;
  final List<_Step> _steps;

  Page get _page => frame.page;

  Locator _with(_Step s) => Locator._(frame, [..._steps, s]);
  Locator _indexed(int i) {
    final last = _steps.last;
    return Locator._(frame, [
      ..._steps.sublist(0, _steps.length - 1),
      _Step(last.selector, last.hasText, i),
    ]);
  }

  Locator get first => _indexed(0);
  Locator nth(int i) => _indexed(i);
  Locator locator(String selector, {String? hasText}) =>
      _with(_Step(selector, hasText, null));

  // JS: kumpulkan elemen sesuai langkah; window.__tbLoc dipakai aksi
  static const _resolve = r'''
const __tbRes = (steps) => {
  let roots = [document];
  for (const st of steps) {
    let els = [];
    for (const r of roots) els.push(...r.querySelectorAll(st.s));
    if (st.t) {
      const w = st.t.replace(/\s+/g, ' ').trim().toLowerCase();
      els = els.filter(e => ((e.innerText || e.textContent || '')
        .replace(/\s+/g, ' ').toLowerCase()).includes(w));
    }
    if (st.i !== null && st.i !== undefined) els = els[st.i] ? [els[st.i]] : [];
    roots = els;
  }
  return roots;
};
const __tbVis = (e) => { const r = e.getBoundingClientRect();
  return r.width > 0 && r.height > 0
    && getComputedStyle(e).visibility !== 'hidden'; };
''';

  Future<dynamic> _run(String body, [Object? extra, double? timeout]) =>
      frame.evaluateWith(
          '(a) => { $_resolve const els = __tbRes(a.steps); $body }',
          {'steps': _steps.map((s) => s.toJson()).toList(), 'x': extra},
          timeout: timeout);

  Future<int> count() async =>
      ((await _run('return els.length;')) as num?)?.toInt() ?? 0;

  Future<bool> isVisible() async =>
      await _run('return !!(els[0] && __tbVis(els[0]));') == true;

  Future<String> innerText({double timeout = 30}) async {
    final end = _page.clock.now + timeout;
    while (true) {
      final r = await _run(
          'return els[0] ? (els[0].innerText || "") : null;', null, timeout);
      if (r is String) return r;
      if (_page.clock.now >= end) throw TimeoutException('innerText');
      await _page.clock.sleep(0.1);
    }
  }

  /// Kotak elemen di koordinat halaman utama (null = tak ada/tak tampil).
  Future<Map<String, double>?> boundingBox({double timeout = 30}) async {
    final r = await _run(
        'const e = els[0]; if (!e) return null; const b = e.getBoundingClientRect();'
        ' if (!(b.width > 0 && b.height > 0)) return null;'
        ' return {x: b.x, y: b.y, w: b.width, h: b.height};',
        null,
        timeout);
    if (r is! Map) return null;
    final off = await _page.frameOffset(frame);
    return {
      'x': (r['x'] as num).toDouble() + off.x,
      'y': (r['y'] as num).toDouble() + off.y,
      'width': (r['w'] as num).toDouble(),
      'height': (r['h'] as num).toDouble(),
    };
  }

  /// Klik mouse CDP sungguhan di tengah elemen (tunggu tampil dulu).
  Future<void> click({double timeout = 30}) async {
    final end = _page.clock.now + timeout;
    while (true) {
      final r = await _run(
          'const e = els[0]; if (!e || !__tbVis(e)) return null;'
          ' let b = e.getBoundingClientRect();'
          ' if (b.bottom < 0 || b.top > innerHeight || b.right < 0 || b.left > innerWidth) {'
          '   e.scrollIntoView({block: "center", inline: "center"});'
          '   b = e.getBoundingClientRect(); }'
          ' return {x: b.x + b.width / 2, y: b.y + b.height / 2};');
      if (r is Map) {
        final off = await _page.frameOffset(frame);
        await _page.mouse.click((r['x'] as num) + off.x, (r['y'] as num) + off.y);
        return;
      }
      if (_page.clock.now >= end) {
        throw TimeoutException('click ${_steps.last.selector}');
      }
      await _page.clock.sleep(0.1);
    }
  }

  /// Pilih opsi <select> berdasar value ATAU label (seperti Playwright).
  Future<void> selectOption(String value, {double timeout = 30}) async {
    final end = _page.clock.now + timeout;
    while (true) {
      final r = await _run(
          'const e = els[0]; if (!e) return null;'
          ' const o = [...e.options].find(o => o.value === a.x || o.label === a.x'
          '   || (o.textContent || "").trim() === a.x);'
          ' if (!o) return false;'
          ' for (const p of e.options) p.selected = (p === o);'
          ' e.dispatchEvent(new Event("input", {bubbles: true}));'
          ' e.dispatchEvent(new Event("change", {bubbles: true}));'
          ' return true;',
          value);
      if (r == true) return;
      if (r == false) throw PageError('opsi "$value" tidak ada');
      if (_page.clock.now >= end) throw TimeoutException('selectOption');
      await _page.clock.sleep(0.1);
    }
  }

  /// Isi input: fokus + pilih semua, lalu Input.insertText (event input
  /// asli, React ikut tahu).
  Future<void> fill(String value, {double timeout = 30}) async {
    final end = _page.clock.now + timeout;
    while (true) {
      final r = await _run(
          'const e = els[0]; if (!e || !__tbVis(e)) return false;'
          ' e.focus(); if (e.select) e.select(); return true;');
      if (r == true) break;
      if (_page.clock.now >= end) throw TimeoutException('fill');
      await _page.clock.sleep(0.1);
    }
    if (value.isEmpty) {
      await _page.keyboard.press('Delete');
    } else {
      await _page.keyboard.insertText(value);
    }
  }
}
