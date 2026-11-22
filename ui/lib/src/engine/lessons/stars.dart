// N7: target bintang. Rumus edclub (bundle coreclassictyping, diverifikasi
// live 22 Nov di akun tes: target 0.9 -> skor 450/1000 = 4 bintang):
//   rasio = akurasi% * akurasi_asli% * wpm / (1e4 * max(1, goal + difficulty))
//   bintang: >= 1 -> 5, >= .8 -> 4, >= .6 -> 3, >= .4 -> 2, >= .2 -> 1
//   wpm < min_wpm atau akurasi < min_accuracy -> 0 bintang
//   perak (skor penuh) = rasio >= 2 dengan akurasi 100% (mode biasa bot).
// wpm edclub = karakter BENAR / 5 per menit waktu ketik, jadi bot benar2
// mengetik secepat yang dibutuhkan (data hasil tidak diutak-atik). Salah
// ketik ditambah supaya kecepatan untuk bintang yang sama bisa lebih
// tinggi (lesson lebih cepat selesai), tapi akurasi tetap aman di atas
// batas minimum.
part of '../engine.dart';

final _hurufAz = RegExp(r'^[a-zA-Z]$');

/// Rencana ketik satu lesson untuk target bintang tertentu.
class StarPace {
  StarPace({
    required this.stars,
    required this.wpm,
    required this.errors,
    required this.chars,
    required this.dt,
    required this.ratio,
  });

  final int stars;

  /// wpm bersih (karakter benar) yang dituju
  final double wpm;

  /// jumlah salah ketik yang disengaja
  final int errors;
  final int chars;

  /// jeda antar tombol (detik)
  final double dt;

  /// rasio edclub yang diperkirakan
  final double ratio;

  int get accuracy => chars == 0 ? 100 : (100 * (chars - errors) / chars).floor();
}

/// Tengah pita tiap bintang (jauh dari batas supaya pembulatan aman).
const starMidRatio = {5: 1.4, 4: 0.9, 3: 0.7, 2: 0.5, 1: 0.3};

/// Hitung kecepatan & jumlah salah untuk [stars] bintang. null = tidak
/// perlu diatur (target perak / lesson tanpa target kecepatan).
StarPace? planStars(int stars,
    {required num goal,
    num minWpm = 0,
    num minAcc = 0,
    num difficulty = 0,
    required int chars}) {
  final r = starMidRatio[stars];
  if (r == null || chars <= 0) return null;
  final g = max(1.0, (goal + difficulty).toDouble());
  final minW = max(0.0, (minWpm + difficulty).toDouble());
  // wpm minimal dengan margin (edclub membulatkan wpm)
  final wMin = minW * 1.2 + 0.5;
  // akurasi serendah yang aman: batas + 5 poin, paling rendah 85%
  final accFloor = min(100.0, max(minAcc.toDouble() + 5, 85.0)) / 100;
  // lesson pendek: pembulatan akurasi terlalu kasar, ketik tanpa salah
  var e = chars < 25 ? 0 : (chars * (1 - accFloor)).floor();
  var a = (chars - e) / chars;
  var w = r * g / (a * a);
  if (w < wMin) {
    // terlalu pelan untuk lolos min_wpm: kurangi salah, naikkan kecepatan
    w = wMin;
    final aPerlu = sqrt(r * g / w);
    if (aPerlu >= 1) {
      e = 0;
      a = 1;
    } else {
      e = min(e, (chars * (1 - aPerlu)).floor());
      a = (chars - e) / chars;
    }
    w = max(wMin, r * g / (a * a));
  }
  final valids = chars - e;
  final dt = 60.0 * valids / (5 * w * max(chars - 1, 1));
  final ratio = min(2.0, a * a * min(w, 200) / g);
  return StarPace(stars: stars, wpm: w, errors: e, chars: chars, dt: dt, ratio: ratio);
}

/// Pacing bintang di game (lihat gamePace). false = semua game secepatnya.
const gamePacingOn = true;

/// Game yang sudah diuji live untuk target bintang (22 Nov, akun tes):
/// dicocokkan ke activity.app + host frame (huruf kecil). Game lain
/// (TempleBash/whackamonster, FloatingBubbles/bubbleburster = premium di
/// akun tes, belum bisa diuji) tetap diketik secepatnya.
const gamePaceTypes = ['balloonvalley', 'monsterattack'];

/// Batas atas kecepatan di game: game kalah kalau wpm > 250.
const gamePaceMaxWpm = 150;

