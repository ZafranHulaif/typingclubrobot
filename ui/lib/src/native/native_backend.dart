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
import 'dart:math';

import 'package:flutter/foundation.dart' show visibleForTesting;

import '../bridge/bridge.dart';
import '../engine/clock.dart';
import '../engine/engine.dart';
import '../engine/level_map.dart';
import '../engine/js.dart' show profileCheckJs;
import '../engine/js_inline.dart' show bacaUnlockJs;
import '../engine/page.dart';
import '../engine/urls.dart' show diLesson, lessonPlayUrl;
import '../net/api.dart';
import '../net/license.dart' as lic;
import '../net/machine.dart' as machine;
import '../net/report.dart';
import '../net/updater.dart';
import '../web/js_diag.dart';
import '../state/star_rule.dart';
import '../web/js_init.dart';
import '../web/js_back.dart';
import '../web/ad_block.dart';
import '../web/js_hidden.dart';
import '../web/js_audio_mac.dart';
import '../web/js_net_mac.dart';
import '../web/web_host.dart';
import 'accounts.dart';
import 'view_bridge.dart';

const homeUrl = 'https://www.edclub.com/student/course/3';
const signinUrl = 'https://www.edclub.com/signin';

/// URL mulai OAuth Google edclub + prompt=none: Google langsung balik
/// (sesi Google ada -> login lewat relay; tidak ada -> ?error -> /signin),
/// tanpa pernah menampilkan UI. client_id dari api.edclub.com/auth/get_account.
String googleSilentUrl() {
  final r = Random.secure();
  final st = [for (var i = 0; i < 32; i++) r.nextInt(256).toRadixString(16).padLeft(2, '0')].join();
  return Uri.https('accounts.google.com', '/o/oauth2/v2/auth', {
    'response_type': 'code',
    'redirect_uri': 'https://s.typingclub.com/m/auth_callback.html',
    'client_id': '1036962974046-hsai0fu9h3huagfkqmn61nfuqgr01mn3.apps.googleusercontent.com',
    'scope': 'https://www.googleapis.com/auth/userinfo.profile https://www.googleapis.com/auth/userinfo.email',
    'state': st,
    'prompt': 'none',
  }).toString();
}

/// Init script utk tiap dokumen (urutan sama dgn pengawas 3.5.x).
const initScripts = [
  noPopupJs,
  durFixJs,
  loginRedirectJs,
  oauthRelayPageJs,
  oauthMarkerJs,
  authBackJs, // v4: tombol kembali di halaman login Google/Clever/Microsoft
  hiddenRunJs, // v4: halaman & game tetap jalan saat app disembunyikan
];

/// Bagian rencana yang mulai <= level kini + ini terkunci saat jalan.
const lockDistance = 2;

/// Level terakhir kursus Typing Jungle.
const lastLevel = 685;

class NativeBackend implements Backend {
  NativeBackend({
    required String version,
    WebHost? host,
    AccountStore? accounts,
    this.revealTimeout = const Duration(seconds: 20),
    this.pollInterval = const Duration(milliseconds: 100),
    CdpBridge Function(WebView view)? bridgeFor,
    this.clock,
    this.checkLicense = true,
    this.updateInterval = const Duration(minutes: 20),
    this.memLogInterval = const Duration(minutes: 5),
    Api? api,
    String Function()? machineCode,
  })  : host = host ?? webHost,
        _version = version,
        _apiOverride = api,
        _machineCode = machineCode ?? machine.machineCode,
        accounts = accounts ?? AccountStore(AccountStore.defaultBase()),
        _bridgeFor = bridgeFor ?? WebViewBridge.new {
    _settings = _loadSettings();
    _bootPlan = _planFor(this.accounts.active() ?? '');
    final wpm = ((_settings['speed'] as num?) ?? 400).toInt().clamp(40, 400);
    final acc = ((_settings['acc'] as num?) ?? 100).toInt().clamp(manualAccMin, 100);
    final fs = (_settings['free'] as Map?) ?? const {};
    final silver = (fs['silver'] ?? true) == true;
    // mode Manual (4.1.0): dulu bintang 5 platinum = kecepatan bebas.
    // Pengguna lama yang menurunkan kecepatan dgn platinum pindah ke
    // Manual 100% (perilaku sama persis); lainnya tetap mode bintang.
    final fmode = fs['mode'] == 'manual' || (fs['mode'] == null && silver && wpm < 400)
        ? 'manual'
        : 'stars';
    _snap = {
      'app': {'version': version, 'platform': Platform.isMacOS ? 'macos' : 'windows', 'mode': 'native'},
      'bot': {'phase': 'idle', 'needs_login': false},
      'level': <String, dynamic>{},
      'range': <String, dynamic>{},
      'speed': {'wpm': wpm, 'acc': acc},
      // bisu: semua suara halaman edclub (disimpan, ikut tiap ganti akun)
      'sound': {'muted': _settings['muted'] == true},
      'account': {'active': '', 'list': <Map<String, dynamic>>[]},
      // N4: diisi _netBoot; checkLicense=false (tes) = tidak dikunci
      // v4: lisensi per akun edclub, diperiksa saat Mulai (bukan saat buka)
      'license': {'state': 'ok'},
      'update': <String, dynamic>{},
      'cover': {'visible': true, 'text': 'Menyiapkan edclub...'},
      'plan': {'segments': <Map<String, dynamic>>[]},
      'web': {'url': '', 'title': ''},
      // target bintang utk Mulai tanpa rencana
      'free': {
        'stars': ((fs['stars'] as num?) ?? 5).toInt().clamp(1, 5),
        // default perak (= ketik secepatnya, perilaku sebelum N7)
        'silver': silver,
        // 'stars' = pilih bintang (kecepatan & akurasi otomatis) /
        // 'manual' = atur kecepatan & akurasi sendiri, bintang = perkiraan
        'mode': fmode,
      },
    };
    _snap['plan']!['segments'] = _bootPlan;
    // aturan khusus game (semua akun, hanya saat rencana jalan)
    _snap['games'] = _gameRulesJson();
    // jenis tiap level kursus (sama utk semua akun), terkumpul selagi jalan
    _snap['catalog'] = Map<String, dynamic>.from((_settings['level_kinds'] as Map?) ?? const {});
    _syncSeq(this.accounts.active() ?? '');
    _syncSpeedLock();
    _snap['range']!['unlocked'] = _unlockedFor(this.accounts.active() ?? '');
  }

  final WebHost host;
  final AccountStore accounts;
  final Duration revealTimeout;
  final Duration pollInterval;
  final CdpBridge Function(WebView view) _bridgeFor;

  /// jam mesin (tes: jam palsu); null = jam sistem
  final Clock? clock;

  /// false = lewati lisensi & jaringan (tes)
  final bool checkLicense;
  final Duration updateInterval;
  final Duration memLogInterval;
  final String _version;
  final Api? _apiOverride;
  final String Function() _machineCode;
  Api? _apiCache;
  Map<String, dynamic>? _tok;
  Map<String, dynamic>? _updateInfo;
  int _approvalRun = 0;
  bool _closed = false;

  late final Map<String, Map<String, dynamic>> _snap;
  late final List<Map<String, dynamic>> _bootPlan;
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
  // cek login sekali tiap webview dibuka (cover tetap sampai pasti)
  bool _gatePending = false;
  int _gateRun = 0;
  // sesi edclub: kuki rt (kuki sesi = hilang saat app tutup) disimpan per
  // akun di tb_sesi.json & dipasang lagi sebelum navigasi pertama
  String? _viewAcct;
  Timer? _rtT;
  Timer? _updT;
  bool _rtBusy = false, _seenIn = false;
  String _rtSaved = '';
  // login Google otomatis / tahan cover selama relay OAuth
  bool _oauthHold = false, _oauthSeen = false, _autoTried = false;
  Timer? _holdT;
  // Mulai ditekan tapi mesin belum jalan: tunggu login / pilih level
  Timer? _waitT;
  bool _waitBusy = false;
  bool _waitNavLogin = false;
  int _waitUnknown = 0;
  String _mode = 'free';
  int _starLvl = 0; // level terakhir yang dikenal utk target bintang
  bool _urlNeedsLogin = false;

  // ---- mesin bot
  LevelMap? _levels;
  Engine? _engine;
  Page? _page;
  Future<void>? _run;
  StreamSubscription<CdpEvent>? _netSub;
  Timer? _poll;
  Timer? _memT;
  // diagnosa beban: waktu CPU per pid di sampel sebelumnya + jumlah
  // respons per host sejak log terakhir
  Map<int, int> _cpuPrev = {};
  DateTime? _cpuAt;
  final _hosts = <String, int>{};
  double _loginNavT = 0;
  int _askSeq = 0;
  final _asking = <String>{};

  WebView? get view => _view;
  Engine? get engine => _engine;
  bool get running => _run != null;

