// Penjaga posisi WebView2 (jendela native) terhadap tata letak Flutter.
//
// - WebSlot: kotak tempat halaman edclub. Posisinya dikirim ke host tiap
//   frame yang berubah (bukan cuma saat build: panel yang beranimasi
//   menggeser slot tanpa membangun ulang WebArea).
// - WebHole: widget Flutter yang harus tampil DI ATAS halaman (popup,
//   panel Rencana). Host melubangi jendela webview di kotak ini, jadi
//   halaman tetap hidup di sekelilingnya (tidak disembunyikan/hitam).
import 'package:flutter/rendering.dart';
import 'package:flutter/scheduler.dart';
import 'package:flutter/widgets.dart';

import '../../web/web_host.dart';

class WebLayer {
  WebLayer._();
  static final instance = WebLayer._();

  /// false = preview/tes (tanpa host native): tidak mengirim apa pun
  bool enabled = false;

  /// sudut lubang (logis) = sudut kartu popup/panel
  double holeRadius = 10;
  WebHost? hostOverride;

  RenderBox? _slot;
  final _holes = <_RenderHole>{};
  bool _hooked = false;
  List<int>? _lastRect;
  List<List<int>>? _lastHoles;

  WebHost get _host => hostOverride ?? webHost;

  void _hook() {
    if (_hooked) return;
    _hooked = true;
    // dipanggil tiap frame SETELAH layout & paint (callback renderer
    // terdaftar lebih dulu), jadi posisi sudah final
    SchedulerBinding.instance.addPersistentFrameCallback((_) => _sync());
  }

  void _attachSlot(RenderBox b) {
    _slot = b;
    _hook();
    SchedulerBinding.instance.scheduleFrame();
  }

  void _detachSlot(RenderBox b) {
    if (_slot == b) _slot = null;
  }

  void _add(_RenderHole h) {
    _holes.add(h);
    _hook();
    SchedulerBinding.instance.scheduleFrame();
  }

  void _remove(_RenderHole h) {
    if (_holes.remove(h)) SchedulerBinding.instance.scheduleFrame();
  }

  double get _dpr {
    final views = WidgetsBinding.instance.platformDispatcher.views;
    return views.isEmpty ? 1.0 : views.first.devicePixelRatio;
  }

  Rect? _global(RenderBox b) {
    if (!b.attached || !b.hasSize) return null;
    final m = b.getTransformTo(null);
    return MatrixUtils.transformRect(m, Offset.zero & b.size);
  }

  void _sync() {
    if (!enabled) return;
    final dpr = _dpr;
    final s = _slot;
    if (s != null) {
      final r = _global(s);
      if (r != null) {
        final v = [
          (r.left * dpr).round(),
          (r.top * dpr).round(),
          (r.width * dpr).round(),
          (r.height * dpr).round(),
        ];
        if (!_eq(v, _lastRect)) {
          _lastRect = v;
          _host.setRect(v[0], v[1], v[2], v[3]).catchError((_) {});
        }
      }
    }
    final hs = <List<int>>[];
    for (final h in _holes) {
      final r = _global(h);
      if (r == null || r.isEmpty) continue;
      // bulatkan keluar: tepi popup tidak boleh tertutup halaman
      final l = (r.left * dpr).floor(), t = (r.top * dpr).floor();
      hs.add([l, t, (r.right * dpr).ceil() - l, (r.bottom * dpr).ceil() - t]);
    }
    hs.sort((a, b) => a[0] != b[0] ? a[0] - b[0] : a[1] - b[1]);
    final last = _lastHoles;
    final same = last != null &&
        last.length == hs.length &&
        [for (var i = 0; i < hs.length; i++) _eq(hs[i], last[i])].every((x) => x);
    if (!same) {
      _lastHoles = hs;
      _host.setHoles(hs, radius: (holeRadius * dpr).round()).catchError((_) {});
    }
  }

  static bool _eq(List<int> a, List<int>? b) {
    if (b == null || a.length != b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (a[i] != b[i]) return false;
    }
    return true;
  }
}

/// Kotak halaman edclub (satu di app).
class WebSlot extends SingleChildRenderObjectWidget {
  const WebSlot({super.key, super.child});
  @override
  RenderObject createRenderObject(BuildContext context) => _RenderSlot();
}

class _RenderSlot extends RenderProxyBox {
  @override
  void attach(PipelineOwner owner) {
    super.attach(owner);
    WebLayer.instance._attachSlot(this);
  }

  @override
  void detach() {
    WebLayer.instance._detachSlot(this);
    super.detach();
  }
}

/// Bungkus widget yang harus tampil di atas halaman native.
class WebHole extends SingleChildRenderObjectWidget {
  const WebHole({super.key, super.child});
  @override
  RenderObject createRenderObject(BuildContext context) => _RenderHole();
}

class _RenderHole extends RenderProxyBox {
  @override
  void attach(PipelineOwner owner) {
    super.attach(owner);
    WebLayer.instance._add(this);
  }

  @override
  void detach() {
    WebLayer.instance._remove(this);
    super.detach();
  }
}
