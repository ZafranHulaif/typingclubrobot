// Backend di dalam proses (Windows): pengganti sidecar Python.
// N1: halaman edclub di WebView2 native, login Google di dalam app,
// ganti/tambah/keluar akun. N3: mesin bot (lib/src/engine) - Mulai/Stop,
// rencana, kecepatan, kemajuan level. Lisensi & update (N4) menyusul.
//
// Bicara dgn UI lewat protokol yang sama dgn sidecar (snapshot/state +
// request + ask), jadi UI tidak tahu bedanya. Pemetaan state mesin ->
// snapshot meniru sidecar/engine_backend.py (_poller 10 Hz).
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import '../bridge/bridge.dart';
import '../engine/clock.dart';
import '../engine/engine.dart';
import '../engine/level_map.dart';
import '../engine/page.dart';
import '../web/js_init.dart';
import '../web/web_host.dart';
import 'accounts.dart';
import 'view_bridge.dart';

const homeUrl = 'https://www.edclub.com/student/course/3';
const signinUrl = 'https://www.edclub.com/signin';

/// Init script utk tiap dokumen (urutan sama dgn pengawas 3.5.x).
const initScripts = [
  noPopupJs,
  durFixJs,
  loginRedirectJs,
  oauthRelayPageJs,
  oauthMarkerJs,
];

/// Bagian rencana yang mulai <= level kini + ini terkunci saat jalan.
const lockDistance = 2;

class NativeBackend implements Backend {
  NativeBackend({
    required String version,
    WebHost? host,
    AccountStore? accounts,
    this.revealTimeout = const Duration(seconds: 20),
    this.pollInterval = const Duration(milliseconds: 100),
    CdpBridge Function(WebView view)? bridgeFor,
    this.clock,
  })  : host = host ?? webHost,
        accounts = accounts ?? AccountStore(AccountStore.defaultBase()),
        _bridgeFor = bridgeFor ?? WebViewBridge.new {
    _settings = _loadSettings();
    final wpm = ((_settings['speed'] as num?) ?? 400).toInt().clamp(40, 400);
    _snap = {
      'app': {'version': version, 'platform': 'windows', 'mode': 'native'},
      'bot': {'phase': 'idle', 'needs_login': false},
      'level': <String, dynamic>{},
      'range': <String, dynamic>{},
      'speed': {'wpm': wpm},
      'account': {'active': '', 'list': <Map<String, dynamic>>[]},
      // lisensi asli menyusul (N4); versi uji tidak dikunci
      'license': {'state': 'ok'},
      'update': <String, dynamic>{},
      'cover': {'visible': true, 'text': 'Menyiapkan edclub...'},
      'plan': {
        'segments': [
          for (final s in (_settings['plan'] as List? ?? const []))
            if (s is Map) Map<String, dynamic>.from(s)
        ],
      },
      'web': {'url': '', 'title': ''},
    };
  }

  final WebHost host;
  final AccountStore accounts;
  final Duration revealTimeout;
  final Duration pollInterval;
  final CdpBridge Function(WebView view) _bridgeFor;

  /// jam mesin (tes: jam palsu); null = jam sistem
  final Clock? clock;

  late final Map<String, Map<String, dynamic>> _snap;
  late Map<String, dynamic> _settings;
  final _events = StreamController<SidecarEvent>.broadcast();
  final _asks = StreamController<SidecarAsk>.broadcast();
  final _link = StreamController<LinkState>.broadcast();
  LinkState _state = LinkState.connecting;

  WebView? _view;
  StreamSubscription<WebEvent>? _viewSub;
  Timer? _revealT;
  bool _occluded = false;
  bool _switching = false;
  bool _urlNeedsLogin = false;

  // ---- mesin bot
  LevelMap? _levels;
  Engine? _engine;
  Page? _page;
  Future<void>? _run;
  StreamSubscription<CdpEvent>? _netSub;
  Timer? _poll;
  double _loginNavT = 0;
  int _askSeq = 0;
  final _asking = <String>{};