/// Rencana bintang satu game. Beda dengan lesson biasa: game berwaktu
/// (balon turun / yeti maju secepat goal_wpm), jadi kecepatan TIDAK boleh
/// di bawah goal. Bintang diatur lewat akurasi asli: huruf salah sekali
/// sebelum huruf benar (game mode blokir: salah tidak maju & tidak
/// menurunkan akurasi, cuma menandai huruf itu bukan benar-pertama-kali).
class GamePace {
  GamePace({required this.stars, required this.ratio, required this.goal, required this.wpm});

  final int stars;

  /// rasio edclub yang dituju (tengah pita bintang)
  final double ratio;

  /// goal_wpm + difficulty (penyebut rumus)
  final double goal;

  /// wpm ketik (bulat: edclub membulatkan wpm, di goal 10 selisih 1 wpm
  /// sudah 8%)
  final double wpm;

  /// jeda antar huruf BENAR (detik)
  double get dt => 12.0 / wpm;

  /// bagian huruf yang harus benar-pertama-kali supaya rasio tercapai
  double get realTarget => min(1.0, ratio * goal / wpm);
}

/// Kecepatan aman untuk [stars] bintang di game: minimal 1.25x goal
/// (balon jatuh ~2x jeda goal, yeti terdorong kalau >= goal), dan cukup
/// cepat supaya target tercapai dengan akurasi asli <= 88% (ada ruang
/// koreksi dua arah). null = tidak diatur.
GamePace? planGame(int stars, {required num goal, num minWpm = 0, num difficulty = 0}) {
  final r = starMidRatio[stars];
  if (r == null) return null;
  final g = max(1.0, (goal + difficulty).toDouble());
  final minW = max(0.0, (minWpm + difficulty).toDouble());
  final w = max(g * max(1.25, r / 0.88), minW * 1.2 + 0.5).ceilToDouble();
  if (w > gamePaceMaxWpm) return null;
  return GamePace(stars: stars, ratio: r, goal: g, wpm: w);
}

/// Loop tertutup: huruf di indeks [idx] perlu diawali salah? [rvBefore] =
/// jumlah huruf benar-pertama-kali sebelum idx (spasi yang dilompati game
/// ikut terhitung, sama seperti per_chr edclub), [valids]/[durationMs] =
/// statistik core saat ini. Pilih yang hasilnya paling dekat ke target.
bool gameMiss(GamePace p,
    {required int idx, required int rvBefore, required int valids, required num durationMs}) {
  // 2 huruf pertama selalu benar (statistik belum berarti)
  if (valids < 2 || idx < 0) return false;
  // wpm seperti yang dihitung edclub (dibulatkan, maks 200); awal game
  // masih kasar -> pakai rencana
  var w = p.wpm;
  if (valids >= 8 && durationMs > 0) {
    w = min(200.0, (valids * 12000.0 / durationMs + 0.5).floorToDouble());
  }
  if (w <= 0) return false;
  final q = p.ratio * p.goal / w;
  return (rvBefore + 0.5) / (idx + 1) > q;
}

extension StarLesson on Engine {
  /// Rencana bintang untuk lesson di [frame] (null = ketik biasa).
  Future<StarPace?> starPace(Frame frame) async {
    // nomor level dibutuhkan target per bagian rencana: setelah reload
    // label belum terbaca -> dulu target jatuh ke perak (400 wpm)
    for (var i = 0; i < 6 && st.statusLabel.isEmpty; i++) {
      try {
        st.statusLabel = await levelLabel();
      } catch (_) {}
      if (st.statusLabel.isEmpty) await sleep(0.3);
    }
    final target = starTarget?.call() ?? 0;
    if (target < 1 || target > 5) return null;
    final info = await runJs(lessonGoalJs, frame);
    if (info is! Map) {
      log('[Bintang] target $target, tapi target kecepatan lesson tidak '
          'terbaca - ketik biasa');
      return null;
    }
    if (_truthy(info['objc']) || _truthy(info['test'])) return null;
    final n = (info['n'] as num?)?.toInt() ?? 0;
    final pos = max((info['pos'] as num?)?.toInt() ?? 0, 0);
    final sisa = n - pos;
    if (sisa < 5) return null;
    // akurasi diatur lewat salah ketik yang maju (on_error 'continue');
    // mode lain (blokir) -> tanpa salah, hanya kecepatan
    final bolehSalah = '${info['on_error']}' == 'continue';
    final p = planStars(target,
        goal: (info['goal'] as num?) ?? 0,
        minWpm: (info['min_wpm'] as num?) ?? 0,
        minAcc: bolehSalah ? ((info['min_acc'] as num?) ?? 0) : 100,
        difficulty: (info['diff'] as num?) ?? 0,
        chars: sisa);
    if (p == null) return null;
    log('[Bintang] target $target: goal ${info['goal']} wpm -> ketik '
        '${p.wpm.toStringAsFixed(1)} wpm, akurasi ${p.accuracy}% '
        '(${p.errors} salah dari ${p.chars}), perkiraan '
        '${(p.chars * p.dt / 60).toStringAsFixed(1)} menit');
    return p;
  }

