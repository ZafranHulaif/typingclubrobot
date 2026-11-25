// macOS: WKWebView tidak punya CDP. Kelas ini meniru SUBSET CDP yang
// dipakai mesin bot (page.dart) + native_backend di atas primitif host
// Swift (ui/macos/Runner/WebHost.swift): eval per frame, tombol & mouse
// lewat NSEvent asli (isTrusted), kuki lewat WKHTTPCookieStore.
//
// Frame: user script di SEMUA frame (termasuk iframe lintas origin) lapor
// diri ke host ('frame' hello/bye/hash) dgn id acak per dokumen. Di sini
// laporan itu diubah jadi event CDP biasa (frameNavigated, konteks JS,
// dst), jadi Page tidak perlu tahu bedanya. Semua frame hidup di sesi ''
// (tanpa target anak); induk iframe dianggap frame utama.
import 'dart:async';
import 'dart:convert';

/// Primitif host yang dibutuhkan peniru (dipisah biar bisa dites).
abstract interface class WkHost {
  Future<dynamic> call(String method, Map<String, Object?> args);
}

class WkFrame {
  WkFrame(this.id, this.ctx);
  final String id;
  final int ctx;
  String url = '';
  String name = '';
  bool main = false;
}

class WkCdp {
  WkCdp(this.host, this.emit);

  final WkHost host;

  /// Keluarkan event CDP palsu (method, params) ke pendengar Page.
  final void Function(String method, Map<String, dynamic> params) emit;

  final frames = <String, WkFrame>{};
  String mainId = '';
  int _ctxSeq = 0;
  int _loaderSeq = 0;
  final _owners = <int, String>{}; // backendNodeId palsu -> frameId anak

  // ------------------------------------------------------------ event host
  /// Event dari host Swift utk webview ini (type + data).
  void onHostEvent(String type, Map<String, dynamic> d) {
    if (type == 'frame') {
      _onFrame(d);
    } else if (type == 'net') {
      // laporan 401/403 dari netWatchJs -> bentuk CDP yang dibaca sentinel
      emit('Network.responseReceived', {
        'type': '${d['type'] ?? 'Fetch'}',
        'response': {'status': (d['status'] as num?)?.toInt() ?? 0, 'url': '${d['url'] ?? ''}'},
      });
    } else if (type == 'nav' && d['phase'] == 'done') {
      emit('Page.loadEventFired', {'timestamp': _ts()});
    }
  }

  double _ts() => DateTime.now().millisecondsSinceEpoch / 1000;

  Map<String, dynamic> _frameJson(WkFrame f) => {
        'id': f.id,
        'url': f.url,
        'name': f.name,
        if (!f.main && mainId.isNotEmpty) 'parentId': mainId,
        'loaderId': 'L$_loaderSeq',
      };

  void _onFrame(Map<String, dynamic> d) {
    final fid = '${d['fid'] ?? ''}';
    if (fid.isEmpty) return;
    final phase = '${d['phase'] ?? ''}';
    final url = '${d['url'] ?? ''}';
    if (phase == 'bye') {
      final f = frames.remove(fid);
      if (f == null) return;
      emit('Runtime.executionContextDestroyed', {'executionContextId': f.ctx});
      if (!f.main) emit('Page.frameDetached', {'frameId': fid, 'reason': 'remove'});
      return;
    }
    if (phase == 'hash') {
      final f = frames[fid];
      if (f == null) return;
      f.url = url;
      emit('Page.navigatedWithinDocument', {'frameId': fid, 'url': url});
      return;
    }
    // hello: dokumen baru lahir di frame ini
    var f = frames[fid];
    final baru = f == null;
    f ??= frames[fid] = WkFrame(fid, ++_ctxSeq);
    f
      ..url = url
      ..name = '${d['name'] ?? ''}'
      ..main = d['main'] == true;
    if (f.main && mainId != fid) {
      // dokumen utama baru: semua frame dokumen lama sudah tidak ada
      // (iframe dokumen baru selalu lapor SESUDAH dokumen utamanya)
      final lama = [
        for (final x in frames.values)
          if (x.id != fid) x
      ];
      for (final x in lama) {
        frames.remove(x.id);
      }
      mainId = fid;
      emit('Runtime.executionContextsCleared', {});
    }
    if (!f.main) {
      emit('Page.frameAttached', {'frameId': fid, 'parentFrameId': mainId});
    }
    emit('Page.frameNavigated', {'frame': _frameJson(f), 'type': 'Navigation'});
    if (baru || f.main) _announce(f);
  }