  WebView? get view => _view;
  Engine? get engine => _engine;
  bool get running => _run != null;

  @override
  Stream<SidecarEvent> get events => _events.stream;
  @override
  Stream<SidecarAsk> get asks => _asks.stream;
  @override
  Stream<LinkState> get link => _link.stream;
  @override
  LinkState get state => _state;

  bool get _coverOn => _snap['cover']!['visible'] == true;
  String get _base => accounts.base;

  // ------------------------------------------------------------ state
  void _set(String key, Map<String, dynamic> fields) {
    final cur = _snap[key]!;
    var changed = false;
    for (final e in fields.entries) {
      if (!_same(cur[e.key], e.value)) {
        changed = true;
        break;
      }
    }
    if (!changed && cur.isNotEmpty) return;
    _snap[key] = {...cur, ...fields};
    _events.add(SidecarEvent('state', {key: _snap[key]}));
  }

  static bool _same(Object? a, Object? b) {
    if (a is List || a is Map || b is List || b is Map) {
      return jsonEncode(a) == jsonEncode(b);
    }
    return a == b;
  }

  void _refreshAccounts() {
    final a = accounts.active();
    _set('account', {
      'active': a ?? '',
      'list': [
        for (final n in accounts.list()) {'name': n}
      ],
    });
  }

  void _cover(String? text) {
    _set('cover', text == null ? {'visible': false} : {'visible': true, 'text': text});
    _applyVisible();
  }

  void _applyVisible() {
    final v = _view;
    if (v == null || v.disposed) return;
    v.setVisible(!_coverOn && !_occluded).catchError((_) {});
  }

  // ------------------------------------------------------------ settings
  String get _settingsPath => '$_base${Platform.pathSeparator}typingbot_settings.json';

  Map<String, dynamic> _loadSettings() {
    try {
      final m = jsonDecode(File(_settingsPath).readAsStringSync());
      if (m is Map) return Map<String, dynamic>.from(m);
    } catch (_) {}
    return {};
  }

  void _saveSettings(Map<String, dynamic> kv) {
    _settings.addAll(kv);
    try {
      Directory(_base).createSync(recursive: true);
      final tmp = File('$_settingsPath.tmp');
      tmp.writeAsStringSync(const JsonEncoder.withIndent(' ').convert(_settings));
      tmp.renameSync(_settingsPath);
    } catch (_) {}
  }

  // ------------------------------------------------------------ log
  String get _logPath => '$_base${Platform.pathSeparator}bot.log';

  void _log(String line) {
    final t = DateTime.now();
    String two(int n) => n.toString().padLeft(2, '0');
    final stamp = '${two(t.hour)}:${two(t.minute)}:${two(t.second)}';
    try {
      Directory(_base).createSync(recursive: true);
      File(_logPath).writeAsStringSync('$stamp $line\n', mode: FileMode.append);
    } catch (_) {}
    _events.add(SidecarEvent('log', {
      't': t.millisecondsSinceEpoch / 1000,
      'raw': line.length > 400 ? line.substring(0, 400) : line,
      'friendly': null,
      'level': 'info',
    }));
  }

  /// bot.log jangan tumbuh tanpa batas (> 4 MB -> sisakan 1 MB terakhir).
  void _trimLog() {
    try {
      final f = File(_logPath);
      if (!f.existsSync() || f.lengthSync() < 4 << 20) return;
      final s = f.readAsStringSync();
      f.writeAsStringSync(s.substring(s.length - (1 << 20)));
    } catch (_) {}
  }

  // ------------------------------------------------------------ boot
  @override
  Future<void> connect() async {
    _events.add(SidecarEvent('snapshot', {..._snap}));
    _state = LinkState.online;
    _link.add(_state);
    _trimLog();
    _refreshAccounts();
    _levels = LevelMap(_base)..muatPosisi();
    _set('range', {
      'position': _levels!.posisi,
      'total': _levels!.map.length,
      'mapped': _levels!.map.length,
    });
    final ver = await host.version().catchError((_) => '');
    if (ver.isEmpty) {
      _cover('WebView2 belum terpasang di komputer ini. Pasang dulu '
          '"Microsoft Edge WebView2 Runtime", lalu buka lagi TypingBot.');
      return;
    }
    await _open(accounts.active());
  }

