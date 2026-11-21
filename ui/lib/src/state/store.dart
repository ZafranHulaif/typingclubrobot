// Satu sumber state UI: snapshot dari sidecar + ask + pesan singkat.
import 'dart:async';

import 'package:material_ui/material_ui.dart';

import '../bridge/bridge.dart';

class Segment {
  Segment(this.from, this.to, this.stars, {this.silver = false});
  int from;
  int to; // 0 = sampai habis
  int stars;
  bool silver;

  factory Segment.fromJson(Map m) => Segment(
        (m['from'] as num).toInt(),
        ((m['to'] as num?) ?? 0).toInt(),
        ((m['stars'] as num?) ?? 5).toInt(),
        silver: m['silver'] == true,
      );
  Map<String, dynamic> toJson() =>
      {'from': from, 'to': to, 'stars': stars, 'silver': silver && stars == 5};
  Segment copy() => Segment(from, to, stars, silver: silver);
  String get label => to == 0 ? '$from+' : (from == to ? '$from' : '$from–$to');
}

class AppStore extends ChangeNotifier {
  AppStore(this.bridge, {this.embedded = false}) {
    _subs.add(bridge.events.listen(_onEvent));
    _subs.add(bridge.asks.listen(_onAsk));
    _subs.add(bridge.link.listen((_) => notifyListeners()));
  }

  final Bridge bridge;
  final bool embedded;
  final _subs = <StreamSubscription>[];

  Map<String, dynamic> snap = {};
  final asks = <SidecarAsk>[];

  /// pesan singkat di slot status (ganti toast: tak ada yg menimpa halaman)
  String? flash;
  bool flashError = false;
  Timer? _flashT;

  bool planOpen = true;

  bool get online => bridge.state == LinkState.online;
  bool get everOnline => snap.isNotEmpty;

  // ---------------------------------------------------- akses snapshot
  Map<String, dynamic> _m(String k) =>
      (snap[k] as Map?)?.cast<String, dynamic>() ?? const {};
  Map<String, dynamic> get app => _m('app');
  Map<String, dynamic> get bot => _m('bot');
  Map<String, dynamic> get level => _m('level');
  Map<String, dynamic> get range => _m('range');
  Map<String, dynamic> get speed => _m('speed');
  Map<String, dynamic> get account => _m('account');
  Map<String, dynamic> get license => _m('license');
  Map<String, dynamic> get update => _m('update');
  Map<String, dynamic> get cover => _m('cover');
  Map<String, dynamic> get plan => _m('plan');

  String get phase => (bot['phase'] as String?) ?? 'idle';
  bool get busy => const {'starting', 'running', 'paused', 'stopping'}
      .contains(phase);
  bool get licensed => license['state'] == null || license['state'] == 'ok';
  int get levelNum => (level['num'] as num?)?.toInt() ?? 0;
  int get wpm => (speed['wpm'] as num?)?.toInt() ?? 400;
  List<int> get tiers =>
      ((speed['tiers'] as List?) ?? const [40, 85, 140, 200, 300, 400])
          .map((e) => (e as num).toInt())
          .toList();
  String speedName(int w) =>
      '${((speed['names'] as Map?) ?? const {})['$w'] ?? ''}';

  List<Map<String, dynamic>> get accounts =>
      ((account['list'] as List?) ?? const [])
          .map((e) => (e as Map).cast<String, dynamic>())
          .toList();

  List<Segment> get segments => ((plan['segments'] as List?) ?? const [])
      .map((e) => Segment.fromJson(e as Map))
      .toList();
  int? get activeSegment => (plan['active'] as num?)?.toInt();
  int get doneInActive => (plan['done_in_active'] as num?)?.toInt() ?? 0;

  // ---------------------------------------------------------- event
  void _onEvent(SidecarEvent e) {
    switch (e.name) {
      case 'snapshot':
        snap = Map<String, dynamic>.from(e.data as Map);
      case 'state':
        (e.data as Map).forEach((k, v) => snap['$k'] = v);
      default:
        return;
    }
    notifyListeners();
  }

  void _onAsk(SidecarAsk a) {
    if (a.method == 'range.pick') {
      // rencana kosong & engine nanya rentang: lanjut dari posisi akun
      a.answer({'mode': 'lanjut'});
      return;
    }
    asks.add(a);
    notifyListeners();
  }

  void answer(SidecarAsk a, Object? r) {
    a.answer(r);
    asks.remove(a);
    notifyListeners();
  }

  // ---------------------------------------------------------- aksi
  void say(String text, {bool error = false}) {
    flash = text;
    flashError = error;
    _flashT?.cancel();
    _flashT = Timer(const Duration(milliseconds: 3500), () {
      flash = null;
      notifyListeners();
    });
    notifyListeners();
  }

  void togglePlan() {
    planOpen = !planOpen;
    notifyListeners();
  }

  /// Panggil sidecar; error ramah tampil di slot status. null = gagal.
  Future<dynamic> call(String m, [Map<String, dynamic>? p]) async {
    try {
      return await bridge.request(m, p);
    } on RpcException catch (e) {
      say(e.message, error: true);
      return null;
    }
  }

  Future<void> toggleRun() async {
    if (busy) {
      await call('bot.stop');
    } else {
      await call('bot.start');
    }
  }

  Future<bool> savePlan(List<Segment> segs) async {
    final r = await call(
        'plan.set', {'segments': segs.map((s) => s.toJson()).toList()});
    return r != null;
  }

  // ---- halaman native vs popup Flutter (airspace)
  int _occluders = 0;

  /// Popup terbuka di atas area web: minta sidecar menyembunyikan
  /// WebView2 (dan menampilkan cuplikan beku) selama popup tampil.
  void occlude(bool on) {
    _occluders += on ? 1 : -1;
    if (_occluders < 0) _occluders = 0;
    if (embedded) {
      bridge.request('web.visible', {'on': _occluders == 0}).ignore();
    }
  }

  @override
  void dispose() {
    for (final s in _subs) {
      s.cancel();
    }
    _flashT?.cancel();
    super.dispose();
  }
}

/// Akses store dari mana saja di bawah pohon widget.
class StoreScope extends InheritedNotifier<AppStore> {
  const StoreScope({super.key, required AppStore store, required super.child})
      : super(notifier: store);

  static AppStore of(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<StoreScope>()!.notifier!;

  static AppStore read(BuildContext context) =>
      context.getInheritedWidgetOfExactType<StoreScope>()!.notifier!;
}
