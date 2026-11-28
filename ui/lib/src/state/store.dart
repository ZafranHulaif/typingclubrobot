// Satu sumber state UI: snapshot dari backend + ask + pesan singkat.
import 'dart:async';

import 'package:material_ui/material_ui.dart';

import '../bridge/bridge.dart';
import 'star_rule.dart';

export 'star_rule.dart';

class Segment {
  Segment(this.from, this.to, int stars, {bool silver = false})
      : rule = StarRule.fixed(codeOf(stars, silver));
  Segment.withRule(this.from, this.to, this.rule);
  int from;
  int to; // 0 = sampai habis
  /// target bintang bagian ini: tetap / pola / acak
  StarRule rule;

  /// target tetap (aturan pola/acak: target tertinggi, utk tampilan lama)
  int get stars => starsOfCode(rule.code);
  bool get silver => rule.type == 'fixed' && silverOfCode(rule.code);

  factory Segment.fromJson(Map m) => Segment.withRule(
        (m['from'] as num).toInt(),
        ((m['to'] as num?) ?? 0).toInt(),
        StarRule.fromJson(m),
      );
  Map<String, dynamic> toJson() => {'from': from, 'to': to, ...rule.toJson()};
  Segment copy() => Segment.withRule(from, to, rule.copy());
  String get label => to == 0 ? '$from+' : (from == to ? '$from' : '$from–$to');

  /// kunci urutan bintang (sama dgn backend)
  String get seqKey => 'p$from';
}

/// Yang sedang dibuka di lembar editor rencana (di samping panel).
class PlanEdit {
  /// ubah bagian ke-[index] yang sudah ada
  PlanEdit.segment(int this.index, Segment this.seg)
      : gap = null,
        games = false;

  /// bagian baru; [gap] = mengisi celah sebelum bagian ke-gap
  PlanEdit.draft(Segment this.seg, {this.gap})
      : index = null,
        games = false;

  /// aturan khusus game
  PlanEdit.games()
      : index = null,
        seg = null,
        gap = null,
        games = true;

  final int? index;
  final Segment? seg;
  final int? gap;
  final bool games;

  bool get isNew => seg != null && index == null;
}

class AppStore extends ChangeNotifier {
  AppStore(this.bridge, {this.embedded = false}) {
    _subs.add(bridge.events.listen(_onEvent));
    _subs.add(bridge.asks.listen(_onAsk));
    _subs.add(bridge.link.listen((_) => notifyListeners()));
  }

  final Backend bridge;
  final bool embedded;
  final _subs = <StreamSubscription>[];

  Map<String, dynamic> snap = {};
  final asks = <SidecarAsk>[];

  /// pesan singkat di slot status (ganti toast: tak ada yg menimpa halaman)
  String? flash;
  bool flashError = false;
  Timer? _flashT;

  bool planOpen = false;

  /// lembar editor rencana yang terbuka (null = tertutup)
  PlanEdit? edit;

  /// level terakhir kursus (Typing Jungle)
  static const lastLevel = 685;

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
  Map<String, dynamic> get sound => _m('sound');
  bool get muted => sound['muted'] == true;

  String get phase => (bot['phase'] as String?) ?? 'idle';
  bool get busy => const {'waiting', 'starting', 'running', 'paused', 'stopping'}
      .contains(phase);

  /// level terbuka tertinggi akun aktif (0 = belum terbaca dari daftar)
  int get unlocked => (range['unlocked'] as num?)?.toInt() ?? 0;

  /// 'free' (tanpa rencana) / 'plan'
  String get mode => (bot['mode'] as String?) ?? 'free';
  bool get planRunning => busy && mode == 'plan';
  Map<String, dynamic> get free => _m('free');
  int get freeStars => (free['stars'] as num?)?.toInt() ?? 5;
  bool get freeSilver => free['silver'] == true;
  /// mode tanpa rencana: 'stars' (pilih bintang) / 'manual' (atur
  /// kecepatan & akurasi sendiri, bintang = perkiraan)
  bool get freeManual => free['mode'] == 'manual';

  /// target platinum: tanpa salah tapi santai (sedikit di atas kecepatan
  /// minimal platinum), bukan secepatnya
  bool get platinumRelaxed => free['plat'] == 'relaxed';
  bool get licensed => license['state'] == null || license['state'] == 'ok';
  int get levelNum => (level['num'] as num?)?.toInt() ?? 0;
  int get wpm => (speed['wpm'] as num?)?.toInt() ?? 400;
  /// akurasi pilihan mode Manual (%)
  int get acc => (speed['acc'] as num?)?.toInt() ?? 100;
  /// dial kecepatan terkunci (mode bintang / rencana jalan)
  bool get speedLocked => speed['locked'] != false;
  /// target bintang yang mengunci kecepatan (0 = platinum)
  int get autoStars => (speed['auto'] as num?)?.toInt() ?? 0;
  int get autoWpm => (speed['auto_wpm'] as num?)?.toInt() ?? 0;
  /// perkiraan bintang mode Manual di level ini (null = belum terbaca)
  Map<String, dynamic>? get guess => (speed['guess'] as Map?)?.cast<String, dynamic>();
  /// catatan perkiraan: batas yang dinaikkan / alasan tanpa perkiraan
  String get guessNote => (speed['note'] as String?) ?? '';
  int get guessLevel => (speed['level'] as num?)?.toInt() ?? 0;
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
  /// selama jalan: bagian yg mulai <= ini terkunci (sedang/segera dikerjakan)
  int? get lockUntil => busy ? (plan['lock_until'] as num?)?.toInt() : null;
  bool locked(Segment sg) =>
      planRunning && lockUntil != null && sg.from <= lockUntil!;
  int get doneInActive => (plan['done_in_active'] as num?)?.toInt() ?? 0;

