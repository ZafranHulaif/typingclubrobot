// Satu sumber state UI: snapshot dari sidecar + log + ask + navigasi panel.
import 'dart:async';
import 'dart:collection';

import 'package:material_ui/material_ui.dart';

import '../bridge/bridge.dart';

enum PanelPage { home, range, accounts, report, settings, update, license }

class LogLine {
  LogLine(this.time, this.text, this.raw, this.level);
  final DateTime time;
  final String text;
  final String raw;
  final String level;
}

class LevelResult {
  LevelResult(this.level, this.stars, this.wpm);
  final int level;
  final int stars;
  final int wpm;
}

class Toast {
  Toast(this.text, {this.error = false}) : id = _n++;
  static int _n = 0;
  final int id;
  final String text;
  final bool error;
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
  final logs = ListQueue<LogLine>();
  final results = ListQueue<LevelResult>();
  final asks = <SidecarAsk>[];
  Toast? toast;
  PanelPage page = PanelPage.home;

  /// ask range.pick yang sedang dijawab lewat halaman Rentang
  SidecarAsk? rangeAsk;

  /// pilihan rentang utk Mulai berikutnya: lanjut | custom | halaman
  Map<String, dynamic> rangeChoice = {'mode': 'lanjut'};

  void setRange(Map<String, dynamic> r) {
    rangeChoice = r;
    notifyListeners();
  }

  Future<void> start() async {
    await call('bot.start', {'range': rangeChoice});
  }

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
  Map<String, dynamic> get activity => _m('activity');
  Map<String, dynamic> get account => _m('account');
  Map<String, dynamic> get license => _m('license');
  Map<String, dynamic> get update => _m('update');
  Map<String, dynamic> get cover => _m('cover');
  Map<String, dynamic> get stats => _m('stats');
  bool get hotkeysOn => _m('hotkeys')['on'] != false;

  String get phase => (bot['phase'] as String?) ?? 'idle';
  bool get busy => const {'starting', 'running', 'paused', 'stopping'}
      .contains(phase);
  int get wpm => (speed['wpm'] as num?)?.toInt() ?? 400;
  List<int> get tiers =>
      ((speed['tiers'] as List?) ?? const [40, 85, 140, 200, 300, 400])
          .map((e) => (e as num).toInt())
          .toList();
  String speedName(int w) {
    final names = (speed['names'] as Map?) ?? const {};
    return '${names['$w'] ?? ''}';
  }

  List<Map<String, dynamic>> get accounts =>
      ((account['list'] as List?) ?? const [])
          .map((e) => (e as Map).cast<String, dynamic>())
          .toList();

  // ---------------------------------------------------------- event
  void _onEvent(SidecarEvent e) {
    switch (e.name) {
      case 'snapshot':
        snap = Map<String, dynamic>.from(e.data as Map);
      case 'state':
        (e.data as Map).forEach((k, v) => snap['$k'] = v);
      case 'log':
        final d = e.data as Map;
        final friendly = d['friendly'] as String?;
        if (friendly == null || friendly.isEmpty) return;
        logs.addFirst(LogLine(
            DateTime.fromMillisecondsSinceEpoch(
                ((d['t'] as num) * 1000).round()),
            friendly,
            '${d['raw']}',
            '${d['level'] ?? 'info'}'));
        while (logs.length > 200) {
          logs.removeLast();
        }
      case 'level.result':
        final d = e.data as Map;
        results.addFirst(LevelResult((d['level'] as num).toInt(),
            (d['stars'] as num).toInt(), (d['wpm'] as num).toInt()));
        while (results.length > 60) {
          results.removeLast();
        }
      default:
        return;
    }
    notifyListeners();
  }

  void _onAsk(SidecarAsk a) {
    if (a.method == 'range.pick') {
      rangeAsk = a;
      page = PanelPage.range;
    } else {
      asks.add(a);
      page = PanelPage.home;
    }
    notifyListeners();
  }

  void answer(SidecarAsk a, Object? r) {
    a.answer(r);
    asks.remove(a);
    if (rangeAsk == a) rangeAsk = null;
    notifyListeners();
  }

  // ---------------------------------------------------------- aksi
  void go(PanelPage p) {
    if (page == p) return;
    page = p;
    notifyListeners();
  }

  void showToast(String text, {bool error = false}) {
    final t = Toast(text, error: error);
    toast = t;
    notifyListeners();
    Future<void>.delayed(const Duration(milliseconds: 3200), () {
      if (toast?.id == t.id) {
        toast = null;
        notifyListeners();
      }
    });
  }

  /// Panggil sidecar; error ramah langsung jadi toast. Return null kalau gagal.
  Future<dynamic> call(String m, [Map<String, dynamic>? p]) async {
    try {
      return await bridge.request(m, p);
    } on RpcException catch (e) {
      showToast(e.message, error: true);
      return null;
    }
  }

  @override
  void dispose() {
    for (final s in _subs) {
      s.cancel();
    }
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