  /// Ketik sisa lesson sesuai [p]: jadwal jam dinding (tombol ke-k pada
  /// t0 + k*dt) supaya overhead tidak menumpuk, salah ketik di posisi
  /// acak (hanya huruf). Return 'done' | 'stall' | 'gone' | 'stop'.
  Future<String> typePaced(Frame frame, String rem0, StarPace p,
      {String? avoid}) async {
    // posisi salah: acak di [2, chars-3]
    final calon = [for (var i = 2; i < p.chars - 2; i++) i]..shuffle(rnd);
    final salahDi = calon.take(p.errors).toSet();
    var hutang = 0; // salah yang tertunda karena jatuh di bukan-huruf
    var rem = rem0;
    var k = 0;
    double? t0;
    var stall = 0;
    var batchLen = rem.length;
    final huruf = RegExp(r'[a-zA-Z]');
    const papan = 'asdfghjklqwertyuiopzxcvbnm';
    final totalLen = max(rem0.length, 1);
    while (true) {
      if (st.stop) return 'stop';
      if (lessonGone()) return 'gone';
      if (rem.isEmpty) {
        // selesai atau baris berikut belum dirender
        String? got;
        for (var i = 0; i < 16; i++) {
          await sleep(0.05);
          final rr = await readRemaining(frame);
          if (rr != null && rr.isNotEmpty) {
            got = rr;
            break;
          }
        }
        if (got == null) return 'done';
        rem = got;
        batchLen = rem.length;
      }
      final ch = rem[0];
      var key = ch;
      if (salahDi.contains(k)) hutang += 1;
      if (hutang > 0 && huruf.hasMatch(ch)) {
        final c = ch.toLowerCase();
        var w = papan[rnd.nextInt(papan.length)];
        // jangan pakai tombol yang lagi ditahan (level tahan tombol)
        while (w == c || w == avoid) {
          w = papan[rnd.nextInt(papan.length)];
        }
        key = w;
        hutang -= 1;
      }
      try {
        if (key == '\n') {
          await page.keyboard.press('Enter');
        } else if (key == '\t') {
          await page.keyboard.press('Tab');
        } else {
          await page.keyboard.type(key);
        }
      } catch (_) {
        return 'gone';
      }
      t0 ??= now;
      k += 1;
      rem = rem.substring(1);
      // cek halaman tiap 6 tombol (atau di akhir)
      if (k % 6 == 0 || rem.isEmpty) {
        final (r2, _) = await readState(frame);
        if (r2 != null) {
          if (r2.length >= batchLen) {
            stall += 1;
            if (stall == 1 || stall % 3 == 0) {
              if (await closeAdModal()) await sleep(0.25);
              await focusFrame(frame);
            }
            if (stall >= 4) return 'stall';
          } else {
            stall = 0;
          }
          rem = r2;
          batchLen = rem.length;
          st.levelProgress = (1 - rem.length / totalLen).clamp(0.0, 1.0);
        }
      }
      final tunggu = t0 + k * p.dt - now;
      if (tunggu > 0) await sleep(tunggu);
    }
  }