  /// Buka webview utk akun [name] (null = profil awal). Webview lama
  /// dibuang SETELAH yang baru siap (tak ada layar kosong di tengah).
  Future<void> _open(String? name, {String url = homeUrl}) async {
    _cover(name == null ? 'Menyiapkan edclub...' : 'Membuka akun $name...');
    final old = _view;
    await _viewSub?.cancel();
    _viewSub = null;
    _revealT?.cancel();
    WebView v;
    try {
      v = await host.create(
          folder: accounts.folderFor(name), url: url, scripts: initScripts);
    } on WebHostException catch (e) {
      _cover('Halaman edclub gagal dibuka (${e.code}). Tutup lalu buka '
          'lagi TypingBot ya.');
      return;
    }
    _view = v;
    _viewSub = v.events.listen(_onWeb);
    // jaga-jaga: halaman lambat / gagal = tetap tampilkan
    _revealT = Timer(revealTimeout, () => _cover(null));
    if (old != null) await old.dispose().catchError((_) {});
  }

  void _onWeb(WebEvent e) {
    switch (e.type) {
      case 'nav':
        if (e.data['phase'] == 'done' && _coverOn) {
          _revealT?.cancel();
          _cover(null);
        }
        _web(e.url);
      case 'source':
        _web(e.url);
      case 'title':
        _set('web', {'title': '${e.data['title'] ?? ''}'});
      case 'crash':
        // proses halaman mati: muat ulang sekali, cover selama itu
        _cover('Halaman macet, memuat ulang...');
        _view?.reload().catchError((_) {});
    }
  }

  void _web(String url) {
    if (url.isEmpty) return;
    _set('web', {'url': url});
    final u = Uri.tryParse(url);
    _urlNeedsLogin =
        u != null && u.host.contains('edclub') && u.path.contains('/signin');
    _set('bot', {'needs_login': _urlNeedsLogin || (_engine?.st.needsLogin ?? false) && running});
  }

  // ------------------------------------------------------------ request
  @override
  Future<dynamic> request(String method, [Map<String, dynamic>? params]) async {
    final p = params ?? const <String, dynamic>{};
    switch (method) {
      case 'hello':
        return {'mode': 'native'};
      case 'acct.list':
        _refreshAccounts();
        return _snap['account'];
      case 'acct.switch':
        final name = '${p['name'] ?? ''}'.trim();
        if (name.isEmpty) throw RpcException('bad_input', 'Pilih akunnya dulu.');
        if (name == accounts.active() && _view != null) return _snap['account'];
        _notWhileRunning();
        return _guard(() async {
          accounts.setActive(name);
          _refreshAccounts();
          await _open(name);
          return _snap['account'];
        });
      case 'acct.add':
        _notWhileRunning();
        return _guard(() async {
          final name = accounts.newName();
          accounts.setActive(name);
          await _open(name, url: signinUrl);
          _refreshAccounts();
          return _snap['account'];
        });
      case 'acct.logout':
        _notWhileRunning();
        return _logout();
      case 'login.open':
        final url = p['kind'] == 'sekolah' ? loginUrlSchool : signinUrl;
        await _view?.navigate(url);
        return true;
      case 'web.visible':
        _occluded = p['on'] != true;
        _applyVisible();
        return true;
      case 'speed.set':
        final w = ((p['wpm'] as num?)?.toInt() ?? 400).clamp(40, 400);
        _engine?.st.speedWpm = w;
        _set('speed', {'wpm': w});
        if (p['save'] != false) _saveSettings({'speed': w});
        return {'wpm': w};
      case 'plan.set':
        return _planSet(p['segments']);
      case 'settings.get':
        return Map<String, dynamic>.from(_settings);
      case 'settings.set':
        _saveSettings(Map<String, dynamic>.from(p));
        return Map<String, dynamic>.from(_settings);
      case 'bot.start':
        return _start(p['range']);
      case 'bot.stop':
        _stop();
        return {};
      case 'bot.recover':
        _engine?.st.askRecovery = true;
        return {};
      case 'levels.build_map':
        _engine?.st.askBuildMap = true;
        return {};
      case 'range.get':
        return _snap['range'];
      case 'log.tail':
        return {'lines': _tail(((p['n'] as num?) ?? 100).toInt())};
      default:
        throw RpcException('later', 'Bagian ini belum ada di versi uji ini.');
    }
  }

