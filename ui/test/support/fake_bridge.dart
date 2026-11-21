// Bridge CDP palsu: catat semua panggilan, jawab lewat handler per metode,
// dan bisa memancarkan event seolah dari WebView2.
import 'dart:async';

import 'package:typingbot/src/engine/page.dart';

typedef CdpHandler = FutureOr<Map<String, dynamic>> Function(
    Map<String, dynamic> params, String session);

class SentCall {
  SentCall(this.method, this.params, this.session);
  final String method;
  final Map<String, dynamic> params;
  final String session;
  @override
  String toString() => '$method${session.isEmpty ? '' : '@$session'} $params';
}

class FakeBridge implements CdpBridge {
  final sent = <SentCall>[];
  final handlers = <String, CdpHandler>{};
  final _ctl = StreamController<CdpEvent>.broadcast(sync: true);

  @override
  Future<Map<String, dynamic>> send(String method,
      [Map<String, dynamic>? params, String session = '']) async {
    final p = params ?? const <String, dynamic>{};
    sent.add(SentCall(method, p, session));
    final h = handlers[method];
    if (h == null) return const {};
    return await h(p, session);
  }

  @override
  Stream<CdpEvent> listen(String method) =>
      _ctl.stream.where((e) => e.method == method);

  void emit(String method, Map<String, dynamic> params, [String session = '']) =>
      _ctl.add(CdpEvent(method, params, session));

  Iterable<SentCall> named(String m) => sent.where((c) => c.method == m);
}