  /// Rencana bintang untuk game di [fr] (sekali per lesson, [s] = hasil
  /// gameStatJs). null = game diberi makan seperti biasa (perak / tanpa
  /// target / game belum teruji).
  Future<GamePace?> gamePace(Frame fr, Map s) async {
    if (!gamePacingOn) return null;
    final url = page.url;
    if (_gamePaceUrl == url) return _gamePace;
    // nomor level dibutuhkan target per bagian rencana (lihat starPace)
    for (var i = 0; i < 6 && st.statusLabel.isEmpty; i++) {
      try {
        st.statusLabel = await levelLabel();
      } catch (_) {}
      if (st.statusLabel.isEmpty) await sleep(0.3);
    }
    _gamePaceUrl = url;
    _gamePace = null;
    _gameReset();
    final target = starTarget?.call() ?? 0;
    if (target < 1 || target > 5) return null;
    if (_truthy(s['objc']) || _truthy(s['test'])) return null;
    final nama = '${s['app']} ${s['host']}'.toLowerCase();
    final label = '${s['app']}'.split('.').last;
    if (!gamePaceTypes.any(nama.contains)) {
      log('[Bintang] target $target, tapi game $label belum teruji untuk '
          'target bintang - diketik secepatnya');
      return null;
    }
    if (!_truthy(s['blok'])) {
      log('[Bintang] target $target, tapi game $label bukan mode blokir - '
          'diketik secepatnya');
      return null;
    }
    final p = planGame(target,
        goal: (s['goal'] as num?) ?? 0,
        minWpm: (s['min_wpm'] as num?) ?? 0,
        difficulty: (s['diff'] as num?) ?? 0);
    if (p == null) {
      log('[Bintang] target $target, tapi goal ${s['goal']} wpm terlalu '
          'tinggi untuk game - diketik secepatnya');
      return null;
    }
    _gamePace = p;
    st.paceWpm = p.wpm;
    log('[Bintang] game $label target $target: goal ${s['goal']} wpm -> ketik '
        '${p.wpm.toStringAsFixed(0)} wpm, akurasi asli '
        '~${(100 * p.realTarget).round()}% (salah sekali sebelum huruf benar)');
    return p;
  }

  /// false = sudah pasti tidak diatur di lesson ini (hemat satu eval per
  /// putaran saat target perak / game belum teruji).
  bool get gamePaceMaybe =>
      gamePacingOn && !(_gamePaceUrl == page.url && _gamePace == null);

  /// Data game belum terbaca (core belum siap): tahan dulu supaya huruf
  /// pertama tidak diketik secepatnya; menyerah setelah 15 putaran.
  bool gamePaceHold() {
    final target = starTarget?.call() ?? 0;
    final url = page.url;
    if (_gameHoldUrl != url) {
      _gameHoldUrl = url;
      _gameHoldN = 0;
    }
    _gameHoldN += 1;
    if (target >= 1 && target <= 5 && _gameHoldN <= 15) return true;
    _gamePaceUrl = url;
    _gamePace = null;
    if (target >= 1 && target <= 5) {
      log('[Bintang] target $target, tapi data game tidak terbaca - '
          'diketik secepatnya');
    }
    return false;
  }

  /// Game tamat: catat hasil yang akan dinilai edclub (sekali per game).
  Future<void> gamePaceEnd(Frame fr) async {
    final p = _gamePace;
    if (p == null || _gamePaceUrl != page.url || _gameK == 0) return;
    final s = await runJs(gameStatJs, fr);
    final k = _gameK, salah = _gameMiss;
    _gameReset();
    if (s is! Map) return;
    final v = (s['v'] as num?) ?? 0, d = (s['d'] as num?) ?? 0;
    final t = (s['t'] as num?) ?? 0;
    final pn = (s['pn'] as num?)?.toInt() ?? 0, prv = (s['prv'] as num?)?.toInt() ?? 0;
    if (d <= 0 || pn <= 0) return;
    final wpm = min(200, (v * 12000 / d + 0.5).floor());
    final acc = t == 0 ? 100 : (100 * v / t).round();
    final real = (100 * prv / pn).ceil();
    final rasio = min(2.0, acc * real * wpm / (1e4 * p.goal));
    final bintang = rasio >= 1 ? 5 : rasio >= .8 ? 4 : rasio >= .6 ? 3 : rasio >= .4 ? 2 : rasio >= .2 ? 1 : 0;
    log('[Bintang] game selesai: $k huruf, $salah salah disengaja, $wpm wpm, '
        'akurasi asli $real% -> rasio ${rasio.toStringAsFixed(2)} = '
        '$bintang bintang (target ${p.stars})');
  }

  void _gameReset() {
    _gameK = 0;
    _gameLastT = 0;
    _gameT0 = 0;
    _gameMiss = 0;
    _gameIdx = -1;
  }

  /// Tunggu sampai jam [t] (dipotong pendek supaya Stop cepat terasa).
  Future<void> _gameWaitUntil(double t) async {
    while (!st.stop) {
      final w = t - now;
      if (w <= 0) return;
      await sleep(min(w, 0.25));
    }
  }

