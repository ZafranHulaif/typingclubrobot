// Port engine/session.py: deteksi & patroli sesi login edclub (mode
// WebView2: tanpa tab cadangan, tanpa redirect pulang-pergi).
part of 'engine.dart';

final _sesiPathRe = RegExp(sesiPathRe, caseSensitive: !sesiPathReIgnoreCase);
final _areaStudentRe = RegExp(r'/(student|sportal)/');

extension Session on Engine {
  /// Sentinel 401/403: respons XHR/fetch edclub (CDP Network.*).
  /// Dipanggil backend utk tiap Network.responseReceived.
  void onNetworkResponse(Map<String, dynamic> p) {
    try {
      final type = '${p['type'] ?? ''}';
      if (type != 'XHR' && type != 'Fetch') return;
      final resp = p['response'];
      if (resp is! Map) return;
      final status = (resp['status'] as num?)?.toInt() ?? 0;
      if (status != 401 && status != 403) return;
      final u = Uri.tryParse('${resp['url'] ?? ''}');
      if (u == null) return;
      final host = u.host.toLowerCase();
      if (!(host.endsWith('edclub.com') || host.endsWith('typingclub.com'))) return;
      final ls = st.loginSentinel;
      final t = now;
      if (status == 401) {
        final path = u.path.isEmpty ? '/' : u.path;
        ls.terakhir401 = t;
        ls.path401[path] = t;
        ls.path401.removeWhere((_, v) => t - v > 120);
        if (t - ls.log401 > 30) {
          ls.log401 = t;
          log('[LOGIN] catatan: API balas 401 (${path.length > 60 ? path.substring(0, 60) : path})');
        }
        // 401 tunggal endpoint acak bukan tanda sesi mati
        if (_sesiPathRe.hasMatch(path) || ls.path401.length >= 3) {
          ls.ok = false;
          ls.alasan = 'API edclub 401 (${path.length > 40 ? path.substring(0, 40) : path})';
        }
      } else {
        // 403 butuh 2x dalam 60 dtk
        if (t - ls.gagal403 < 60) {
          ls.ok = false;
          ls.alasan = 'API edclub berulang 403';
        }
        ls.gagal403 = t;
      }
    } catch (_) {}
  }

  /// 'in' / 'out' / null dari penanda DOM halaman aktif.
  Future<String?> loginProfile() async {
    final r = await runJs(profileCheckJs, page.mainFrame);
    return r is String ? r : null;
  }

  /// Cek sesi lewat fetch same-origin (nol navigasi). 'in'/'out'/''/null.
  Future<String?> probeFetchLogin([double timeoutS = 9.0]) async {
    final batas = now + timeoutS;
    while (now < batas) {
      dynamic r;
      try {
        r = await page.evaluate(probeFetchLoginJs);
      } catch (_) {
        return null;
      }
      if (r == 'in' || r == 'out') return r as String;
      await sleep(2.0);
    }
    return '';
  }

  /// Gerbang start (mode WebView2): baca penanda di halaman aktif
  /// berulang sampai pasti; 'out' harus stabil 2x (hydration race).
  /// TANPA redirect (dilarang di mode embedded: kilatan di dalam app).
  Future<String?> probeRedirectLogin([double timeoutS = 14.0]) async {
    if (!await page.alive()) return null;
    final batas = now + timeoutS;
    var outHitung = 0;
    while (now < batas) {
      final r = await runJs(profileCheckJs, page.mainFrame);
      if (r == 'in') return 'in';
      if (r == 'out') {
        outHitung += 1;
        if (outHitung >= 2) return 'out';
      } else {
        outHitung = 0;
      }
      final low = page.url.toLowerCase();
      if (low.contains('signin') || low.contains('login') || low.contains('signup')) {
        return 'out';
      }
      if (st.stop) return null;
      await sleep(0.8);
    }
    return null;
  }

  /// sesi_edclub.json berisi cookie identitas?
  bool sesiPunyaIdentitas() {
    final d = dataDir;
    if (d == null) return false;
    try {
      final f = File('$d${Platform.pathSeparator}sesi_edclub.json');
      final m = jsonDecode(f.readAsStringSync()) as Map;
      final nama = {for (final c in (m['cookies'] as List? ?? const [])) '${(c as Map)['name']}'};
      return nama
          .intersection(const {'pw_uuid', 'connectId', 'tb_lt', '_cc_id', '_lc2_fpi', '_pubcid', '_sharedid'})
          .isNotEmpty;
    } catch (_) {
      return false;
    }
  }