  /// mesin jalan ATAU masih menunggu login/pilihan level
  bool get busy => running || _waitT != null;

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
    final lb = accounts.labels();
    _set('account', {
      'active': a ?? '',
      'active_label': a == null ? '' : (lb[a] ?? a),
      'pending': a != null && accounts.isPending(a),
      'list': [
        for (final n in accounts.list()) {'name': n, 'label': lb[n] ?? n}
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

  /// Log memori WebView2 per jenis proses, mis.
  /// `[mem] WebView2 1234 MB: renderer 3x 800, gpu 250, browser 120, ...`
  /// (private bytes; mirip kolom Memory di Task Manager).
  Future<void> _memLog({bool quiet = false}) async {
    final v = _view;
    if (v == null || v.disposed) return;
    try {
      if (Platform.isMacOS && !quiet) {
        // macOS: proses WebKit tak terbaca; gantinya diagnosa suara
        try {
          final r = await v.cdp('Runtime.evaluate',
              {'expression': audioStateJs, 'returnByValue': true});
          _log('[audio] ${(r['result'] as Map?)?['value'] ?? '?'}'
              '${_snap['sound']!['muted'] == true ? ' (dibisukan di app)' : ''}');
        } catch (e) {
          _log('[audio] gagal baca: $e');
        }
      }
      final l = await v.memInfo();
      if (l.isEmpty) return;
      final kini = DateTime.now();
      final cpuKini = <int, int>{};
      final cpuPer = <String, int>{};
      for (final p in l) {
        final pid = (p['pid'] as num?)?.toInt() ?? 0;
        final c = (p['cpu'] as num?)?.toInt() ?? 0;
        cpuKini[pid] = c;
        final lama = _cpuPrev[pid];
        if (lama != null && c >= lama) {
          cpuPer['${p['kind']}'] = (cpuPer['${p['kind']}'] ?? 0) + c - lama;
        }
      }
      final dari = _cpuAt;
      _cpuPrev = cpuKini;
      _cpuAt = kini;
      if (quiet) return;
      if (dari != null) {
        // % dari seluruh inti CPU (sama dgn kolom CPU di Task Manager)
        final jendela = kini.difference(dari).inMicroseconds * 10 * Platform.numberOfProcessors;
        if (jendela > 0) {
          int pct(int t) => (t * 100 / jendela).round();
          final tot = cpuPer.values.fold(0, (a, b) => a + b);
          final rinciCpu = (cpuPer.entries.toList()..sort((a, b) => b.value.compareTo(a.value)))
              .map((e) => '${e.key} ${pct(e.value)}')
              .join(', ');
          _log('[cpu] WebView2 ${pct(tot)}%: $rinciCpu');
        }
      }
      if (_hosts.isNotEmpty) {
        final top = (_hosts.entries.toList()..sort((a, b) => b.value.compareTo(a.value)))
            .take(15)
            .map((e) => '${e.key} ${e.value}')
            .join(', ');
        _log('[net] respons per host: $top');
        _hosts.clear();
      }
      final per = <String, List<int>>{};
      var tot = 0;
      for (final p in l) {
        final b = (p['private'] as num?)?.toInt() ?? 0;
        tot += b;
        (per['${p['kind']}'] ??= [0, 0])
          ..[0] += 1
          ..[1] += b;
      }
      int mb(int b) => (b / 1048576).round();
      final rinci = (per.entries.toList()..sort((a, b) => b.value[1].compareTo(a.value[1])))
          .map((e) => '${e.key} ${e.value[0] > 1 ? '${e.value[0]}x ' : ''}${mb(e.value[1])}')
          .join(', ');
      _log('[mem] WebView2 ${mb(tot)} MB: $rinci');
    } catch (e) {
      _log('[mem] gagal baca memori: $e');
    }
  }

  void _keepAwake(bool on) {
    host.keepAwake(on).catchError((Object e) {
      _log('[app] keepAwake gagal: $e');
    });
  }

  /// Buffer Network CDP kecil: tanpa batas, Chromium menyimpan salinan isi
  /// respons (utk DevTools) sampai ratusan MB, padahal yang dibaca cuma
  /// status + URL (sentinel login).
  static const _netBuffers = {
    'maxTotalBufferSize': 1000000,
    'maxResourceBufferSize': 100000,
    'maxPostDataSize': 0,
  };

  /// Blokir iklan (default nyala; settings 'adblock': false = mati).
  bool get _adBlockOn => _settings['adblock'] != false;

  /// Windows: blokir domain iklan lewat CDP sebelum halaman pertama.
  /// (macOS memakai content blocker WebKit dari argumen 'block' saat create.)
  Future<void> _adBlock(WebView v) async {
    if (!_adBlockOn) return;
    try {
      await v.cdp('Network.enable', _netBuffers);
      await v.cdp('Network.setBlockedURLs', {'urls': adBlockPatterns()});
    } catch (e) {
      _log('[web] blokir iklan gagal: $e');
    }
  }

  void _applyMute(WebView v) {
    v.setMuted(_snap['sound']!['muted'] == true).catchError((Object e) {
      _log('[web] bisu gagal: $e');
    });
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
    accounts.dropPending(except: accounts.active());
    _refreshAccounts();
    _levels = LevelMap(_base)..muatPosisi();
    _set('range', {
      'position': _levels!.posisi,
      'total': _levels!.map.length,
      'mapped': _levels!.map.length,
    });
    if (checkLicense) {
      // cek lokal dulu (cepat): token/kunci sah = langsung ok tanpa
      // menunggu jaringan; server memastikan di latar
      final tok = lic.loadToken(_licPath);
      if (tok != null && lic.verifyToken(tok)) _tok = tok;
      unawaited(_netBoot());
      // cek pembaruan berkala: versi baru muncul tanpa buka-tutup app
      _updT?.cancel();
      _updT = Timer.periodic(updateInterval, (_) => _updateTick());
    }
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
    _cover(name == null
        ? 'Menyiapkan edclub...'
        : accounts.isPending(name)
            ? 'Membuka akun baru...'
            : 'Membuka akun ${accounts.labelOf(name)}...');
    final old = _view;
    await _viewSub?.cancel();
    _viewSub = null;
    _revealT?.cancel();
    WebView v;
    try {
      // tanpa URL dulu: kuki sesi dipasang sebelum halaman pertama
      v = await host.create(
          folder: accounts.folderFor(name),
          url: '',
          scripts: [
            ...initScripts,
            if (Platform.isMacOS) netWatchJs, // sentinel login (tanpa CDP Network)
            if (Platform.isMacOS) audioWatchJs, // diagnosa suara
            if (Engine.keyLog) keyLogJs,
          ],
          blockHosts: _adBlockOn ? adHosts : const []);
    } on WebHostException catch (e) {
      _cover('Halaman edclub gagal dibuka (${e.code}). Tutup lalu buka '
          'lagi TypingBot ya.');
      return;
    }
    _view = v;
    _viewAcct = name;
    if (_snap['sound']!['muted'] == true) _applyMute(v);
    _set('plan', {'segments': _planFor(name ?? '')});
    _syncSeq(name ?? '');
    _set('range', {'unlocked': _unlockedFor(name ?? '')});
    _labelDone = false;
    _rtSaved = '';
    _seenIn = false;
    _autoTried = false;
    _oauthHold = false;
    _oauthSeen = false;
    _gatePending = !url.contains('/signin');
    _gateRun++;
    _viewSub = v.events.listen(_onWeb);
    await _adBlock(v);
    await _rtRestore(v, name);
    await v.navigate(url).catchError((_) {});
    _rtT?.cancel();
    _rtT = Timer.periodic(const Duration(seconds: 3), (_) => _rtTick());
    // jaga-jaga: halaman lambat / gagal = tetap tampilkan
    _revealT = Timer(revealTimeout, () => _cover(null));
    if (old != null) await old.dispose().catchError((_) {});
  }

  void _onWeb(WebEvent e) {
    switch (e.type) {
      case 'nav':
        final url = e.url;
        if (url.isEmpty || url.startsWith('about:')) return;
        // relay OAuth (auth_callback / ?oauth_relay=): cover menutupi
        // kilatan putih sampai login selesai
        if (e.data['phase'] == 'start' && _relayUrl(url)) {
          _oauthSeen = true;
          if (!_oauthHold) {
            _oauthHold = true;
            _cover('Sedang masuk...');
          }
          _revealT?.cancel();
          _revealT = Timer(revealTimeout, () {
            _oauthHold = false;
            _cover(null);
          });
        }
        if (e.data['phase'] == 'done') {
          final u = Uri.tryParse(url);
          final host = u?.host ?? '';
          if (_oauthHold) {
            if (host.contains('google')) {
              // prompt=none tak pernah berhenti di Google kecuali error
              _oauthHold = false;
              _view?.navigate(signinUrl).catchError((_) {});
            } else if (host.endsWith('edclub.com') && !_relayUrl(url)) {
              _holdT?.cancel();
              void buka() {
                _oauthHold = false;
                _revealT?.cancel();
                _cover(null);
                unawaited(_logRelay());
              }
              if (u!.path.contains('/signin')) {
                // bisa jadi halaman relay (URL sudah dibersihkan): tunggu
                _holdT = Timer(const Duration(seconds: 4), () {
                  if (_oauthHold) buka();
                });
              } else {
                buka();
              }
            }
          } else if (_coverOn) {
            if (_gatePending) {
              // belum login = coba masuk otomatis / ke halaman login
              // (jangan tampilkan daftar level kosong)
              _gatePending = false;
              unawaited(_loginGate());
            } else {
              _revealT?.cancel();
              _cover(null);
            }
          }
        }
        _web(url);
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
    _checkPendingSoon();
    _readUnlockedSoon(url);
    _set('web', {'url': url});
    final u = Uri.tryParse(url);
    _urlNeedsLogin =
        u != null && u.host.contains('edclub') && u.path.contains('/signin');
    _set('bot', {'needs_login': _urlNeedsLogin || (_engine?.st.needsLogin ?? false) && running});
  }

  // ---- akun baru: resmi tersimpan begitu login berhasil
  Timer? _pendingT;

  bool _labelDone = false;

  /// Begitu login: akun baru jadi resmi & nama tampil ikut nama edclub
  /// (sekali per buka webview).
  void _checkPendingSoon() {
    final a = accounts.active();
    if (a == null || _labelDone) return;
    _pendingT?.cancel();
    _pendingT = Timer(const Duration(milliseconds: 1500), () => _checkPending(a));
  }

  Future<void> _checkPending(String id) async {
    if (accounts.active() != id || _labelDone) return;
    final url = '${_snap['web']!['url'] ?? ''}'.toLowerCase();
    if (url.contains('/signin') || url.contains('/signup') || url.contains('google')) return;
    if (await _profile() != 'in') return;
    final baru = accounts.isPending(id);
    if (baru) accounts.clearPending(id);
    final nama = await _displayName();
    _labelDone = nama.isNotEmpty || baru;
    if (nama.isNotEmpty && accounts.labelOf(id) != nama) {
      accounts.setLabel(id, nama);
      _log('[AKUN] Nama akun: $nama');
    }
    if (baru) _log('[AKUN] Akun baru tersimpan${nama.isNotEmpty ? ': $nama' : ''}.');
    _refreshAccounts();
  }

  /// Jejak relay OAuth (sessionStorage tb_oauth_dbg) -> bot.log.
  Future<void> _logRelay() async {
    try {
      final r = await _view?.eval("(() => { try { const v = sessionStorage.getItem('tb_oauth_dbg') || ''; "
          "sessionStorage.removeItem('tb_oauth_dbg'); return v; } catch (e) { return ''; } })()");
      if (r is String && r.isNotEmpty) _log('[LOGIN] relay: $r');
    } catch (_) {}
  }

  /// Nama user dari halaman edclub ('' = tidak terbaca).
  Future<String> _displayName() async {
    final v = _view;
    if (v == null || v.disposed) return '';
    try {
      // sama dgn sinyal 4 profileCheckJs (tombol nama-user), tapi ambil
      // kandidat paling kanan-atas (tombol profil di pojok kanan)
      final r = await v.eval(r'''(() => {
        const el = document.querySelector('.profile-name');
        if (el && el.textContent.trim() && !/sign|log\s*in/i.test(el.textContent)) return el.textContent.trim();
        const UI = /^(courses?|english|save progress|more|help|settings?|language|lessons?|programs?|typing jungle|dashboard|outline)$/i;
        let best = '', bx = -1;
        for (const b of document.querySelectorAll('button, [role="button"], a, li.dropdown > a.dropdown-toggle')) {
          if (!b.offsetParent) continue;
          const t = (b.textContent || '').replace(/\s+/g, ' ').trim();
          if (!t || t.length > 30) continue;
          if (/log ?(in|out)|sign ?(in|up|out)|masuk|daftar|get started|help/i.test(t)) continue;
          if (!/^[A-Z][A-Za-zÀ-ɏ'.\-]+( [A-Z][A-Za-zÀ-ɏ'.\-]{0,19}){0,3}$/.test(t)) continue;
          if (UI.test(t)) continue;
          const r = b.getBoundingClientRect();
          if (r.top > 160) continue;
          if (r.right > bx) { bx = r.right; best = t; }
        }
        return best;
      })()''');
      return r is String ? r : '';
    } catch (_) {
      return '';
    }
  }

  /// 'in' / 'out' / null dari penanda DOM halaman aktif.
  Future<String?> _profile() async {
    final v = _view;
    if (v == null || v.disposed) return null;
    try {
      final r = await v.eval('(() => {/*tb:login*/$profileCheckJs})()');
      return r is String ? r : null;
    } catch (_) {
      return null;
    }
  }

  /// Halaman balik OAuth (bukan halaman Google-nya). DULU cukup
  /// `contains('auth_callback')`: URL Google sendiri memuat teks itu di
  /// redirect_uri -> klik "Sign in with Google" langsung ditutup cover
  /// lalu dilempar balik ke /signin (kena kalau belum ada sesi Google).
  bool _relayUrl(String url) {
    final u = Uri.tryParse(url);
    if (u == null) return false;
    if (u.host.contains('typingclub')) return u.path.contains('auth_callback');
    if (u.host.endsWith('edclub.com')) return u.queryParameters.containsKey('oauth_relay');
    return false;
  }

  Future<void> _loginGate() async {
    final run = _gateRun;
    var out = 0;
    for (var i = 0; i < 25; i++) { // maks ~10 dtk
      final r = await _profile();
      if (run != _gateRun) return;
      if (r == 'in') {
        _seenIn = true;
        break;
      }
      out = r == 'out' ? out + 1 : 0;
      if (out >= 6) { // 'out' bertahan ~2,4 dtk (bukan kilatan hidrasi)
        if (!_autoTried && _sesiLoad(_viewAcct)['google'] != false) {
          _autoTried = true;
          _oauthHold = true;
          _log('[LOGIN] Mencoba masuk otomatis lewat Google.');
          _cover('Masuk otomatis...');
          try {
            // tandai: relay jangan kasih pesan "daftar dulu" (bukan klik user)
            await _view?.eval("(() => { try { sessionStorage.setItem('tb_oauth_from', 'auto'); } catch (e) {} return 1; })()")
                .catchError((_) => null);
            await _view?.navigate(googleSilentUrl());
            return;
          } catch (_) {
            _oauthHold = false;
          }
        }
        _log('[LOGIN] Belum login - membuka halaman login.');
        _set('bot', {'needs_login': true});
        try {
          await _view?.navigate(signinUrl);
          return; // cover turun begitu halaman login selesai dimuat
        } catch (_) {
          break;
        }
      }
      await Future<void>.delayed(const Duration(milliseconds: 400));
    }
    if (run != _gateRun) return;
    _revealT?.cancel();
    _cover(null);
  }

  // ---- sesi edclub (kuki rt) per akun
  String _sesiPath(String? name) =>
      '${accounts.folderFor(name)}${Platform.pathSeparator}tb_sesi.json';

  Map<String, dynamic> _sesiLoad(String? name) {
    try {
      return (jsonDecode(File(_sesiPath(name)).readAsStringSync()) as Map)
          .cast<String, dynamic>();
    } catch (_) {
      return {};
    }
  }

  void _sesiSave(String? name, Map<String, dynamic> patch) {
    try {
      final f = File(_sesiPath(name))..parent.createSync(recursive: true);
      f.writeAsStringSync(jsonEncode({..._sesiLoad(name), ...patch}));
    } catch (_) {}
  }

  Future<String?> _rtNow(WebView v) async {
    final r = await v.cdp('Network.getCookies', {
      'urls': ['https://api.edclub.com/']
    });
    for (final c in (r['cookies'] as List? ?? const [])) {
      if (c is Map && c['name'] == 'rt') return '${c['value']}';
    }
    return null;
  }

  /// rt = kuki sesi (hilang saat app tutup): pasang lagi SEBELUM navigasi.
  Future<void> _rtRestore(WebView v, String? name) async {
    final sesi = _sesiLoad(name);
    final rt = '${sesi['rt'] ?? ''}';
    if (rt.isEmpty) {
      if (sesi['legacy'] != true) await _legacyImport(v, name);
      return;
    }
    try {
      if (await _rtNow(v) != null) return; // jar masih punya rt lebih baru
      await v.cdp('Network.setCookie', {
        'name': 'rt',
        'value': rt,
        'domain': '.edclub.com',
        'path': '/',
        'secure': true,
        'httpOnly': true,
        'sameSite': 'None',
        'expires': DateTime.now().millisecondsSinceEpoch / 1000 + 180 * 86400,
      });
      _rtSaved = rt;
    } catch (_) {}
  }

  /// N5: akun dari 3.5.x belum punya sesi v4: pasang kuki edclub lamanya
  /// sekali (3.5.x menyimpannya di akun/akun-NAMA.json & sesi_edclub.json).
  Future<void> _legacyImport(WebView v, String? name) async {
    final cookies = accounts.legacyCookies(name);
    _sesiSave(name, {'legacy': true});
    if (cookies == null) return;
    var n = 0;
    for (final c in cookies) {
      final dom = '${c['domain'] ?? ''}';
      if (!dom.contains('edclub') && !dom.contains('typingclub')) continue;
      final p = <String, dynamic>{
        'name': c['name'],
        'value': c['value'],
        'domain': dom,
        'path': c['path'] ?? '/',
        if (c['secure'] == true) 'secure': true,
        if (c['httpOnly'] == true) 'httpOnly': true,
        if (const ['Strict', 'Lax', 'None'].contains(c['sameSite'])) 'sameSite': c['sameSite'],
        // kuki sesi (expires -1) dipasang dgn umur 180 hari spt rt v4
        'expires': ((c['expires'] as num?) ?? -1) > 0
            ? c['expires']
            : DateTime.now().millisecondsSinceEpoch / 1000 + 180 * 86400,
      };
      try {
        await v.cdp('Network.setCookie', p);
        n++;
      } catch (_) {}
    }
    if (n > 0) _log('[AKUN] $n kuki login dari versi lama dipasang (${name ?? 'bawaan'}).');
  }

  /// rt berputar tiap refresh: simpan tiap berubah, HANYA saat pasti login
  /// (boot anonim juga dapat rt, itu tidak boleh menimpa yang bagus).
  int _guestN = 0;

  /// edclub kini menampilkan daftar level ke TAMU (belum login, tombol
  /// 'Log in' di header). Kalau gerbang login terlewat (mis. internet
  /// lambat: cover sudah turun karena batas waktu sebelum halaman siap),
  /// app diam di halaman tamu dgn status 'Siap' (laporan 24 Nov). Tamu
  /// yang bertahan ~6 dtk di halaman /student = buka halaman login.
  Future<void> _guestCheck(WebView v, Uri u) async {
    if (running || _coverOn || _oauthHold || !u.path.startsWith('/student')) {
      _guestN = 0;
      return;
    }
    if (await _profile() != 'out' || v != _view) {
      _guestN = 0;
      return;
    }
    if (++_guestN < 2) return;
    _guestN = 0;
    _log('[LOGIN] Halaman tamu (belum login) - membuka halaman login.');
    _set('bot', {'needs_login': true});
    await v.navigate(signinUrl).catchError((_) {});
  }

  @visibleForTesting
  Future<void> rtTickForTest() => _rtTick();

  Future<void> _rtTick() async {
    final v = _view;
    if (v == null || v.disposed || _rtBusy) return;
    final url = '${_snap['web']!['url'] ?? ''}';
    final u = Uri.tryParse(url);
    if (u == null || !u.host.endsWith('edclub.com')) return;
    if (u.path.contains('/signin') || u.path.contains('/signup')) {
      _seenIn = false;
      return;
    }
    _rtBusy = true;
    try {
      final rt = await _rtNow(v);
      if (rt == null || rt.isEmpty) {
        await _guestCheck(v, u);
        return;
      }
      _guestN = 0;
      if (rt == _rtSaved) return;
      final masuk = (diLesson(url) && _seenIn) || await _profile() == 'in';
      if (!masuk || v != _view) return;
      _seenIn = true;
      _sesiSave(_viewAcct, {'rt': rt, if (_oauthSeen) 'google': true});
      _rtSaved = rt;
    } catch (_) {
    } finally {
      _rtBusy = false;
    }
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
          // akun baru yang ditinggal sebelum login = dibuang
          accounts.dropPending(except: name);
          _refreshAccounts();
          return _snap['account'];
        });
      case 'acct.add':
        _notWhileRunning();
        return _guard(() async {
          final name = accounts.newName();
          accounts.addPending(name);
          accounts.setActive(name);
          await _open(name, url: signinUrl);
          accounts.dropPending(except: name);
          _refreshAccounts();
          return _snap['account'];
        });
      case 'acct.delete':
        _notWhileRunning();
        final del = '${p['name'] ?? ''}'.trim();
        if (del.isEmpty) throw RpcException('bad_input', 'Pilih akunnya dulu.');
        return _guard(() async {
          if (del == accounts.active()) {
            final lain = accounts.list().where((n) => n != del).toList();
            if (lain.isNotEmpty) {
              accounts.setActive(lain.first);
              await _open(lain.first);
            } else {
              accounts.clearActive();
              await _open(null, url: signinUrl);
            }
          }
          final ok = await accounts.delete(del);
          _log('[AKUN] Akun dihapus: ${accounts.labelOf(del)}${ok ? '' : ' (folder dibersihkan saat app dibuka lagi)'}');
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
      case 'web.refocus':
        final st = _engine?.st;
        // hanya saat benar2 mengetik (bukan Dijeda / menunggu)
        if (running && st != null && !st.userLepas && st.waitUserUrl.isEmpty) {
          await _view?.focus().catchError((_) {});
          _handOver();
        }
        return true;
      case 'web.visible':
        _occluded = p['on'] != true;
        _applyVisible();
        return true;
      case 'speed.set':
        final sp = _snap['speed']!;
        final w = ((p['wpm'] as num?)?.toInt() ?? (sp['wpm'] as int?) ?? 400).clamp(40, 400);
        final a = ((p['acc'] as num?)?.toInt() ?? (sp['acc'] as int?) ?? 100)
            .clamp(manualAccMin, 100);
        // kecepatan dial hanya dipakai mode Manual tanpa rencana
        final e = _engine;
        if (e != null && _manualOn) e.st.speedWpm = w;
        _set('speed', {'wpm': w, 'acc': a});
        if (p['save'] != false) _saveSettings({'speed': w, 'acc': a});
        _syncSpeedLock();
        return {'wpm': w, 'acc': a};
      case 'sound.set':
        final on = p['muted'] == true;
        _set('sound', {'muted': on});
        _saveSettings({'muted': on});
        final v = _view;
        if (v != null && !v.disposed) _applyMute(v);
        return {'muted': on};
      case 'plan.set':
        return _planSet(p['segments']);
      case 'games.set':
        return _gamesSet(p);
      case 'settings.get':
        return Map<String, dynamic>.from(_settings);
      case 'settings.set':
        _saveSettings(Map<String, dynamic>.from(p));
        return Map<String, dynamic>.from(_settings);
      case 'bot.start':
        return _start(p['mode'], p['range']);
      case 'bot.stop':
        _stop();
        return {};
      case 'bot.resume':
        return _resume();
      case 'free.set':
        final cur = _snap['free']!;
        final st = ((p['stars'] as num?) ?? (cur['stars'] as int?) ?? 5).toInt().clamp(1, 5);
        final sv = p.containsKey('stars') ? p['silver'] == true : cur['silver'] == true;
        final md = p['mode'] == null
            ? (p.containsKey('stars') ? 'stars' : '${cur['mode'] ?? 'stars'}')
            : (p['mode'] == 'manual' ? 'manual' : 'stars');
        final f = {'stars': st, 'silver': sv && st == 5, 'mode': md};
        _set('free', f);
        _saveSettings({'free': f});
        final e = _engine;
        if (e != null) e.st.speedWpm = _engineWpm;
        _syncSpeedLock();
        return f;
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
      case 'license.request':
        return _licenseRequest('${p['nickname'] ?? ''}');
      case 'license.refresh':
        if (checkLicense) unawaited(_netBoot());
        return _snap['license'];
      case 'update.check':
        return _updateCheck();
      case 'update.download':
        return _updateDownload();
      case 'update.install':
        return _updateInstall();
      case 'update.cancel':
        _dlCancel = true;
        return {};
      case 'report.send':
        return _report('${p['category'] ?? ''}', '${p['text'] ?? ''}');
      case 'dev.info':
        return {'version': _version, 'data_dir': _base, 'mc': _mc()};
      default:
        throw RpcException('later', 'Bagian ini belum ada di versi uji ini.');
    }
  }

  void _notWhileRunning() {
    if (busy) {
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
      // keluar sengaja = jangan dipasang lagi / masuk otomatis
      _sesiSave(_viewAcct, {'rt': '', 'google': false});
      _rtSaved = '';
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
  /// Rencana per akun (settings 'plans' {akun: [...]}); rencana lama
  /// (3.5.x / dev, satu utk semua) jadi milik akun yang aktif pertama kali.
  List<Map<String, dynamic>> _planFor(String key) {
    final all = (_settings['plans'] as Map?) ?? const {};
    var raw = all[key];
    if (raw == null && all.isEmpty) raw = _settings['plan'];
    return _cleanPlan(raw);
  }

  /// Rencana tersimpan dirapikan: level di atas 685 dipotong/dibuang,
  /// bagian rusak/tumpang tindih dilewati (tanpa error).
  static List<Map<String, dynamic>> _cleanPlan(dynamic raw) {
    final out = <Map<String, dynamic>>[];
    for (final sg in (raw is List ? raw : const [])) {
      if (sg is! Map || sg['from'] is! num) continue;
      final a = (sg['from'] as num).toInt();
      var b = ((sg['to'] as num?) ?? 0).toInt();
      if (a < 1 || a > lastLevel) continue;
      if (b > lastLevel) b = lastLevel;
      if (b != 0 && b < a) continue;
      if (out.isNotEmpty && (out.last['to'] == 0 || a <= (out.last['to'] as int))) continue;
      final r = StarRule.fromJson(sg);
      out.add({'from': a, 'to': b, ...(r.follow ? StarRule.fixed(platinumCode) : r).toJson()});
    }
    return out;
  }

  int _unlockedFor(String key) =>
      ((((_settings['unlocked'] as Map?) ?? const {})[key] as num?) ?? 0).toInt();

  Timer? _unlockT;

  /// Di daftar level: baca level terbuka tertinggi akun ini (batas awal
  /// rencana & Mulai rencana).
  void _readUnlockedSoon(String url) {
    final u = Uri.tryParse(url);
    if (u == null || !u.host.endsWith('edclub.com')) return;
    if (!RegExp(r'^/student/course/\d+/?$').hasMatch(u.path)) return;
    _unlockT?.cancel();
    _unlockT = Timer(const Duration(seconds: 2), () async {
      final v = _view;
      if (v == null || v.disposed) return;
      try {
        final r = await v.eval('($bacaUnlockJs)()');
        if (r is! List || r.isEmpty) return;
        final n = r.whereType<num>().map((e) => e.toInt()).fold<int>(0, max);
        if (n < 1) return;
        final key = accounts.active() ?? '';
        if (_unlockedFor(key) == n) return;
        _saveSettings({
          'unlocked': {...((_settings['unlocked'] as Map?) ?? const {}), key: n}
        });
        _set('range', {'unlocked': n});
      } catch (_) {}
    });
  }

  /// Akhir rangkaian bagian yang tersambung dari bagian pertama. Bagian
  /// setelah celah tidak dijalankan (UI menandainya abu-abu).
  static int _chainEnd(List<Map<String, dynamic>> segs) {
    var end = segs.first['to'] as int;
    for (var i = 1; i < segs.length && end != 0; i++) {
      if ((segs[i]['from'] as int) != end + 1) break;
      end = segs[i]['to'] as int;
    }
    return end;
  }

  List<Map<String, dynamic>> get _segments =>
      [for (final s in (_snap['plan']!['segments'] as List)) Map<String, dynamic>.from(s as Map)];

  Map<String, dynamic> _planSet(dynamic raw) {
    final out = <Map<String, dynamic>>[];
    for (final sg in (raw as List? ?? const [])) {
      final m = sg as Map;
      final a = (m['from'] as num).toInt();
      final b = ((m['to'] as num?) ?? 0).toInt();
      if (m['rule'] == 'pattern' && (m['pattern'] as List? ?? const []).isEmpty) {
        throw RpcException('bad_input', 'Polanya masih kosong. Tambah minimal satu target ya.');
      }
      final r = StarRule.fromJson(m);
      if (a < 1 || (b != 0 && b < a)) {
        throw RpcException('bad_input', 'Rentang $a-$b tidak valid.');
      }
      if (a > lastLevel || b > lastLevel) {
        throw RpcException('bad_input', 'Level terakhir itu $lastLevel ya.');
      }
      if (out.isNotEmpty &&
          (out.last['to'] == 0 || a <= (out.last['to'] as int))) {
        throw RpcException(
            'bad_input', 'Bagian harus berurutan dan tidak tumpang tindih.');
      }
      out.add({'from': a, 'to': b, ...(r.follow ? StarRule.fixed(platinumCode) : r).toJson()});
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
      _engine?.st.levelEnd = out.isEmpty ? 0 : _chainEnd(out);
    }
    _set('plan', {'segments': out});
    final key = accounts.active() ?? '';
    _saveSettings({
      'plans': {...((_settings['plans'] as Map?) ?? const {}), key: out}
    });
    _pruneSeq(key);
    return {'segments': out};
  }

  // ------------------------------------------------- aturan & urutan bintang
  /// Aturan khusus game tersimpan (settings 'game_rules'); default ikut
  /// rencana. Hanya berlaku saat rencana jalan.
  Map<String, dynamic> _gameRulesJson() {
    final raw = (_settings['game_rules'] as Map?) ?? const {};
    return {
      for (final k in gameKinds)
        k: (raw[k] is Map ? StarRule.fromJson(raw[k] as Map) : StarRule.follow()).toJson(),
    };
  }

  StarRule _gameRule(String kind) {
    final g = (_snap['games']?[kind] as Map?) ?? const {'rule': 'follow'};
    return StarRule.fromJson(g);
  }

  /// Ada aturan khusus untuk game [kind] ('game' = game apa saja).
  bool _gameRuleOn(String kind) => kind == 'game'
      ? gameKinds.any((k) => !_gameRule(k).follow)
      : gameKinds.contains(kind) && !_gameRule(kind).follow;

  Map<String, dynamic> _gamesSet(Map p) {
    final out = <String, dynamic>{};
    for (final k in gameKinds) {
      final m = p[k];
      if (m is Map && m['rule'] == 'pattern' && (m['pattern'] as List? ?? const []).isEmpty) {
        throw RpcException('bad_input',
            'Pola ${gameNames[k]!.toLowerCase()} masih kosong. Tambah minimal satu target ya.');
      }
      out[k] = (m is Map ? StarRule.fromJson(m) : _gameRule(k)).toJson();
    }
    _set('games', out);
    _saveSettings({'game_rules': out});
    _pruneSeq(accounts.active() ?? '');
    _syncSpeedLock();
    return out;
  }

  /// Urutan bintang per akun: settings 'star_seq' {akun: {tanda aturan:
  /// {n: giliran berikutnya, lv: {level: giliran}}}}. Level yang sudah
  /// dapat giliran tetap sama saat diulang / bot dibuka lagi.
  Map<String, dynamic> _seqFor(String acct) => Map<String, dynamic>.from(
      (((_settings['star_seq'] as Map?) ?? const {})[acct] as Map?) ?? const {});

  void _saveSeq(String acct, Map<String, dynamic> seq) {
    _saveSettings({
      'star_seq': {...((_settings['star_seq'] as Map?) ?? const {}), acct: seq}
    });
    _syncSeq(acct);
  }

  /// UI: giliran terpakai per aturan (pratinjau "berikutnya") + kunci akun
  /// (benih acak sama dgn backend).
  void _syncSeq(String acct) {
    final seq = _seqFor(acct);
    _snap['plan'] = {
      ...?_snap['plan'],
      'acct': acct,
      // {tanda: {n, lv: {level: giliran}}}: peta level di editor
      'seq': seq,
    };
    _events.add(SidecarEvent('state', {'plan': _snap['plan']}));
  }

  /// Catat jenis level sekarang (peta level di editor rencana). Jenis
  /// yang dinilai bintang tidak diturunkan jadi 'free' (mis. tahan tombol
  /// di tengah lesson berbintang).
  void _recordKind(Engine e, String kind) {
    final l = _levelNow(e);
    if (l <= 0) return;
    final cat = _snap['catalog']!;
    final lama = cat['$l'];
    if (lama == kind || (kind == 'free' && lama != null && lama != 'free')) return;
    _snap['catalog'] = {...cat, '$l': kind};
    _saveSettings({'level_kinds': _snap['catalog']});
    _events.add(SidecarEvent('state', {'catalog': _snap['catalog']}));
  }

  /// Semua tanda aturan yang masih dipakai akun ini.
  Set<String> _liveSigs() => {
        for (final sg in _segments) StarRule.fromJson(sg).sig('p${sg['from']}'),
        for (final k in gameKinds) _gameRule(k).sig('g:$k'),
      };

  /// Aturan diubah: urutan lama dibuang (pola/acak mulai dari awal).
  void _pruneSeq(String acct) {
    final seq = _seqFor(acct);
    final hidup = _liveSigs();
    final sisa = {for (final e in seq.entries) if (hidup.contains(e.key)) e.key: e.value};
    if (sisa.length != seq.length) _saveSeq(acct, sisa);
  }

  // ------------------------------------------------------------ bot
  /// Mulai: [mode] 'free' (tanpa rencana: mulai dari level yang dibuka
  /// user di halaman) atau 'plan' (ikuti rencana). Belum login = tunggu
  /// login dulu; mode free tanpa lesson terbuka = tunggu user memilih.
  Future<dynamic> _start(dynamic mode, dynamic range) async {
    if (busy) {
      throw RpcException('busy', 'Bot masih jalan. Tunggu sebentar ya.');
    }
    final v = _view;
    if (v == null || v.disposed) {
      throw RpcException('not_ready', 'Halaman edclub belum siap.');
    }
    if (range is Map && range['mode'] == 'custom') {
      return _launch((range['start'] as num).toInt(), ((range['end'] as num?) ?? 0).toInt());
    }
    _mode = mode == 'plan' ? 'plan' : 'free';
    _starLvl = 0;
    if (_mode == 'plan' && _segments.isEmpty) {
      throw RpcException('empty', 'Rencana masih kosong. Tambah bagian dulu ya.');
    }
    final buka = _unlockedFor(accounts.active() ?? '');
    if (_mode == 'plan' && buka > 0 && (_segments.first['from'] as int) > buka) {
      throw RpcException('locked_level',
          'Level ${_segments.first['from']} belum terbuka di akun ini. '
          'Level terbuka terakhir: $buka.');
    }
    _waitNavLogin = false;
    _waitUnknown = 0;
    _set('bot', {'phase': 'waiting', 'wait': '', 'mode': _mode, 'error': ''});
    _waitT = Timer.periodic(const Duration(milliseconds: 500), (_) => _waitTick());
    await _waitTick();
    return {'started': true};
  }

  Future<String> _webUrl() async {
    var u = '${_snap['web']!['url'] ?? ''}';
    if (u.isEmpty) {
      try {
        u = (await _view!.info()).url;
      } catch (_) {}
    }
    return u;
  }

  Future<void> _waitTick() async {
    if (_waitT == null || _waitBusy) return;
    _waitBusy = true;
    try {
      final url = await _webUrl();
      final low = url.toLowerCase();
      final diLogin = low.contains('/signin') ||
          low.contains('accounts.google') ||
          low.contains('/login') ||
          low.contains('sportal.');
      String wait;
      if (diLogin) {
        wait = 'login';
      } else {
        final prof = diLesson(url) ? 'in' : await _profile();
        if (_waitT == null) return;
        if (prof == 'out') {
          wait = 'login';
          if (!_waitNavLogin) {
            _waitNavLogin = true;
            _log('[LOGIN] Belum login - membuka halaman login.');
            await _view?.navigate(signinUrl).catchError((_) {});
          }
        } else if (prof == null && ++_waitUnknown < 10) {
          wait = 'check';
        } else if (_mode == 'plan') {
          wait = '';
          final segs = _segments;
          final akhir = _chainEnd(segs);
          _stopWaiting();
          if (!await _accountGate()) {
            _set('bot', {'phase': 'idle', 'wait': ''});
            return;
          }
          _log('Mulai rencana: level ${segs.first['from']} - '
              '${akhir == 0 ? 'akhir' : akhir}.');
          await _launch(segs.first['from'] as int, akhir);
          return;
        } else if (diLesson(url)) {
          wait = '';
          final n = (_levels ??= LevelMap(_base)).urlToLevel(lessonPlayUrl(url)) ?? 1;
          _stopWaiting();
          if (!await _accountGate()) {
            _set('bot', {'phase': 'idle', 'wait': ''});
            return;
          }
          _log('Mulai tanpa rencana dari level yang dibuka (${n > 1 ? n : '?'}).');
          await _launch(n, 0);
          return;
        } else {
          wait = 'pick';
        }
      }
      _set('bot', {'phase': 'waiting', 'wait': wait, 'needs_login': wait == 'login'});
    } finally {
      _waitBusy = false;
    }
  }

  /// User menyerahkan kendali ke bot (Mulai / Lanjut / popup ditutup):
  /// klik user sebelumnya di halaman jangan dihitung 'user aktif'.
  void _handOver() => _engine?.handOver();

  void _stopWaiting() {
    _waitT?.cancel();
    _waitT = null;
  }

  /// Bot dijeda karena user membuka halaman lain: kembali ke level yang
  /// sedang dikerjakan (rencana / tanpa rencana sama).
  Future<dynamic> _resume() async {
    final e = _engine;
    if (e == null || !running) return {'ok': false};
    final n = e.st.rangeMaxSeen > e.st.levelStart ? e.st.rangeMaxSeen : e.st.levelStart;
    if (n < 1) {
      throw RpcException('unknown', 'Buka level yang mau dikerjakan di halaman ya.');
    }
    e.handOver();
    final ok = await e.gotoLevelUrl(n);
    if (!ok) {
      throw RpcException('unknown', 'Level $n belum dikenal. Buka levelnya di halaman ya.');
    }
    _log('[USER] Lanjut ke level $n.');
    return {'ok': true, 'level': n};
  }

  Future<dynamic> _launch(int mulai, int akhir) async {
    final v = _view;
    if (v == null || v.disposed) {
      _set('bot', {'phase': 'idle', 'wait': ''});
      throw RpcException('not_ready', 'Halaman edclub belum siap.');
    }
    final page = Page(_bridgeFor(v), clock: clock);
    final eng = Engine(
      page: page,
      levels: _levels ??= LevelMap(_base),
      dataDir: _base,
      onLog: _log,
    );
    eng.st
      ..speedWpm = _engineWpm
      ..levelStart = mulai
      ..levelEnd = akhir
      ..rangeJumpDone = mulai <= 1
      ..rangeReady = true;
    eng.askLocked = _askLocked;
    eng.starTarget = (kind, assign) => _starTargetFor(eng, kind: kind, assign: assign);
    eng.levelKind = (kind) => _recordKind(eng, kind);
    eng.levelKnown = () {
      final l = _levelNow(eng);
      return l <= 0 || _snap['catalog']!.containsKey('$l');
    };
    eng.manual = (kind) => _manualOn
        ? (
            wpm: (_snap['speed']!['wpm'] as int?) ?? 400,
            acc: (_snap['speed']!['acc'] as int?) ?? 100,
          )
        : null;
    if (mulai > 1 || akhir > 0) {
      _log('Rentang level aktif: $mulai - ${akhir == 0 ? 'akhir kursus' : akhir}.');
    }
    _engine = eng;
    _page = page;
    _set('bot', {'phase': 'starting', 'wait': '', 'error': ''});
    _set('range', {'start': mulai, 'end': akhir});
    // fokus ke halaman: klik tombol Mulai mem-blur webview, dan blur
    // dihitung 'user aktif' oleh pengawas (bot bisa menunggu 25 dtk)
    v.focus().catchError((_) {});
    try {
      await page.attach();
      await page.cdp('Network.enable', _netBuffers).catchError((_) => <String, dynamic>{});
      _netSub = page.bridge
          .listen('Network.responseReceived')
          .listen((e) {
        eng.onNetworkResponse(e.params);
        final r = e.params['response'];
        final h = r is Map ? Uri.tryParse('${r['url'] ?? ''}')?.host ?? '' : '';
        if (h.isNotEmpty) _hosts[h] = (_hosts[h] ?? 0) + 1;
      }, onError: (_) {});
    } catch (e) {
      _log('[BOT] gagal menyambung ke halaman: $e');
    }
    _poll = Timer.periodic(pollInterval, (_) => _tick());
    _keepAwake(true);
    _memT?.cancel();
    _hosts.clear();
    unawaited(_memLog(quiet: true)); // titik awal hitungan CPU
    _memT = Timer.periodic(memLogInterval, (_) => _memLog());
    _run = eng.run().catchError((Object e) {
      _set('bot', {'error': '$e'.length > 200 ? '$e'.substring(0, 200) : '$e'});
      _log('[BOT] berhenti karena error: $e');
    }).whenComplete(_finished);
    _set('bot', {'phase': 'running'});
    return {'started': true};
  }

  void _stop() {
    if (_waitT != null) {
      _stopWaiting();
      _set('bot', {'phase': 'idle', 'wait': '', 'needs_login': _urlNeedsLogin});
      return;
    }
    final e = _engine;
    if (e == null || !running) return;
    e.st.stop = true;
    _set('bot', {'phase': 'stopping'});
  }

  Future<void> _finished() async {
    _keepAwake(false);
    _poll?.cancel();
    _poll = null;
    _memT?.cancel();
    _memT = null;
    unawaited(_memLog());
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
    _set('plan', {'active': null, 'lock_until': null, 'done_in_active': 0, 'cur': null});
    _set('level', {'progress': 0.0});
    _log('Bot berhenti.');
  }

  /// Tunggu sampai loop bot benar2 selesai (tes / tutup app).
  Future<void> get stopped => _run ?? Future.value();

  /// Mode Manual aktif: tanpa rencana & mode 'manual' (rencana selalu
  /// pakai target bintang tiap bagian).
  bool get _manualOn => _mode != 'plan' && _snap['free']?['mode'] == 'manual';

  /// Kecepatan jalur ketik biasa: dial di mode Manual, selain itu
  /// maksimal (mode bintang: kecepatan & akurasi otomatis, platinum =
  /// secepatnya). Selama rencana jalan _mode = 'plan'.
  int get _engineWpm =>
      _manualOn ? ((_snap['speed']!['wpm'] as int?) ?? 400) : 400;

  /// Keadaan tombol kecepatan (UI):
  /// - locked: dial terkunci (mode bintang / rencana jalan)
  /// - auto: bintang target (0 = platinum), auto_wpm: wpm lesson ini
  /// - manual: mode Manual aktif; guess = perkiraan level ini (null =
  ///   belum terbaca), note = alasan tanpa perkiraan / batas yang dinaikkan
  void _syncSpeedLock() {
    final e = running ? _engine : null;
    final plan = e != null && _mode == 'plan';
    final manual = !plan && _snap['free']?['mode'] == 'manual';
    var tgt = 0;
    var pw = 0.0;
    if (e != null && !manual) {
      tgt = _starTargetFor(e);
      // pola/acak: target level ini kalau sudah dapat giliran
      final cur = _snap['plan']?['cur'];
      if (tgt < 0 && cur is Map && cur['level'] == _levelNow(e)) {
        tgt = engineTarget((cur['code'] as num).toInt());
      }
      pw = e.st.paceWpm;
    } else if (!manual) {
      final f = _snap['free'];
      if (f != null && f['silver'] != true) tgt = ((f['stars'] as num?) ?? 5).toInt();
    }
    Map<String, dynamic>? guess;
    var note = '';
    final g = e?.st.lessonGoal;
    if (manual && g != null) {
      final sp = _snap['speed']!;
      final mp = guessManual(g, (sp['wpm'] as int?) ?? 400, (sp['acc'] as int?) ?? 100);
      if (mp != null) {
        guess = {'stars': mp.stars, 'silver': mp.silver, 'wpm': mp.wpm.round(), 'acc': mp.acc};
        // kalimat utuh, langsung tampil di UI
        note = [
          if (mp.wpmRaised) 'Kecepatan naik ke ${mp.wpm.round()} wpm (minimum level ini).',
          if (mp.accRaised) 'Akurasi naik ke ${mp.acc}% (minimum level ini).',
          if (mp.accFixed) 'Level ini selalu 100%, salah ketik tidak bisa lanjut.',
          if (g['kind'] == 'game' && mp.wpm < ((sp['wpm'] as int?) ?? 400))
            'Game maksimal ${mp.wpm.round()} wpm.',
        ].join(' ');
      } else {
        note = g['kind'] == 'skip' ? 'tidak dinilai bintang' : 'game ini diketik seperti biasa';
      }
    }
    _set('speed', {
      'locked': !manual,
      'auto': tgt,
      // platinum = selalu secepatnya
      'auto_wpm': manual ? 0 : (pw > 0 ? pw.round() : (tgt == 0 ? 400 : 0)),
      'manual': manual,
      'guess': guess,
      'note': note,
      'level': e != null && (guess != null || note.isNotEmpty) ? _levelNow(e) : 0,
    });
  }

  /// Aturan yang berlaku untuk [kind] di level sekarang + kunci tandanya
  /// (null = tidak ada target: platinum).
  (StarRule, String)? _ruleFor(Engine e, String kind) {
    // aturan khusus game hanya berlaku saat rencana jalan
    final plan = _mode == 'plan';
    if (plan && gameKinds.contains(kind)) {
      final g = _gameRule(kind);
      if (!g.follow) return (g, 'g:$kind');
    } else if (plan && kind == 'game' && _gameRuleOn('game')) {
      // game belum terbaca & ada aturan khusus: anggap diatur
      return (StarRule(type: 'random', min: 1, max: 5), 'g:?');
    }
    Map? sg;
    if (plan) {
      final segs = _segments;
      var lvl = _levelNow(e);
      // level belum terbaca (habis reload): pakai level terakhir yang
      // dikenal, jangan jatuh ke perak
      if (lvl == 0) lvl = _starLvl;
      if (lvl > 0) _starLvl = lvl;
      for (final s in segs) {
        final to = s['to'] as int;
        if (lvl >= (s['from'] as int) && (to == 0 || lvl <= to)) {
          sg = s;
          break;
        }
      }
      if (sg == null && lvl == 0 && segs.isNotEmpty) sg = segs.first;
      if (sg == null) return null;
      return (StarRule.fromJson(sg), 'p${sg['from']}');
    }
    sg = _snap['free'];
    if (sg == null) return null;
    return (StarRule.fixed(codeOf(((sg['stars'] as num?) ?? 5).toInt(), sg['silver'] == true)), 'free');
  }

  /// Target bintang level sekarang: 1-5, 0 = perak (secepatnya), -1 =
  /// pola/acak yang belum mendapat giliran (hanya saat [assign] false).
  /// [assign] = level ini dinilai bintang: ambil giliran berikutnya dan
  /// simpan, supaya diulang / dibuka lagi tetap target yang sama.
  int _starTargetFor(Engine e, {String kind = 'lesson', bool assign = false}) {
    final r = _ruleFor(e, kind);
    if (r == null) return 0;
    final (rule, key) = r;
    if (!rule.variable) return engineTarget(rule.code);
    if (key == 'g:?') return -1;
    final acct = accounts.active() ?? '';
    final sig = rule.sig(key);
    final lvl = _levelNow(e) > 0 ? _levelNow(e) : _starLvl;
    final lk = lvl > 0 ? '$lvl' : 'u:${e.st.statusUrl}';
    final seq = _seqFor(acct);
    final cur = Map<String, dynamic>.from((seq[sig] as Map?) ?? const {});
    final lv = Map<String, dynamic>.from((cur['lv'] as Map?) ?? const {});
    var idx = (lv[lk] as num?)?.toInt();
    if (idx == null) {
      if (!assign) return -1;
      idx = ((cur['n'] as num?) ?? 0).toInt();
      lv[lk] = idx;
      seq[sig] = {'n': idx + 1, 'lv': lv};
      _saveSeq(acct, seq);
      final code = rule.at(idx, '$acct|$sig');
      final siapa = gameKinds.contains(kind) ? '${gameNames[kind]!.toLowerCase()} ke-${idx + 1}' : 'level berbintang ke-${idx + 1}';
      _log('[Bintang] ${lvl > 0 ? 'level $lvl' : 'level ini'}: ${rule.label}, $siapa -> '
          'target ${codeLabel(code)}');
    }
    final code = rule.at(idx, '$acct|$sig');
    if (assign || lvl > 0) {
      _set('plan', {
        'cur': {'level': lvl, 'code': code, 'kind': kind}
      });
    }
    return engineTarget(code);
  }

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
            : (st.userLepas || st.waitUserUrl.isNotEmpty)
                ? 'paused'
                : 'running';
    _syncSpeedLock();
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
    // mode tanpa rencana: rencana tidak dipakai & tidak dikunci
    if (!jalan || lvl == 0 || _mode != 'plan') {
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

  // ------------------------------------------------------------ lisensi (N4)
  // Port alur sidecar/engine_backend.py (_net_boot dst). Kontrak server
  // sama persis (server/API.md).
  String get _licPath => '$_base${Platform.pathSeparator}license.dat';
  Api get _api => _apiOverride ?? (_apiCache ??= Api.resolve(dataDir: _base, version: _version));

  String? _mcCache;
  String _mc() => _mcCache ??= _machineCode();

  /// mc utk tanya server: token sah membawa mc yang disetujui. Kalau sidik
  /// jari v4 ternyata beda dgn 3.5.x, pakai mc token supaya lisensi lama
  /// tidak dianggap dicabut (dicatat di log utk diperiksa).
  String _mcFor(Map<String, dynamic>? tok) {
    final mine = _mc();
    final t = tok == null ? '' : '${tok['mc'] ?? ''}';
    if (t.isNotEmpty && t != mine) {
      _log('[LISENSI] kode mesin v4 ($mine) beda dgn token ($t) - pakai kode token');
      return t;
    }
    return mine;
  }

  /// Lisensi MESIN (3.5.x): v4 hanya memakainya sebagai 'jatah akun
  /// pertama' & token unduh pembaruan. Tidak lagi mengunci UI.
  void _licOk(Map<String, dynamic> tok) {
    _tok = tok;
  }

  void _saveTok(Map<String, dynamic> tok) {
    try {
      Directory(_base).createSync(recursive: true);
      lic.saveToken(_licPath, tok);
    } catch (_) {}
  }

  Future<void> _netBoot() async {
    try {
      await _licenseOnline();
    } catch (e) {
      _log('[net] lisensi online gagal: $e');
      _licenseLocal();
    }
    try {
      await _updateCheck();
    } catch (e) {
      _log('[net] cek pembaruan gagal: $e');
    }
  }

  void _licenseLocal() {
    final tok = lic.loadToken(_licPath);
    if (tok != null && lic.verifyToken(tok)) _licOk(tok);
  }

  Future<void> _licenseOnline() async {
    final tok = lic.loadToken(_licPath);
    if (tok != null && lic.verifyToken(tok)) {
      final data = await lic.fetchStatus(_api, _mcFor(tok));
      if (data['status'] == 'approved') {
        var t = tok;
        if (data['token'] is Map) {
          t = Map<String, dynamic>.from(data['token'] as Map);
          _saveTok(t);
        }
        _licOk(t);
      } else {
        _tok = null; // mesin dicabut: tidak jadi jatah akun pertama
      }
      return;
    }
    if (lic.licenseValid(_licPath, _mc())) {
      // kunci manual lama masih sah: minta token di latar (jatah akun pertama)
      final nick = '${_settings['nickname'] ?? ''}'.isNotEmpty ? '${_settings['nickname']}' : 'pemilik-lama';
      final data = await lic.requestApproval(_api, _mc(), nick, _version);
      if (data['status'] == 'approved' && data['token'] is Map) {
        final t = Map<String, dynamic>.from(data['token'] as Map);
        _saveTok(t);
        _tok = t;
      }
      return;
    }
    final awal = await lic.fetchStatus(_api, _mc());
    if (awal['status'] == 'approved' && awal['token'] is Map) {
      final t = Map<String, dynamic>.from(awal['token'] as Map);
      _saveTok(t);
      _licOk(t);
    }
  }

  // ---------------------------------------------- lisensi per akun (v4)
  // id lisensi akun = 'a' + user_id edclub. Server memperlakukannya sama
  // dgn kode mesin (status/permintaan/token Ed25519 'v1|id|exp'). Token
  // disimpan per id di lisensi-akun.json: akun dihapus dari app lalu login
  // lagi = token masih ada (dan server tetap menyetujuinya).
  String get _acctLicPath => '$_base${Platform.pathSeparator}lisensi-akun.json';
  String? _licAid; // id akun yang sedang diperiksa / diminta
  String _edclubName = ''; // nama akun edclub (utk halaman admin)

  Map<String, dynamic> _acctToks() {
    try {
      return (jsonDecode(File(_acctLicPath).readAsStringSync()) as Map).cast<String, dynamic>();
    } catch (_) {
      return {};
    }
  }

  void _saveAcctTok(String aid, Map<String, dynamic> tok) {
    try {
      Directory(_base).createSync(recursive: true);
      File(_acctLicPath).writeAsStringSync(jsonEncode({..._acctToks(), aid: tok}));
    } catch (_) {}
  }

  /// Token apa saja yang sah (mesin atau akun) - utk unduh pembaruan.
  Map<String, dynamic>? _anyTok() {
    final m = _tok ?? lic.loadToken(_licPath);
    if (m != null && lic.verifyToken(m)) return m;
    for (final t in _acctToks().values) {
      if (t is Map && lic.verifyToken(t)) return t.cast<String, dynamic>();
    }
    return null;
  }

  /// user_id edclub akun yang sedang login (dari respons refresh-tokens
  /// halaman edclub sendiri; sesi tetap utuh, diuji live 22 Nov).
  Future<String?> _edclubAid() async {
    final v = _view;
    if (v == null || v.disposed) return null;
    try {
      final r = await v.cdp('Runtime.evaluate', {
        'expression': '(async () => { try { const r = await fetch('
            "'https://api.edclub.com/j/auth/refresh-tokens', {method: 'POST', "
            "credentials: 'include', headers: {'content-type': 'application/json'}, "
            "body: JSON.stringify({domain: 'www'})}); const j = await r.json(); "
            'return Array.isArray(j) && j[0] && j[0].user_id ? '
            "{id: j[0].user_id, name: j[0].name || ''} : null; "
            '} catch (e) { return null; } })()',
        'awaitPromise': true,
        'returnByValue': true,
      });
      final val = (r['result'] as Map?)?['value'];
      final id = val is Map ? val['id'] : null;
      if (id is num && id > 0) {
        _edclubName = '${(val as Map)['name'] ?? ''}';
        return 'a${id.toInt()}';
      }
    } catch (_) {}
    return null;
  }

  String get _acctLabel {
    final a = accounts.active();
    return a == null ? 'ini' : accounts.labelOf(a);
  }

  /// Gerbang Mulai: akun edclub ini sudah punya lisensi? Belum = minta
  /// (lisensi mesin 3.5.x yang belum dipakai = disetujui otomatis server).
  /// false = jangan jalan (banner lisensi tampil).
  Future<bool> _accountGate() async {
    if (!checkLicense) return true;
    final aid = await _edclubAid();
    if (aid == null) {
      _set('bot', {'error': 'Akun edclub belum terbaca. Coba Mulai lagi sebentar ya.'});
      return false;
    }
    _licAid = aid;
    final label = _acctLabel;
    final tok = _acctToks()[aid];
    if (tok is Map && tok['mc'] == aid && lic.verifyToken(tok)) {
      // cek cepat: dicabut = tolak (server lambat/offline = lanjut)
      String? st;
      try {
        final (_, data) = await _api
            .json('GET', '/api/license/status?mc=$aid', timeout: const Duration(seconds: 3))
            .timeout(const Duration(milliseconds: 1500));
        st = data['status'] as String?;
        if (st == 'approved' && data['token'] is Map) {
          _saveAcctTok(aid, Map<String, dynamic>.from(data['token'] as Map));
        }
      } catch (_) {}
      if (st != null && st != 'approved') {
        _set('license', {'state': 'revoked', 'account': label});
        return false;
      }
      _set('license', {'state': 'ok', 'account': label});
      return true;
    }
    final nick = '${_settings['nickname'] ?? ''}';
    if (nick.isEmpty && _tok == null) {
      _set('license', {'state': 'need', 'account': label, 'nickname': ''});
      return false;
    }
    _set('license', {'state': 'checking', 'account': label});
    return _acctRequest(aid, nick.isEmpty ? 'pemilik-lama' : nick, label);
  }

  /// Kirim permintaan lisensi akun. Disetujui langsung (jatah akun pertama
  /// lisensi mesin) = true.
  Future<bool> _acctRequest(String aid, String nick, String label) async {
    Map<String, dynamic> data;
    int code;
    try {
      final m = _tok;
      final (c, d) = await _api.json('POST', '/api/license/request', body: {
        'mc': aid,
        'nickname': nick,
        'account_name': _edclubName.isNotEmpty ? _edclubName : label,
        'app_version': _version,
        if (m != null && lic.verifyToken(m)) 'mtok': m,
      });
      data = d;
      code = c;
    } on Unreachable {
      _set('license', {'state': 'ok', 'account': label});
      _set('bot', {'error': 'Server lisensi tidak terjangkau. Cek internet lalu coba lagi ya.'});
      return false;
    }
    if (data['status'] == 'approved' && data['token'] is Map) {
      _saveAcctTok(aid, Map<String, dynamic>.from(data['token'] as Map));
      _log('[LISENSI] akun $label aktif.');
      _set('license', {'state': 'ok', 'account': label});
      return true;
    }
    if (data['status'] == 'revoked' || data['status'] == 'denied' || data['status'] == 'rejected') {
      _set('license', {'state': 'revoked', 'account': label});
      return false;
    }
    if (data['status'] != 'pending') {
      // bukan jawaban server lisensi (halaman galat / diblokir / kosong):
      // dulu dianggap 'terkirim' padahal tak tercatat di halaman admin
      // (uji Mac mini 4.0.8)
      _log('[LISENSI] permintaan akun $label gagal: HTTP $code, jawaban '
          '${data.isEmpty ? 'bukan JSON' : data.keys.join(',')}');
      _set('license', {'state': 'need', 'account': label, 'nickname': nick});
      _set('bot', {'error': 'Permintaan izin gagal terkirim (HTTP $code). Coba lagi sebentar ya.'});
      return false;
    }
    _log('[LISENSI] akun $label menunggu persetujuan.');
    _set('license', {'state': 'pending', 'account': label, 'nickname': nick});
    unawaited(_waitApproval());
    return false;
  }

  Future<dynamic> _licenseRequest(String nickname) async {
    final nick = nickname.trim();
    if (nick.length < 2) {
      throw RpcException('bad_input', 'Nama panggilan minimal 2 huruf.');
    }
    _saveSettings({'nickname': nick});
    final aid = _licAid;
    if (aid == null) throw RpcException('later', 'Tekan Mulai dulu ya.');
    await _acctRequest(aid, nick, _acctLabel);
    return {};
  }

  /// Tunggu pemilik menyetujui (poll 5 dtk, maks 30 menit).
  Future<void> _waitApproval() async {
    final run = ++_approvalRun;
    final batas = DateTime.now().add(const Duration(minutes: 30));
    while (DateTime.now().isBefore(batas)) {
      await Future<void>.delayed(const Duration(seconds: 5));
      if (_closed || run != _approvalRun) return;
      Map<String, dynamic> data;
      final aid = _licAid;
      if (aid == null) return;
      try {
        data = await lic.fetchStatus(_api, aid);
      } catch (_) {
        continue;
      }
      final st = data['status'];
      if (st == 'approved' && data['token'] is Map) {
        _saveAcctTok(aid, Map<String, dynamic>.from(data['token'] as Map));
        _set('license', {'state': 'ok', 'account': _acctLabel, 'approved': true});
        return;
      }
      if (st == 'rejected' || st == 'revoked' || st == 'denied') {
        _set('license', {'state': 'revoked'});
        return;
      }
    }
    _set('license', {'state': 'need'});
  }

  /// Cek berkala: diam saja kalau gagal / sedang mengunduh / siap pasang.
  Future<void> _updateTick() async {
    final ph = '${_snap['update']!['phase'] ?? 'idle'}';
    if (_closed || ph == 'downloading' || ph == 'ready') return;
    try {
      await _updateCheck();
    } catch (e) {
      _log('[net] cek pembaruan berkala gagal: $e');
    }
  }

  @visibleForTesting
  Future<void> updateTickForTest() => _updateTick();

  Future<dynamic> _updateCheck() async {
    // rilis di server = TypingBot.exe Windows; Mac ambil dari rilis GitHub
    // (aset TypingBot-mac.zip). Tes (api disuntik) tetap jalur biasa.
    final mac = Platform.isMacOS && _apiOverride == null;
    Map<String, dynamic>? info;
    if (mac) {
      try {
        final r = await _api.latestMacRelease();
        if (r != null && isNewer('${r['version']}', _version)) info = r;
      } on Unreachable {
        info = null;
      }
    } else {
      info = await checkUpdate(_api, _version);
    }
    if (info == null) {
      _set('update', {'available': false});
      return _snap['update'];
    }
    final tok = _anyTok();
    if (tok == null) {
      _log('[net] pembaruan ada tapi belum ada lisensi yang disetujui');
      return _snap['update'];
    }
    _updateInfo = info;
    _set('update', {
      'available': true,
      'version': '${info['version'] ?? ''}',
      'notes': '${info['notes'] ?? ''}',
      'size': (info['size'] as num?)?.toInt() ?? 0,
    });
    return _snap['update'];
  }

  /// Info rilis terakhir yang ditawarkan (N6 memakainya utk unduh).
  Map<String, dynamic>? get updateInfo => _updateInfo;

  bool _dlCancel = false;
  String? _dlPath;

  /// N6: unduh TypingBot.exe rilis (pembawa: exe + zip app) ke folder
  /// update, cek sha256. Jalur: server (token) lalu GitHub langsung, sama
  /// dgn 3.5.x. Progres lewat snapshot 'update'.
  Future<dynamic> _updateDownload() async {
    final info = _updateInfo;
    if (info == null) throw RpcException('later', 'Belum ada versi baru.');
    if (_snap['update']!['phase'] == 'downloading') return _snap['update'];
    final ver = '${info['version'] ?? ''}';
    final dir = Directory('$_base${Platform.pathSeparator}update');
    try {
      if (dir.existsSync()) dir.deleteSync(recursive: true);
      dir.createSync(recursive: true);
    } catch (_) {}
    final mac = Platform.isMacOS && _apiOverride == null;
    final dest = '${dir.path}${Platform.pathSeparator}TypingBot-$ver.${mac ? 'zip' : 'exe'}';
    _dlCancel = false;
    _dlPath = null;
    _set('update', {'phase': 'downloading', 'progress': 0.0, 'error': ''});
    unawaited(() async {
      final tok = _anyTok();
      final size = (info['size'] as num?)?.toInt();
      final want = '${info['sha256'] ?? ''}';
      final jalur = mac
          ? ['${info['url'] ?? ''}']
          : [
        if (tok != null)
          '/api/download?t=${Uri.encodeComponent(base64Encode(utf8.encode(jsonEncode(tok))))}',
        'https://github.com/ZafranHulaif/typingclubrobot/releases/download/v$ver/TypingBot.exe',
      ];
      var terakhir = 0.0;
      for (final u in jalur) {
        try {
          final h = await _api.download(u, dest, timeout: const Duration(seconds: 120),
              progress: (got, total) {
            final t = total ?? size;
            if (t != null && t > 0) {
              final p = (got / t).clamp(0.0, 1.0);
              if (p - terakhir >= 0.01) {
                terakhir = p;
                _set('update', {'progress': p});
              }
            }
            return !_dlCancel;
          });
          if (want.isNotEmpty && h != want) {
            _log('[UPDATE] hash unduhan tidak cocok (${u.startsWith('/') ? 'server' : 'GitHub'})');
            try {
              File(dest).deleteSync();
            } catch (_) {}
            continue;
          }
          _dlPath = dest;
          _log('[UPDATE] versi $ver terunduh.');
          _set('update', {'phase': 'ready', 'progress': 1.0});
          return;
        } on Cancelled {
          _set('update', {'phase': 'idle', 'progress': 0.0});
          return;
        } catch (e) {
          _log('[UPDATE] unduh gagal lewat ${u.startsWith('/') ? 'server' : 'GitHub'}: $e');
        }
      }
      _set('update', {
        'phase': 'idle',
        'progress': 0.0,
        'error': 'Unduhan gagal. Cek internet lalu coba lagi ya.',
      });
    }());
    return _snap['update'];
  }

  /// Jalankan pembawa dgn --update (dia menunggu app ini tutup, memasang,
  /// lalu membuka versi baru), lalu keluar.
  Future<dynamic> _updateInstall() async {
    final p = _dlPath;
    if (p == null || !File(p).existsSync()) {
      throw RpcException('later', 'Unduh pembaruannya dulu ya.');
    }
    if (busy) throw RpcException('busy', 'Stop bot dulu ya.');
    if (Platform.isMacOS && _apiOverride == null) {
      await _macInstall(p);
    } else {
      // folder kerja = folder unduhan, BUKAN folder app (warisan): pemasang
      // tak bisa me-rename folder app selama jadi folder kerjanya
      await Process.start(p, ['--update', '--wait', '$pid'],
          workingDirectory: File(p).parent.path, mode: ProcessStartMode.detached);
    }
    _log('[UPDATE] memasang versi baru, app ditutup.');
    Timer(const Duration(milliseconds: 400), () => exit(0));
    return {'ok': true};
  }

  /// macOS: skrip kecil menunggu app tutup, membongkar zip, menukar
  /// TypingBot.app (lama disimpan dulu, dibalikkan kalau gagal), lalu
  /// membuka versi baru.
  Future<void> _macInstall(String zip) async {
    // .../TypingBot.app/Contents/MacOS/TypingBot -> .../TypingBot.app
    final exe = File(Platform.resolvedExecutable);
    final app = exe.parent.parent.parent.path;
    if (!app.endsWith('.app')) {
      throw RpcException('later', 'Lokasi app tidak dikenali, unduh manual dari GitHub ya.');
    }
    // dari .dmg / salinan tersembunyi macOS (App Translocation): read-only
    if (app.startsWith('/Volumes/') || app.contains('/AppTranslocation/')) {
      throw RpcException('later',
          'Pindahkan TypingBot ke folder Applications dulu ya, lalu buka dari sana.');
    }
    final sh = File('$_base${Platform.pathSeparator}update${Platform.pathSeparator}pasang.sh');
    sh.writeAsStringSync(macInstallScript(app: app, zip: zip, pid: pid));
    await Process.start('/bin/bash', [sh.path], mode: ProcessStartMode.detached);
  }

  Future<dynamic> _report(String category, String text) async {
    final akun = '${_snap['account']!['active'] ?? ''}';
    final isi = buildReport(
      version: _version,
      account: akun.isEmpty ? '?' : akun,
      category: category,
      text: text,
      logTail: _tail(400),
    );
    final r = await sendReport(_api, version: _version, account: akun.isEmpty ? '?' : akun, isi: isi);
    if (r.sent) {
      _log('[LAPOR] terkirim otomatis.');
      return {'sent': true};
    }
    _log('[LAPOR] kirim otomatis gagal${r.savedTo != null ? ', disimpan: ${r.savedTo}' : ''}');
    throw RpcException('offline', r.savedTo != null
        ? 'Gagal terkirim. Laporan disimpan di Desktop, kirim manual ya.'
        : 'Gagal terkirim. Coba lagi nanti ya.');
  }

  @override
  void close() {
    _closed = true;
    _engine?.st.stop = true;
    _poll?.cancel();
    _memT?.cancel();
    _stopWaiting();
    _gateRun++;
    _rtT?.cancel();
    _updT?.cancel();
    _holdT?.cancel();
    _revealT?.cancel();
    _viewSub?.cancel();
    _view?.dispose().catchError((_) {});
  }
}

/// Skrip pasang pembaruan macOS (dites terpisah).
String macInstallScript({required String app, required String zip, required int pid}) {
  String q(String x) => "'${x.replaceAll("'", "'\\''")}'";
  return [
    '#!/bin/bash',
    'APP=${q(app)}',
    'ZIP=${q(zip)}',
    'for i in \$(seq 1 100); do kill -0 $pid 2>/dev/null || break; sleep 0.2; done',
    'T=\$(mktemp -d)',
    r'if ! ditto -x -k "$ZIP" "$T" || [ ! -d "$T/TypingBot.app" ]; then open "$APP"; exit 1; fi',
    r'rm -rf "$APP.lama"',
    r'if ! mv "$APP" "$APP.lama"; then open "$APP"; exit 1; fi',
    r'if ! mv "$T/TypingBot.app" "$APP"; then mv "$APP.lama" "$APP"; open "$APP"; exit 1; fi',
    r'xattr -dr com.apple.quarantine "$APP" 2>/dev/null',
    r'rm -rf "$APP.lama" "$T" "$ZIP"',
    r'open "$APP"',
    '',
  ].join('\n');
}