  void _announce(WkFrame f) {
    emit('Runtime.executionContextCreated', {
      'context': {
        'id': f.ctx,
        'origin': _origin(f.url),
        'name': '',
        'auxData': {'isDefault': true, 'frameId': f.id, 'type': 'default'},
      }
    });
  }

  static String _origin(String u) {
    final p = Uri.tryParse(u);
    if (p == null || !p.hasScheme || p.host.isEmpty) return '';
    return p.origin;
  }

  // ------------------------------------------------------------ cdp palsu
  Future<Map<String, dynamic>> send(String method, Map<String, dynamic> p) async {
    switch (method) {
      case 'Runtime.enable':
        // Page membuang daftar konteks sebelum ini: umumkan ulang semua
        for (final f in frames.values.toList()) {
          _announce(f);
        }
        return {};
      case 'Page.getFrameTree':
        return {'frameTree': _tree()};
      case 'Runtime.evaluate':
        return _evaluate(p);
      case 'Page.navigate':
        await host.call('navigate', {'url': '${p['url'] ?? ''}'});
        return {'frameId': mainId, 'loaderId': 'L${++_loaderSeq}'};
      case 'Page.reload':
        await host.call('reload', {});
        return {};
      case 'Page.getNavigationHistory':
        final h = await host.call('history', {});
        final m = h is Map ? h : const {};
        final n = (m['count'] as num?)?.toInt() ?? 1;
        return {
          'currentIndex': (m['index'] as num?)?.toInt() ?? 0,
          'entries': [
            for (var i = 0; i < n; i++) {'id': i, 'url': ''}
          ],
        };
      case 'Page.navigateToHistoryEntry':
        await host.call('goBack', {});
        return {};
      case 'Page.addScriptToEvaluateOnNewDocument':
        final sid = await host.call('addScript', {'js': '${p['source'] ?? ''}'});
        return {'identifier': '${sid ?? ''}'};
      case 'Page.captureScreenshot':
        final b64 = await host.call('snapshot', {});
        return {'data': '${b64 ?? ''}'};
      case 'Input.dispatchKeyEvent':
        await host.call('key', {
          'type': p['type'] == 'keyUp' ? 'up' : 'down',
          'key': '${p['key'] ?? ''}',
          'code': '${p['code'] ?? ''}',
          'text': '${p['text'] ?? ''}',
          'mods': (p['modifiers'] as num?)?.toInt() ?? 0,
          'repeat': p['autoRepeat'] == true,
        });
        return {};
      case 'Input.insertText':
        await host.call('insertText', {'text': '${p['text'] ?? ''}'});
        return {};
      case 'Input.dispatchMouseEvent':
        final t = '${p['type'] ?? ''}';
        await host.call('mouse', {
          'type': t == 'mousePressed'
              ? 'down'
              : t == 'mouseReleased'
                  ? 'up'
                  : 'move',
          'x': (p['x'] as num?)?.toDouble() ?? 0,
          'y': (p['y'] as num?)?.toDouble() ?? 0,
          'count': (p['clickCount'] as num?)?.toInt() ?? 1,
        });
        return {};
      case 'Network.getCookies':
        final out = <Map<String, dynamic>>[];
        final urls = (p['urls'] as List?) ?? const [''];
        for (final u in urls) {
          final r = await host.call('cookies', {'url': '$u'});
          for (final c in (r is List ? r : const [])) {
            if (c is Map) out.add(c.cast<String, dynamic>());
          }
        }
        return {'cookies': out};
      case 'Network.setCookie':
        await host.call('setCookie', {
          for (final k in const [
            'name', 'value', 'domain', 'path', 'secure', 'httpOnly', 'sameSite', 'expires'
          ])
            if (p[k] != null) k: p[k],
        });
        return {'success': true};
      case 'Network.clearBrowserCookies':
        await host.call('clearCookies', {});
        return {};
      case 'Storage.clearDataForOrigin':
        await host.call('clearData', {'origin': '${p['origin'] ?? ''}'});
        return {};
      case 'DOM.getFrameOwner':
        final fid = '${p['frameId'] ?? ''}';
        final node = fid.hashCode & 0x7fffffff;
        _owners[node] = fid;
        return {'backendNodeId': node};
      case 'DOM.getBoxModel':
        return _boxModel(_owners[(p['backendNodeId'] as num?)?.toInt() ?? -1]);
      default:
        // Page.enable, Runtime.disable, Target.setAutoAttach, Network.enable,
        // Emulation.setFocusEmulationEnabled, ...: tidak perlu di WebKit
        return {};
    }
  }