  /// Patroli berkala dari loop utama: set/bersihkan needsLogin.
  Future<void> loginPatrol(String url) async {
    final t = now;
    final jeda = st.needsLogin ? 3.0 : 8.0;
    if (t - st.loginCkTerakhir < jeda) return;
    st.loginCkTerakhir = t;
    final ls = st.loginSentinel;
    var profil = await loginProfile();
    final low = url.toLowerCase();
    final diLogin = looksLikeLogin(low);
    final diEdclub = low.contains('edclub') || low.contains('typingclub');
    // area student hanya terjangkau saat login = bukti positif
    if (profil == null && !diLogin && _areaStudentRe.hasMatch(low)) profil = 'in';
    if (profil == null && !diLogin && diEdclub && !ls.pernahIn && !st.loginSeedCek) {
      st.loginSeedCek = true;
      if (sesiPunyaIdentitas()) {
        ls.pernahIn = true;
        profil = 'in';
        log('[LOGIN] sesi tersimpan ber-cookie identitas - '
            'gerbang login langsung terbuka.');
      }
    }
    // tanpa penanda: mode WebView2 hanya boleh fetch same-origin
    if (profil == null &&
        !diLogin &&
        diEdclub &&
        (st.needsLogin || !st.loginDicek) &&
        t - st.probeTabCk > (st.needsLogin ? 60.0 : 30.0)) {
      st.probeTabCk = t;
      if (st.needsLogin) {
        final r = await probeFetchLogin();
        profil = (r == 'in' || r == 'out') ? r : null;
      } else {
        profil = await probeRedirectLogin();
      }
    }
    if (profil == 'in') {
      ls.pernahIn = true;
      if (!ls.ok || st.needsLogin) {
        ls.ok = true;
        ls.alasan = '';
        ls.path401.clear();
      }
    }
    var mati = (diLogin || !ls.ok || profil == 'out') && profil != 'in';
    if (profil != null) {
      ls.unknownMulai = 0;
    } else if (!mati && !st.needsLogin) {
      if (diEdclub && !diLogin) {
        if (ls.unknownMulai == 0) {
          ls.unknownMulai = t;
          log('[LOGIN] Status login belum terbaca '
              '(url=${low.length > 72 ? low.substring(0, 72) : low}) - menunggu...');
        } else if (t - ls.unknownMulai > 12.0) {
          if (ls.pernahIn) {
            st.loginDicek = true;
            ls.unknownMulai = 0;
            log("[LOGIN] halaman ini tak punya penanda (tampilan lama?) - "
                "percaya sesi 'in' yang sudah terverifikasi.");
          } else {
            ls.ok = false;
            ls.alasan = 'login tidak terdeteksi >12 dtk';
            mati = true;
          }
        }
      } else {
        ls.unknownMulai = 0;
      }
    }
    if (mati || profil == 'in' || profil == 'out') st.loginDicek = true;
    if (mati && !st.needsLogin) {
      st.needsLogin = true;
      log('[LOGIN] Sesi edclub tidak aktif'
          '${ls.alasan.isNotEmpty ? ' (${ls.alasan})' : ''}'
          '. Login di jendela browser bot - bot menunggu di sini.');
    } else if (st.needsLogin && profil == 'in') {
      st.needsLogin = false;
      ls.ok = true;
      ls.alasan = '';
      log('[LOGIN] Sesi edclub aktif kembali - lanjut.');
    }
    if (st.needsLogin && st.askLoginNav) {
      st.askLoginNav = false;
      final tujuan = st.askLoginUrl.isNotEmpty ? st.askLoginUrl : loginUrlIndividual;
      try {
        await page.goto(tujuan, timeout: 25);
        log('[LOGIN] Halaman login dibuka: $tujuan');
      } catch (e) {
        log('[LOGIN] Gagal membuka halaman login: ${'$e'.length > 60 ? '$e'.substring(0, 60) : e}');
      }
    }
  }
}
