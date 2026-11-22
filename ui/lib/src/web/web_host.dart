// Jembatan ke host WebView2 di runner C++ (ui/windows/runner/web_host.cpp).
// Satu MethodChannel; event dari C++ datang sebagai panggilan "event".
//
// Semua webview berbagi satu kotak (setRect, piksel fisik relatif ke
// jendela). Tiap webview punya folder data sendiri = jar akun sendiri.
import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'wk_cdp.dart';

class WebHostException implements Exception {
  WebHostException(this.code, this.message);
  final String code;
  final String message;
  @override
  String toString() => 'WebHostException($code): $message';
}

/// Event dari satu webview. type: nav (phase start|done), source, title,
/// newWindow, crash, cdp (event + params JSON).
class WebEvent {
  WebEvent(this.id, this.type, this.data);
  final int id;
  final String type;
  final Map<String, dynamic> data;

  String get url => '${data['url'] ?? ''}';
  @override
  String toString() => 'WebEvent($id, $type, $data)';
}

class WebHost {
  WebHost({MethodChannel? channel})
      : _ch = channel ?? const MethodChannel('typingbot/web_host') {
    _ch.setMethodCallHandler(_onCall);
  }

  final MethodChannel _ch;
  final _events = StreamController<WebEvent>.broadcast();

  /// macOS (WKWebView, tanpa CDP): CDP ditiru di Dart (wk_cdp.dart).
  /// Bisa dipaksa di tes.
  static bool? emulateCdpOverride;
  bool get emulateCdp =>
      emulateCdpOverride ?? (!kIsWeb && defaultTargetPlatform == TargetPlatform.macOS);
  int _seq = 0;
  final _views = <int, WebView>{};

  Stream<WebEvent> get events => _events.stream;

  /// Kapan app sendiri terakhir memberi fokus ke halaman (WebView.focus).
  /// Event 'focus' sesudahnya BUKAN klik user (popup jangan ikut tutup).
  static DateTime selfFocusAt = DateTime(0);
  static bool get recentSelfFocus =>
      DateTime.now().difference(selfFocusAt) < const Duration(milliseconds: 900);

  Future<dynamic> _onCall(MethodCall call) async {
    if (call.method != 'event') return null;
    final m = (call.arguments as Map).cast<String, dynamic>();
    final e = WebEvent((m['id'] as num).toInt(), '${m['type']}', m);
    // peniru CDP (macOS) membaca laporan frame/nav lebih dulu
    _views[e.id]?._wk?.onHostEvent(e.type, m);
    _events.add(e);
    return null;
  }

  Future<T?> _call<T>(String method, [Map<String, Object?>? args]) async {
    try {
      return await _ch.invokeMethod<T>(method, args);
    } on PlatformException catch (e) {
      throw WebHostException(e.code, e.message ?? '');
    }
  }

  /// Versi runtime WebView2 terpasang ('' = belum terpasang).
  Future<String> version() async => await _call<String>('version') ?? '';

  /// Kotak area web (piksel fisik, relatif ke area klien jendela).
  Future<void> setRect(int x, int y, int w, int h) =>
      _call('setRect', {'x': x, 'y': y, 'w': w, 'h': h});

  /// Lubang di atas webview (piksel fisik, ruang sama dgn [setRect]):
  /// di area ini halaman tidak digambar, jadi popup/panel Flutter di
  /// bawahnya kelihatan. Kosong = tanpa lubang.
  Future<void> setHoles(List<List<int>> rects, {int radius = 0}) =>
      _call('setHoles', {'rects': [for (final r in rects) ...r], 'radius': radius});

  /// Pindahkan fokus keyboard dari halaman ke app (popup dibuka).
  Future<void> blur() => _call('blur');

  /// Buat webview baru dgn folder data [folder]. [scripts] dipasang
  /// SEBELUM navigasi pertama (dokumen pertama sudah lahir dgnnya).
  Future<WebView> create({
    required String folder,
    String url = '',
    List<String> scripts = const [],
    bool visible = false,
  }) async {
    final id = ++_seq;
    await _call('create', {
      'id': id,
      'folder': folder,
      'url': url,
      'scripts': scripts,
      'visible': visible,
    });
    final v = WebView._(this, id, folder);
    _views[id] = v;
    return v;
  }
}

