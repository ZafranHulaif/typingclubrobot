// Backend di dalam proses (Windows): pengganti sidecar Python.
// N1: halaman edclub di WebView2 native, login Google di dalam app,
// ganti/tambah/keluar akun. Mesin bot (N3), lisensi & update (N4)
// menyusul - metodenya menjawab pesan ramah "belum ada".
//
// Bicara dgn UI lewat protokol yang sama dgn sidecar (snapshot/state +
// request), jadi UI tidak tahu bedanya.
import 'dart:async';

import '../bridge/bridge.dart';
import '../web/js_init.dart';
import '../web/web_host.dart';
import 'accounts.dart';

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

class NativeBackend implements Backend {
  NativeBackend({
    required String version,
    WebHost? host,
    AccountStore? accounts,
    this.revealTimeout = const Duration(seconds: 20),
  })  : host = host ?? webHost,
        accounts = accounts ?? AccountStore(AccountStore.defaultBase()) {
    _snap = {
      'app': {'version': version, 'platform': 'windows', 'mode': 'native'},
      'bot': {'phase': 'idle', 'needs_login': false},
      'level': <String, dynamic>{},
      'range': <String, dynamic>{},
      'speed': {'wpm': 400},
      'account': {'active': '', 'list': <Map<String, dynamic>>[]},
      // lisensi asli menyusul (N4); versi uji tidak dikunci
      'license': {'state': 'ok'},
      'update': <String, dynamic>{},
      'cover': {'visible': true, 'text': 'Menyiapkan edclub...'},
      'plan': {'segments': <Map<String, dynamic>>[]},
      'web': {'url': '', 'title': ''},
    };
  }

  final WebHost host;
  final AccountStore accounts;
  final Duration revealTimeout;

  late final Map<String, Map<String, dynamic>> _snap;
  final _events = StreamController<SidecarEvent>.broadcast();
  final _asks = StreamController<SidecarAsk>.broadcast();
  final _link = StreamController<LinkState>.broadcast();
  LinkState _state = LinkState.connecting;

  WebView? _view;
  StreamSubscription<WebEvent>? _viewSub;
  Timer? _revealT;
  bool _occluded = false;
  bool _switching = false;

  WebView? get view => _view;

  @override
  Stream<SidecarEvent> get events => _events.stream;
  @override
  Stream<SidecarAsk> get asks => _asks.stream;
  @override
  Stream<LinkState> get link => _link.stream;
  @override
  LinkState get state => _state;

  bool get _coverOn => _snap['cover']!['visible'] == true;

  // ------------------------------------------------------------ state
  void _set(String key, Map<String, dynamic> fields) {
    _snap[key] = {..._snap[key]!, ...fields};
    _events.add(SidecarEvent('state', {key: _snap[key]}));
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

  // ------------------------------------------------------------ boot
  @override
  Future<void> connect() async {
    _events.add(SidecarEvent('snapshot', {..._snap}));
    _state = LinkState.online;
    _link.add(_state);
    _refreshAccounts();
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
    final needsLogin = u != null &&
        u.host.contains('edclub') &&
        u.path.contains('/signin');
    if (_snap['bot']!['needs_login'] != needsLogin) {
      _set('bot', {'needs_login': needsLogin});
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
        return _guard(() async {
          accounts.setActive(name);
          _refreshAccounts();
          await _open(name);
          return _snap['account'];
        });
      case 'acct.add':
        return _guard(() async {
          final name = accounts.newName();
          accounts.setActive(name);
          await _open(name, url: signinUrl);
          _refreshAccounts();
          return _snap['account'];
        });
      case 'acct.logout':
        return _logout();
      case 'login.open':
        await _view?.navigate(signinUrl);
        return true;
      case 'web.visible':
        _occluded = p['on'] != true;
        _applyVisible();
        return true;
      case 'speed.set':
        final w = (p['wpm'] as num?)?.toInt() ?? 400;
        _set('speed', {'wpm': w});
        return {'wpm': w};
      case 'plan.set':
        return _planSet(p['segments']);
      case 'settings.get':
        return const <String, dynamic>{};
      case 'bot.stop':
        return true;
      default:
        throw RpcException('later', 'Bagian ini belum ada di versi uji ini.');
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
    _set('plan', {'segments': out});
    return {'segments': out};
  }

  @override
  void close() {
    _revealT?.cancel();
    _viewSub?.cancel();
    _view?.dispose().catchError((_) {});
  }
}