  void _notWhileRunning() {
    if (running) {
      throw RpcException('busy', 'Hentikan bot dulu sebelum ganti akun.');
    }
  }

  List<String> _tail(int n) {
    try {
      final ls = File(_logPath).readAsLinesSync();
      return ls.sublist(ls.length > n ? ls.length - n : 0);
    } catch (_) {
      return const [];
    }
  }

  Future<dynamic> _guard(Future<dynamic> Function() f) async {
    if (_switching) {
      throw RpcException('busy', 'Sebentar, masih membuka akun.');
    }
    _switching = true;
    try {
      return await f();
    } finally {
      _switching = false;
    }
  }

  /// Keluar dari akun aktif: hapus kuki + penyimpanan edclub di jar ini
  /// (termasuk tiket tb_lt, kalau tidak relay masuk sendiri lagi).
  Future<dynamic> _logout() async {
    final v = _view;
    if (v == null) return false;
    _cover('Keluar dari akun...');
    try {
      await v.cdp('Network.clearBrowserCookies');
      for (final o in const [
        'https://www.edclub.com',
        'https://api.edclub.com',
        'https://www.typingclub.com',
        'https://s.typingclub.com',
      ]) {
        await v.cdp('Storage.clearDataForOrigin', {
          'origin': o,
          'storageTypes': 'local_storage,session_storage,indexeddb,cache_storage',
        }).catchError((_) => const <String, dynamic>{});
      }
      await v.navigate(signinUrl);
    } on WebHostException {
      _cover(null);
      throw RpcException('logout_failed', 'Gagal keluar, coba lagi ya.');
    }
    _set('bot', {'needs_login': true});
    _revealT?.cancel();
    _revealT = Timer(revealTimeout, () => _cover(null));
    return true;
  }

  // ------------------------------------------------------------ rencana
  List<Map<String, dynamic>> get _segments =>
      [for (final s in (_snap['plan']!['segments'] as List)) Map<String, dynamic>.from(s as Map)];

  Map<String, dynamic> _planSet(dynamic raw) {
    final out = <Map<String, dynamic>>[];
    for (final sg in (raw as List? ?? const [])) {
      final m = sg as Map;
      final a = (m['from'] as num).toInt();
      final b = ((m['to'] as num?) ?? 0).toInt();
      final st = ((m['stars'] as num?) ?? 5).toInt().clamp(1, 5);
      if (a < 1 || (b != 0 && b < a)) {
        throw RpcException('bad_input', 'Rentang $a-$b tidak valid.');
      }
      if (out.isNotEmpty &&
          (out.last['to'] == 0 || a <= (out.last['to'] as int))) {
        throw RpcException(
            'bad_input', 'Bagian harus berurutan dan tidak tumpang tindih.');
      }
      out.add({'from': a, 'to': b, 'stars': st, 'silver': m['silver'] == true && st == 5});
    }
    final lock = _snap['plan']!['lock_until'] as int?;
    if (running && lock != null) {
      // bagian yang sedang/segera dikerjakan tidak boleh berubah
      final lama = _segments.where((x) => (x['from'] as int) <= lock).toList();
      final depan = out.take(lama.length).toList();
      if (!_same(depan, lama)) {
        throw RpcException('locked',
            'Bagian yang sedang dikerjakan belum bisa diubah. Stop dulu ya.');
      }
      // akhir rentang ikut rencana baru
      _engine?.st.levelEnd = out.isEmpty ? 0 : out.last['to'] as int;
    }
    _set('plan', {'segments': out});
    _saveSettings({'plan': out});
    return {'segments': out};
  }

