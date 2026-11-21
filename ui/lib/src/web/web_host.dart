// Jembatan ke host WebView2 di runner C++ (ui/windows/runner/web_host.cpp).
// Satu MethodChannel; event dari C++ datang sebagai panggilan "event".
//
// Semua webview berbagi satu kotak (setRect, piksel fisik relatif ke
// jendela). Tiap webview punya folder data sendiri = jar akun sendiri.
import 'dart:async';
import 'dart:convert';

import 'package:flutter/services.dart';

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
  int _seq = 0;

  Stream<WebEvent> get events => _events.stream;

  Future<dynamic> _onCall(MethodCall call) async {
    if (call.method != 'event') return null;
    final m = (call.arguments as Map).cast<String, dynamic>();
    _events.add(WebEvent((m['id'] as num).toInt(), '${m['type']}', m));
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
    return WebView._(this, id, folder);
  }
}

class WebView {
  WebView._(this.host, this.id, this.folder);
  final WebHost host;
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
  Future<void> focus() => _call('focus');

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
  Future<Map<String, dynamic>> cdp(String method,
      [Map<String, dynamic>? params]) async {
    final r = await _call<String>('cdp', {
      'method': method,
      'params': jsonEncode(params ?? const {}),
    });
    if (r == null || r.isEmpty) return const {};
    return (jsonDecode(r) as Map).cast<String, dynamic>();
  }

  /// Aliran event CDP [event] (mis. 'Page.loadEventFired'); params JSON.
  Stream<Map<String, dynamic>> on(String event) {
    late StreamController<Map<String, dynamic>> c;
    StreamSubscription<WebEvent>? sub;
    c = StreamController<Map<String, dynamic>>(
      onListen: () {
        sub = events
            .where((e) => e.type == 'cdp' && e.data['event'] == event)
            .listen((e) {
          final p = '${e.data['params'] ?? ''}';
          c.add(p.isEmpty
              ? const {}
              : (jsonDecode(p) as Map).cast<String, dynamic>());
        });
        final n = _cdpListeners[event] = (_cdpListeners[event] ?? 0) + 1;
        if (n == 1) {
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
        if (!_disposed) {
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
    await host._call('dispose', {'id': id});
  }
}

/// Host tunggal app (dibuat saat pertama dipakai; hanya Windows).
final webHost = WebHost();