  Map<String, dynamic> _tree() {
    final main = frames[mainId];
    return {
      'frame': main == null ? {'id': mainId, 'url': ''} : _frameJson(main),
      'childFrames': [
        for (final f in frames.values)
          if (!f.main) {'frame': _frameJson(f)}
      ],
    };
  }

  /// Badan fungsi utk callAsyncJavaScript: nilai ekspresi -> teks JSON.
  static String evalBody(String expr) =>
      'const __v = await (\n$expr\n);\n'
      'return __v === undefined ? null : JSON.stringify(__v);';

  Future<Map<String, dynamic>> _evaluate(Map<String, dynamic> p) async {
    final ctx = (p['contextId'] as num?)?.toInt();
    var fid = '';
    if (ctx != null) {
      for (final f in frames.values) {
        if (f.ctx == ctx) fid = f.id;
      }
      if (fid.isEmpty) {
        return _exception('Cannot find context with specified id');
      }
      if (fid == mainId) fid = '';
    }
    final expr = '${p['expression'] ?? ''}';
    final dynamic r;
    try {
      r = await host.call('evalFrame', {'fid': fid, 'body': evalBody(expr)});
    } on WkJsError catch (e) {
      return _exception(e.message);
    }
    if (r == null) return {'result': {'type': 'undefined'}};
    final v = jsonDecode('$r');
    return {
      'result': {'type': v == null ? 'object' : _jsType(v), 'value': v}
    };
  }

  static String _jsType(Object v) => v is String
      ? 'string'
      : v is num
          ? 'number'
          : v is bool
              ? 'boolean'
              : 'object';

  static Map<String, dynamic> _exception(String msg) => {
        'result': {'type': 'object', 'subtype': 'error'},
        'exceptionDetails': {
          'text': 'Uncaught',
          'exception': {'description': msg},
        },
      };

  /// Kotak iframe [fid] di halaman utama: iframe yang origin src-nya sama
  /// dgn dokumen anak (iframe lintas origin tidak bisa dicocokkan lewat id).
  Future<Map<String, dynamic>> _boxModel(String? fid) async {
    final f = fid == null ? null : frames[fid];
    if (f == null) throw WkJsError('frame tidak dikenal');
    final js = '((u) => { const want = new URL(u); let best = null, skor = -1;'
        ' for (const el of document.querySelectorAll("iframe, frame")) {'
        ' let s; try { s = new URL(el.src, location.href); } catch (e) { continue; }'
        ' if (s.origin !== want.origin) continue;'
        ' const r = el.getBoundingClientRect(); if (!r.width || !r.height) continue;'
        ' const n = s.pathname === want.pathname ? 2 : 1;'
        ' if (n > skor) { skor = n; best = el; } }'
        ' if (!best) return null; const r = best.getBoundingClientRect();'
        ' const cs = getComputedStyle(best);'
        ' const x = r.left + (parseFloat(cs.borderLeftWidth) || 0) + (parseFloat(cs.paddingLeft) || 0);'
        ' const y = r.top + (parseFloat(cs.borderTopWidth) || 0) + (parseFloat(cs.paddingTop) || 0);'
        ' return [x, y]; })(${jsonEncode(f.url)})';
    final r = await host.call('evalFrame', {'fid': '', 'body': evalBody(js)});
    final v = r == null ? null : jsonDecode('$r');
    if (v is! List || v.length < 2) throw WkJsError('iframe tidak ketemu');
    final x = (v[0] as num).toDouble(), y = (v[1] as num).toDouble();
    return {
      'model': {
        'content': [x, y, x, y, x, y, x, y]
      }
    };
  }
}

/// Error JS dari host (exception di halaman).
class WkJsError implements Exception {
  WkJsError(this.message);
  final String message;
  @override
  String toString() => 'WkJsError: $message';
}