  /// Satu tombol ke core game dengan jeda NYATA sejak tombol sebelumnya
  /// (dibaca BALLOON_FEED_JS lewat window.__tbPace). [salah] = huruf a-z
  /// acak yang bukan huruf sekarang.
  Future<dynamic> _gameFeed(Frame fr, GamePace p, {required bool salah}) async {
    final t = now;
    // jeda panjang (bot dijeda): core edclub sendiri berhenti menghitung
    // setelah 10 dtk diam, jadi dibatasi sama
    final ms = _gameLastT > 0
        ? min(10000, ((t - _gameLastT) * 1000).round())
        : (p.dt * 1000).round();
    final res =
        await runJs('window.__tbPace = {ms: $ms, salah: $salah};\n$balloonFeedJs', fr);
    if (res is Map && _truthy(res['fed'])) {
      _gameLastT = t;
    } else {
      await runJs('window.__tbPace = null; return 1;', fr);
    }
    return res;
  }

  /// Satu huruf game sesuai rencana [p]: huruf benar ke-k pada t0 + k*dt
  /// (jam dinding, overhead tidak menumpuk); kalau perkiraan rasio di atas
  /// target, huruf salah dulu di sela jeda. [s] = gameStatJs terbaru.
  /// Return 'fed' | 'wait' | 'ended' | 'none'.
  Future<String> gamePaceStep(Frame fr, GamePace p, Map s) async {
    if (_truthy(s['ended'])) return 'ended';
    final chr = '${s['chr'] ?? ''}';
    if (chr.isEmpty) {
      // layar mulai: feed JS mengetuk spasi; kalau huruf pertama langsung
      // siap ia masuk sebagai huruf berjadwal (bukan rantai cepat)
      final r = await _gameFeed(fr, p, salah: false);
      if (r is Map && _truthy(r['ended'])) return 'ended';
      if (r is! Map || !_truthy(r['fed'])) return 'wait';
      if (_gameT0 == 0) _gameT0 = _gameLastT;
      _gameK += 1;
      return 'fed';
    }
    final idx = (s['idx'] as num?)?.toInt() ?? 0;
    // game diulang di URL yang sama (Try again): jadwal dari awal
    if (idx < _gameIdx || (!_truthy(s['started']) && _gameK > 0)) _gameReset();
    _gameIdx = idx;
    final dt = p.dt;
    final perluSalah = _truthy(s['cur_rv']) &&
        _hurufAz.hasMatch(chr) &&
        gameMiss(p,
            idx: idx,
            rvBefore: (s['rvb'] as num?)?.toInt() ?? 0,
            valids: (s['v'] as num?)?.toInt() ?? 0,
            durationMs: (s['d'] as num?) ?? 0);
    if (perluSalah) {
      await _gameWaitUntil(_gameLastT + 0.4 * dt);
      if (st.stop) return 'none';
      final r = await _gameFeed(fr, p, salah: true);
      if (r is Map && _truthy(r['ended'])) return 'ended';
      if (r is! Map || !_truthy(r['fed'])) return 'none';
      if (_truthy(r['salah'])) _gameMiss += 1;
    }
    if (_gameT0 > 0) {
      // tertinggal jadwal (eval lambat / game sempat menahan): kejar
      // pelan2, jeda minimal setengah dt (seperempat sesudah huruf salah,
      // seperti orang membetulkan), ketinggalan dibatasi 3 huruf supaya
      // tidak ada rentetan panjang (wpm > 250 = game kalah)
      if (now - (_gameT0 + _gameK * dt) > 3 * dt) _gameT0 = now - (_gameK + 3) * dt;
      await _gameWaitUntil(
          max(_gameT0 + _gameK * dt, _gameLastT + (perluSalah ? 0.25 : 0.5) * dt));
      if (st.stop) return 'none';
    }
    final r = await _gameFeed(fr, p, salah: false);
    if (r is Map && _truthy(r['ended'])) return 'ended';
    if (r is! Map || !_truthy(r['fed'])) return 'none';
    if (_gameT0 == 0) _gameT0 = _gameLastT;
    _gameK += 1;
    final len = (s['len'] as num?)?.toInt() ?? 0;
    if (len > 0) st.levelProgress = ((idx + 1) / len).clamp(0.0, 1.0);
    return 'fed';
  }
}