  // ------------------------------------------------------------ bot
  Future<dynamic> _start(dynamic range) async {
    if (running) {
      throw RpcException('busy', 'Bot masih jalan. Tunggu sebentar ya.');
    }
    if (_snap['license']!['state'] != 'ok') {
      throw RpcException('license', 'Aktifkan TypingBot dulu ya.');
    }
    final v = _view;
    if (v == null || v.disposed) {
      throw RpcException('not_ready', 'Halaman edclub belum siap.');
    }
    final segs = _segments;
    int mulai, akhir;
    if (segs.isNotEmpty) {
      mulai = segs.first['from'] as int;
      akhir = segs.last['to'] as int;
    } else if (range is Map && range['mode'] == 'custom') {
      mulai = (range['start'] as num).toInt();
      akhir = ((range['end'] as num?) ?? 0).toInt();
    } else {
      mulai = 1; // lanjut dari posisi akun
      akhir = 0;
    }
    final page = Page(_bridgeFor(v), clock: clock);
    final eng = Engine(
      page: page,
      levels: _levels ??= LevelMap(_base),
      dataDir: _base,
      onLog: _log,
    );
    eng.st
      ..speedWpm = (_snap['speed']!['wpm'] as int?) ?? 400
      ..levelStart = mulai
      ..levelEnd = akhir
      ..rangeJumpDone = mulai <= 1
      ..rangeReady = true;
    eng.askLocked = _askLocked;
    if (mulai > 1 || akhir > 0) {
      _log('Rentang level aktif: $mulai - ${akhir == 0 ? 'akhir kursus' : akhir}.');
    }
    _engine = eng;
    _page = page;
    _set('bot', {'phase': 'starting', 'error': ''});
    _set('range', {'start': mulai, 'end': akhir});
    // fokus ke halaman: klik tombol Mulai mem-blur webview, dan blur
    // dihitung 'user aktif' oleh pengawas (bot bisa menunggu 25 dtk)
    v.focus().catchError((_) {});
    try {
      await page.attach();
      await page.cdp('Network.enable').catchError((_) => <String, dynamic>{});
      _netSub = page.bridge
          .listen('Network.responseReceived')
          .listen((e) => eng.onNetworkResponse(e.params), onError: (_) {});
    } catch (e) {
      _log('[BOT] gagal menyambung ke halaman: $e');
    }
    _poll = Timer.periodic(pollInterval, (_) => _tick());
    _run = eng.run().catchError((Object e) {
      _set('bot', {'error': '$e'.length > 200 ? '$e'.substring(0, 200) : '$e'});
      _log('[BOT] berhenti karena error: $e');
    }).whenComplete(_finished);
    _set('bot', {'phase': 'running'});
    return {'started': true};
  }

  void _stop() {
    final e = _engine;
    if (e == null || !running) return;
    e.st.stop = true;
    _set('bot', {'phase': 'stopping'});
  }

  Future<void> _finished() async {
    _poll?.cancel();
    _poll = null;
    final e = _engine;
    await _netSub?.cancel();
    _netSub = null;
    await _page?.detach();
    _run = null;
    _tick(); // keadaan akhir
    final done = e?.st.rangeDone ?? false;
    _set('bot', {
      'phase': done ? 'done' : 'idle',
      'needs_login': _urlNeedsLogin,
    });
    _set('plan', {'active': null, 'lock_until': null, 'done_in_active': 0});
    _set('level', {'progress': 0.0});
    _log('Bot berhenti.');
  }

  /// Tunggu sampai loop bot benar2 selesai (tes / tutup app).
  Future<void> get stopped => _run ?? Future.value();

  int _levelNow(Engine e) {
    final lbl = e.st.statusLabel;
    if (lbl.startsWith('L')) {
      final n = int.tryParse(lbl.substring(1));
      if (n != null) return n;
    }
    return e.levels.urlToLevel(e.st.statusUrl) ?? 0;
  }

