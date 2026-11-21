// Jembatan ke sidecar Python (protokol: docs/architecture/M0-decision.md §4).
// Satu WebSocket. Request -> Future, event & ask -> stream.
import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/web_socket_channel.dart';

class RpcException implements Exception {
  RpcException(this.code, this.message);
  final String code;
  final String message;
  @override
  String toString() => message;
}

class SidecarEvent {
  SidecarEvent(this.name, this.data);
  final String name;
  final dynamic data;
}

class SidecarAsk {
  SidecarAsk(this.id, this.method, this.params, this._reply);
  final int id;
  final String method;
  final Map<String, dynamic> params;
  final void Function(int id, Object? answer) _reply;
  bool _answered = false;
  bool get answered => _answered;

  void answer(Object? result) {
    if (_answered) return;
    _answered = true;
    _reply(id, result);
  }
}

enum LinkState { connecting, online, offline }

/// Yang dibutuhkan UI dari "otak" app: request -> Future, event & ask ->
/// stream. Dua wujud: [Bridge] (sidecar lewat WebSocket: preview/mock) dan
/// NativeBackend (Windows, semua di dalam proses).
abstract interface class Backend {
  Stream<SidecarEvent> get events;
  Stream<SidecarAsk> get asks;
  Stream<LinkState> get link;
  LinkState get state;
  Future<void> connect();
  Future<dynamic> request(String method, [Map<String, dynamic>? params]);
  void close();
}

class Bridge implements Backend {
  Bridge({required this.url, required this.token});

  final Uri url;
  final String token;

  WebSocketChannel? _ch;
  int _seq = 0;
  final _pending = <int, Completer<dynamic>>{};
  final _events = StreamController<SidecarEvent>.broadcast();
  final _asks = StreamController<SidecarAsk>.broadcast();
  final _link = StreamController<LinkState>.broadcast();
  LinkState _state = LinkState.connecting;
  bool _closed = false;
  Map<String, dynamic> hello = const {};

  @override
  Stream<SidecarEvent> get events => _events.stream;
  @override
  Stream<SidecarAsk> get asks => _asks.stream;
  @override
  Stream<LinkState> get link => _link.stream;
  @override
  LinkState get state => _state;

  void _setState(LinkState s) {
    _state = s;
    _link.add(s);
  }

  /// Konek + hello. Kalau putus, coba lagi otomatis (sidecar bisa
  /// lahir belakangan dari UI saat dev).
  @override
  Future<void> connect() async {
    var tunggu = const Duration(milliseconds: 300);
    while (!_closed) {
      _setState(LinkState.connecting);
      try {
        final ch = WebSocketChannel.connect(url);
        await ch.ready;
        _ch = ch;
        final done = Completer<void>();
        ch.stream.listen(_onMessage,
            onDone: () => done.complete(), onError: (_) {
          if (!done.isCompleted) done.complete();
        });
        hello = Map<String, dynamic>.from(
            await request('hello', {'token': token, 'ui': 1}) as Map);
        _setState(LinkState.online);
        tunggu = const Duration(milliseconds: 300);
        await done.future;
      } catch (_) {
        // diam: coba lagi
      }
      _ch = null;
      for (final c in _pending.values) {
        if (!c.isCompleted) {
          c.completeError(RpcException('offline', 'Koneksi ke bot terputus.'));
        }
      }
      _pending.clear();
      if (_closed) break;
      _setState(LinkState.offline);
      await Future<void>.delayed(tunggu);
      if (tunggu < const Duration(seconds: 3)) tunggu *= 2;
    }
  }

  void _send(Map<String, dynamic> obj) {
    final ch = _ch;
    if (ch == null) throw RpcException('offline', 'Belum terhubung ke bot.');
    ch.sink.add(jsonEncode(obj));
  }

  @override
  Future<dynamic> request(String method, [Map<String, dynamic>? params]) {
    final id = ++_seq;
    final c = Completer<dynamic>();
    _pending[id] = c;
    try {
      _send({'id': id, 'm': method, 'p': params ?? const {}});
    } catch (e) {
      _pending.remove(id);
      return Future.error(e);
    }
    return c.future;
  }

  void _onMessage(dynamic raw) {
    final Map<String, dynamic> msg;
    try {
      msg = jsonDecode(raw as String) as Map<String, dynamic>;
    } catch (_) {
      return;
    }
    if (msg.containsKey('id') && msg.containsKey('ok')) {
      final c = _pending.remove(msg['id']);
      if (c == null) return;
      if (msg['ok'] == true) {
        c.complete(msg['r']);
      } else {
        final e = (msg['err'] as Map?) ?? const {};
        c.completeError(RpcException(
            '${e['code'] ?? 'error'}', '${e['msg'] ?? 'Terjadi kesalahan.'}'));
      }
    } else if (msg.containsKey('ev')) {
      _events.add(SidecarEvent(msg['ev'] as String, msg['d']));
    } else if (msg.containsKey('ask')) {
      _asks.add(SidecarAsk(
          msg['ask'] as int,
          msg['m'] as String,
          Map<String, dynamic>.from((msg['p'] as Map?) ?? const {}),
          (id, r) {
            try {
              _send({'ans': id, 'r': r});
            } catch (_) {}
          }));
    }
  }

  @override
  void close() {
    _closed = true;
    _ch?.sink.close();
  }
}