  // ---------------------------------------------------------- event
  void _onEvent(SidecarEvent e) {
    switch (e.name) {
      case 'snapshot':
        snap = Map<String, dynamic>.from(e.data as Map);
      case 'state':
        final m = e.data as Map;
        // lisensi akun baru disetujui (dari menunggu): kabari
        final lic = m['license'];
        if (lic is Map && lic['approved'] == true && license['state'] == 'pending') {
          say('Akun sudah aktif. Tekan Mulai.');
        }
        m.forEach((k, v) => snap['$k'] = v);
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
    if (!planOpen) edit = null;
    notifyListeners();
  }

  void openEdit(PlanEdit? e) {
    edit = e;
    notifyListeners();
  }

  // ---------------------------------------------- aturan & urutan bintang
  Map<String, dynamic> get games => _m('games');
  StarRule gameRule(String kind) =>
      StarRule.fromJson((games[kind] as Map?) ?? const {'rule': 'follow'});
  bool get anyGameRule => gameKinds.any((k) => !gameRule(k).follow);

  /// kunci akun utk benih acak (sama dgn backend)
  String get seqAcct => (plan['acct'] as String?) ?? '';

  /// urutan tersimpan akun aktif: {tanda aturan: {n, lv: {level: giliran}}}
  Map? get seq => plan['seq'] as Map?;

  /// level selesai akun aktif: {level: {c: target, e: bintang asli}}
  Map? get done => plan['done'] as Map?;

  /// giliran yang sudah terpakai utk aturan bertanda [sig]
  int usedFor(String sig) => seqState(seq, sig).n;

  /// jenis level kursus yang sudah dikenal: {'377': 'star' / 'free' /
  /// 'balloon' / 'monster'}
  Map get catalog => (snap['catalog'] as Map?) ?? const {};

  /// aturan khusus game yang aktif (bukan 'ikut rencana')
  Map<String, StarRule> get gameRules => {
        for (final k in gameKinds)
          if (!gameRule(k).follow) k: gameRule(k),
      };

  /// target level yang sedang dikerjakan (pola/acak/game): {level, code, kind}
  Map<String, dynamic>? get curTarget => (plan['cur'] as Map?)?.cast<String, dynamic>();

  Future<bool> saveGames(Map<String, StarRule> rules) async {
    final r = await call('games.set', {for (final e in rules.entries) e.key: e.value.toJson()});
    if (r != null && planRunning) {
      say('Aturan game berlaku mulai game berikutnya.');
    }
    return r != null;
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

  /// Tombol atas: Mulai tanpa rencana (level dipilih di halaman) / Stop.
  Future<void> toggleRun() async {
    if (busy) {
      await call('bot.stop');
    } else {
      await call('bot.start', {'mode': 'free'});
    }
  }

  /// Lembar editor yang terbuka: simpan perubahannya (true = tersimpan /
  /// tak ada perubahan, false = isian salah, pesan sudah tampil).
  Future<bool> Function()? saveDraft;

  Future<void> startPlan() async {
    if (busy) return;
    // editor masih terbuka dgn perubahan belum disimpan: simpan dulu,
    // supaya yang jalan = yang terlihat (laporan 28 Nov)
    final d = saveDraft;
    if (d != null && !await d()) return;
    await call('bot.start', {'mode': 'plan'});
  }

  Future<void> resume() async {
    await call('bot.resume');
  }

  Future<void> setFreeStars(int stars, bool silver) async {
    final r = await call('free.set', {'stars': stars, 'silver': silver});
    // sedang mengetik tanpa rencana: lesson ini tetap, ganti di level berikutnya
    if (r != null && phase == 'running' && !planRunning) {
      say('Target bintang baru berlaku mulai level berikutnya.');
    }
  }

  /// Platinum secepatnya <-> santai (berlaku di bebas & rencana).
  Future<void> setPlatinumRelaxed(bool on) async {
    final r = await call('free.set', {'plat': on ? 'relaxed' : 'fast'});
    if (r != null && phase == 'running') {
      say('Kecepatan platinum baru berlaku mulai level berikutnya.');
    }
  }

  /// Ganti mode tanpa rencana: bintang <-> manual.
  Future<void> setFreeMode(bool manual) async {
    final r = await call('free.set', {'mode': manual ? 'manual' : 'stars'});
    if (r != null && phase == 'running' && !planRunning) {
      say('Mode baru berlaku penuh mulai level berikutnya.');
    }
  }

  Future<bool> savePlan(List<Segment> segs) async {
    final r = await call(
        'plan.set', {'segments': segs.map((s) => s.toJson()).toList()});
    return r != null;
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