class WebView {
  WebView._(this.host, this.id, this.folder) {
    if (host.emulateCdp) {
      _wk = WkCdp(_WkAdapter(this), (method, params) {
        host._events.add(WebEvent(id, 'cdp', {
          'id': id,
          'type': 'cdp',
          'event': method,
          'params': jsonEncode(params),
        }));
      });
    }
  }
  final WebHost host;
  WkCdp? _wk;
  final int id;
  final String folder;
  bool _disposed = false;
  // jumlah pendengar per event CDP (langganan native cukup satu)
  final _cdpListeners = <String, int>{};

  bool get disposed => _disposed;

  Stream<WebEvent> get events => host.events.where((e) => e.id == id);

  Future<T?> _call<T>(String method, [Map<String, Object?>? args]) =>
      host._call<T>(method, {'id': id, ...?args});

  Future<void> setVisible(bool on) => _call('setVisible', {'on': on});
  Future<void> navigate(String url) => _call('navigate', {'url': url});
  Future<void> reload() => _call('reload');
  Future<void> goBack() => _call('goBack');
  Future<void> focus() {
    WebHost.selfFocusAt = DateTime.now();
    return _call('focus');
  }

  Future<({String url, String title})> info() async {
    final m = (await _call<Map>('info')) ?? const {};
    return (url: '${m['url'] ?? ''}', title: '${m['title'] ?? ''}');
  }

  /// Script utk semua dokumen mendatang; hasil = id utk removeScript.
  Future<String> addScript(String js) async =>
      await _call<String>('addScript', {'js': js}) ?? '';
  Future<void> removeScript(String sid) => _call('removeScript', {'sid': sid});

  /// Jalankan JS di dokumen aktif; hasil sudah di-decode dari JSON.
  Future<dynamic> eval(String js) async {
    final r = await _call<String>('eval', {'js': js});
    return r == null || r.isEmpty ? null : jsonDecode(r);
  }

  /// Panggil metode CDP (mis. 'Runtime.evaluate'); hasil = objek JSON.
  /// [session] = sessionId target anak (iframe lintas origin); kosong =
  /// halaman utama.
  Future<Map<String, dynamic>> cdp(String method,
      [Map<String, dynamic>? params, String session = '']) async {
    final wk = _wk;
    if (wk != null) return wk.send(method, params ?? const {});
    final r = await _call<String>('cdp', {
      'method': method,
      'params': jsonEncode(params ?? const {}),
      if (session.isNotEmpty) 'session': session,
    });
    if (r == null || r.isEmpty) return const {};
    return (jsonDecode(r) as Map).cast<String, dynamic>();
  }

  /// Aliran event CDP [event] (mis. 'Page.loadEventFired'); params JSON.
  Stream<Map<String, dynamic>> on(String event) =>
      onSession(event).map((e) => e.params);

  /// Seperti [on] tapi ikut sessionId asal event ('' = halaman utama).
  Stream<({Map<String, dynamic> params, String session})> onSession(
      String event) {
    late StreamController<({Map<String, dynamic> params, String session})> c;
    StreamSubscription<WebEvent>? sub;
    c = StreamController(
      onListen: () {
        sub = events
            .where((e) => e.type == 'cdp' && e.data['event'] == event)
            .listen((e) {
          final p = '${e.data['params'] ?? ''}';
          c.add((
            params: p.isEmpty
                ? const <String, dynamic>{}
                : (jsonDecode(p) as Map).cast<String, dynamic>(),
            session: '${e.data['session'] ?? ''}',
          ));
        });
        final n = _cdpListeners[event] = (_cdpListeners[event] ?? 0) + 1;
        if (n == 1 && _wk == null) {
          _call('cdpSubscribe', {'event': event}).catchError((Object e) {
            c.addError(e);
          });
        }
      },
      onCancel: () async {
        await sub?.cancel();
        final n = (_cdpListeners[event] ?? 1) - 1;
        if (n > 0) {
          _cdpListeners[event] = n;
          return;
        }
        _cdpListeners.remove(event);
        if (!_disposed && _wk == null) {
          await _call('cdpUnsubscribe', {'event': event})
              .catchError((_) => null);
        }
      },
    );
    return c.stream;
  }

  Future<void> dispose() async {
    if (_disposed) return;
    _disposed = true;
    host._views.remove(id);
    await host._call('dispose', {'id': id});
  }
}

class _WkAdapter implements WkHost {
  _WkAdapter(this.view);
  final WebView view;
  @override
  Future<dynamic> call(String method, Map<String, Object?> args) async {
    try {
      return await view._call<dynamic>(method, args);
    } on WebHostException catch (e) {
      if (e.code == 'js') throw WkJsError(e.message);
      rethrow;
    }
  }
}

/// Host tunggal app (dibuat saat pertama dipakai; Windows & macOS).
final webHost = WebHost();