  /// Pemetaan state mesin -> snapshot (10x per detik selama jalan).
  void _tick() {
    final e = _engine;
    if (e == null) return;
    final st = e.st;
    final jalan = running;
    final phase = !jalan
        ? (st.rangeDone ? 'done' : 'idle')
        : st.stop
            ? 'stopping'
            : 'running';
    _set('bot', {
      'phase': phase,
      'needs_login': _urlNeedsLogin || (jalan && st.needsLogin),
      'browser_closed': st.browserClosed,
    });
    final lvl = jalan ? _levelNow(e) : 0;
    _set('level', {
      'num': lvl,
      'url': st.statusUrl,
      'label': st.statusLabel,
      'progress': double.parse(st.levelProgress.toStringAsFixed(3)),
    });
    _set('range', {
      'start': st.levelStart,
      'end': st.levelEnd,
      'position': e.levels.posisi,
    });
    _planTick(jalan, lvl);
    _askTick(e);
    _loginTick(e);
  }

  void _planTick(bool jalan, int lvl) {
    final p = _snap['plan']!;
    if (!jalan || lvl == 0) {
      if (p['active'] != null || p['lock_until'] != null) {
        _set('plan', {'active': null, 'lock_until': null, 'done_in_active': 0});
      }
      return;
    }
    int? idx;
    Map<String, dynamic>? seg;
    final segs = _segments;
    for (var i = 0; i < segs.length; i++) {
      final s = segs[i];
      final to = s['to'] as int;
      if (lvl >= (s['from'] as int) && (to == 0 || lvl <= to)) {
        idx = i;
        seg = s;
        break;
      }
    }
    _set('plan', {
      'active': idx,
      'done_in_active': seg == null ? 0 : (lvl - (seg['from'] as int)).clamp(0, 1 << 30),
      'lock_until': lvl + lockDistance,
    });
    // TODO(N7): target bintang per bagian -> atur kecepatan/akurasi
  }

  void _askTick(Engine e) {
    if (e.st.askNextLevel) {
      e.st.askNextLevel = false;
      _askOnce('next', 'level.next', {'level': _levelNow(e)}, {'wait': true}).then((r) {
        if (r is Map && r['wait'] == false) _stop();
      });
    }
  }

  /// Sesi mati saat jalan: arahkan halaman ke login sekali per 5 menit
  /// (sama dgn _login_tick sidecar; halaman login tampil di app).
  void _loginTick(Engine e) {
    if (!e.st.needsLogin) {
      _loginNavT = 0;
      return;
    }
    final t = DateTime.now().millisecondsSinceEpoch / 1000;
    if (t - _loginNavT > 300) {
      _loginNavT = t;
      e.st.askLoginUrl = loginUrlIndividual;
      e.st.askLoginNav = true;
    }
  }

  Future<String?> _askLocked(int start, int fallback) async {
    final r = await _askOnce('locked', 'level.locked',
        {'level': start, 'fallback': fallback}, {'skip': true},
        timeout: const Duration(seconds: 300));
    return (r is Map && r['skip'] == false) ? 'stop' : 'mulai';
  }

  /// Tanya UI (satu per kunci); habis waktu = [fallback].
  Future<Object?> _askOnce(String key, String method, Map<String, dynamic> params,
      Object? fallback,
      {Duration timeout = const Duration(seconds: 300)}) async {
    if (!_asking.add(key)) return fallback;
    final c = Completer<Object?>();
    _asks.add(SidecarAsk(++_askSeq, method, params, (_, ans) {
      if (!c.isCompleted) c.complete(ans);
    }));
    try {
      return await c.future.timeout(timeout, onTimeout: () => fallback);
    } finally {
      _asking.remove(key);
    }
  }

  @override
  void close() {
    _engine?.st.stop = true;
    _poll?.cancel();
    _revealT?.cancel();
    _viewSub?.cancel();
    _view?.dispose().catchError((_) {});
  }
}
