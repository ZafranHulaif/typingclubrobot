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

/// Pita rasio tiap bintang (atas 5 bintang dibatasi supaya tidak
/// kebablasan jadi secepat platinum).
const starBand = {5: (1.0, 1.6), 4: (0.8, 1.0), 3: (0.6, 0.8), 2: (0.4, 0.6), 1: (0.2, 0.4)};

/// Rasio acak di bagian aman pita [stars] (jauh dari batas: pembulatan
/// wpm & akurasi edclub). Goal kecil = pita sempit -> tengah pita.
double starRatioPick(int stars, double g, Random rnd) {
  final (lo, hi) = starBand[stars]!;
  final m = max(0.06, 1.2 / g);
  final a = lo + m, b = stars == 5 ? hi : hi - m;
  if (a >= b) return starMidRatio[stars]!;
  return a + rnd.nextDouble() * (b - a);
}

/// Hitung kecepatan & jumlah salah untuk [stars] bintang. null = tidak
/// perlu diatur (target perak / lesson tanpa target kecepatan). [rnd] =
/// rasio & akurasi diacak di dalam pita aman (tiap lesson beda); tanpa
/// [rnd] selalu tengah pita.
StarPace? planStars(int stars,
    {required num goal,
    num minWpm = 0,
    num minAcc = 0,
    num difficulty = 0,
    required int chars,
    Random? rnd}) {
  var r = starMidRatio[stars];
  if (r == null || chars <= 0) return null;
  final g = max(1.0, (goal + difficulty).toDouble());
  if (rnd != null) r = starRatioPick(stars, g, rnd);
  final minW = max(0.0, (minWpm + difficulty).toDouble());
  // wpm minimal dengan margin (edclub membulatkan wpm)
  final wMin = minW * 1.2 + 0.5;
  // akurasi serendah yang aman: batas + 5 poin, paling rendah 85%
  final accFloor = min(100.0, max(minAcc.toDouble() + 5, 85.0)) / 100;
  // lesson pendek: pembulatan akurasi terlalu kasar, ketik tanpa salah
  var e = chars < 25 ? 0 : (chars * (1 - accFloor)).floor();
  if (rnd != null && e > 0) {
    // akurasi acak antara batas aman & +10 poin (maks 98%): lebih tinggi
    // = lebih jauh dari 'focus on accuracy'
    final top = min(0.98, accFloor + 0.10);
    if (top > accFloor) e = (chars * (1 - (accFloor + rnd.nextDouble() * (top - accFloor)))).floor();
  }
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

/// Batas wpm yang dihitung edclub (lebih cepat tidak menambah rasio).
const edclubWpmCap = 200;

/// Platinum 'santai': tanpa salah, kecepatan acak sedikit di atas minimal
/// platinum (rasio 2 = wpm 2x goal), bukan secepatnya. null = tidak
/// terjangkau di bawah batas wpm edclub (ketik secepatnya saja).
StarPace? planPlatinum(
    {required num goal, num minWpm = 0, num difficulty = 0, required int chars, required Random rnd}) {
  if (chars <= 0) return null;
  final g = max(1.0, (goal + difficulty).toDouble());
  final m = max(0.1, 1.5 / g);
  final lo = (2 + m) * g, hi = 2.6 * g;
  const cap = edclubWpmCap - 5.0;
  if (lo > cap) return null;
  final minW = max(0.0, (minWpm + difficulty).toDouble()) * 1.2 + 0.5;
  final w = max(min(lo + rnd.nextDouble() * max(0.0, hi - lo), cap), minW);
  final dt = 60.0 * chars / (5 * w * max(chars - 1, 1));
  return StarPace(stars: 5, wpm: w, errors: 0, chars: chars, dt: dt, ratio: min(2.0, min(w, 200) / g));
}

/// Jadwal naik-turun per frasa: waktu tombol ke-k (satuan dt) supaya
/// kecepatan beda tiap frasa (+-[spread]) tapi rata2 lesson tetap
/// ([chars] tombol = [chars] dt). Lewat [chars]: lanjut rata.
List<double> phraseSchedule(int chars, Random rnd, {double spread = 0.2}) {
  final f = <double>[];
  while (f.length < chars) {
    // frasa 12-40 tombol, kecepatan 1 +- spread
    final len = 12 + rnd.nextInt(29);
    final v = 1 + (rnd.nextDouble() * 2 - 1) * spread;
    for (var i = 0; i < len && f.length < chars; i++) {
      f.add(1 / v);
    }
  }
  final total = f.fold<double>(0, (a, b) => a + b);
  final k = total > 0 ? chars / total : 1.0;
  final out = List<double>.filled(chars + 1, 0);
  for (var i = 0; i < chars; i++) {
    out[i + 1] = out[i] + f[i] * k;
  }
  return out;
}

/// Pacing bintang di game (lihat gamePace). false = semua game secepatnya.
const gamePacingOn = true;

/// Game yang sudah diuji live untuk target bintang (22 Nov, akun tes):
/// dicocokkan ke activity.app + host frame (huruf kecil). Game lain
/// (TempleBash/whackamonster, FloatingBubbles/bubbleburster = premium di
/// akun tes, belum bisa diuji) tetap diketik secepatnya.
const gamePaceTypes = ['balloonvalley', 'monsterattack'];

/// Jenis game yang bisa diatur dari nama app + host (huruf kecil):
/// 'balloon' / 'monster', '' = game lain (diketik secepatnya).
String gameKindOf(String nama) => nama.contains('balloonvalley')
    ? 'balloon'
    : nama.contains('monsterattack')
        ? 'monster'
        : '';

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

/// Kecepatan minimum game (wpm). Balon terlepas & ninja kehilangan nyawa
/// kalau diketik pelan, apa pun goal-nya (live 28 Nov: balon goal 10 gagal
/// di 13 wpm dua kali, 16 wpm lulus tapi 2 nyawa hilang). Bintang rendah
/// dicapai lewat salah disengaja, bukan dengan melambat.
const gameMinWpm = 22;

/// Akurasi asli terendah yang dipakai. Target yang butuh lebih rendah dari
/// ini (di kecepatan minimum) dinaikkan ke bintang terendah yang terjangkau.
/// Salah ketik di game TIDAK mengurangi nyawa (kata owner 28 Nov, hanya
/// kelambatan), jadi boleh banyak: tiap huruf paling banyak sekali salah.
const gameRealAccMin = 0.1;

/// Kecepatan aman untuk [stars] bintang di game: minimal [gameMinWpm] dan
/// 1.25x goal (balon jatuh ~2x jeda goal, yeti terdorong kalau >= goal),
/// dan cukup cepat supaya target tercapai dengan akurasi asli <= 88% (ada
/// ruang koreksi dua arah). [faster] = pengali kecepatan minimum (coba
/// lagi sesudah game gagal). null = tidak diatur.
GamePace? planGame(int stars,
    {required num goal, num minWpm = 0, num difficulty = 0, double faster = 1}) {
  var r = starMidRatio[stars];
  if (r == null) return null;
  final g = max(1.0, (goal + difficulty).toDouble());
  final minW = max(0.0, (minWpm + difficulty).toDouble());
  final w = max(max(g * max(1.25, r / 0.88), gameMinWpm * faster), minW * 1.2 + 0.5).ceilToDouble();
  if (w > gamePaceMaxWpm) return null;
  // terlalu banyak salah yang dibutuhkan: naik ke bintang terendah yang
  // terjangkau (lebih aman daripada melambat)
  var s = stars;
  while (s < 5 && r! * g / w < gameRealAccMin) {
    s += 1;
    r = starMidRatio[s];
  }
  return GamePace(stars: s, ratio: r!, goal: g, wpm: w);
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

/// Akurasi terendah yang bisa dipilih di mode Manual (sama dgn batas aman
/// planStars).
const manualAccMin = 85;

/// Bintang dari rasio edclub (lihat rumus di atas).
int starsOf(double ratio) => ratio >= 1
    ? 5
    : ratio >= .8
        ? 4
        : ratio >= .6
            ? 3
            : ratio >= .4
                ? 2
                : ratio >= .2
                    ? 1
                    : 0;

/// Mode Manual: hasil kecepatan & akurasi pilihan user di satu lesson.
/// Kebalikan planStars: bintang tidak dipilih, tinggal dihitung. Kalau
/// pilihan user di bawah batas minimum level (= 0 bintang, level tidak
/// lulus & bot tertahan di 'Try again'), dinaikkan secukupnya.
class ManualPace {
  ManualPace({
    required this.wpm,
    required this.acc,
    required this.errors,
    required this.chars,
    required this.ratio,
    required this.wpmRaised,
    required this.accRaised,
    required this.accFixed,
  });

  /// wpm bersih yang dipakai (sudah dinaikkan kalau perlu)
  final double wpm;

  /// akurasi yang dipakai (%)
  final int acc;
  final int errors;
  final int chars;
  final double ratio;

  /// kecepatan user di bawah min_wpm level -> dinaikkan
  final bool wpmRaised;

  /// akurasi user di bawah min_accuracy level -> dinaikkan
  final bool accRaised;

  /// level tidak bisa diberi salah ketik (mode blokir / lesson pendek)
  final bool accFixed;

  int get stars => starsOf(ratio);

  /// platinum: rasio penuh tanpa satu pun salah
  bool get silver => errors == 0 && ratio >= 2;

  /// jeda antar tombol (detik), seperti StarPace
  double get dt => 60.0 * (chars - errors) / (5 * wpm * max(chars - 1, 1));

  StarPace get pace => StarPace(
      stars: stars, wpm: wpm, errors: errors, chars: chars, dt: dt, ratio: ratio);
}

/// Hitung mode Manual untuk lesson biasa. [canErr] = salah ketik boleh
/// maju (on_error 'continue'); selain itu akurasi selalu 100%.
ManualPace planManual(
    {required int wpm,
    required int acc,
    required num goal,
    num minWpm = 0,
    num minAcc = 0,
    num difficulty = 0,
    required int chars,
    bool canErr = true}) {
  final g = max(1.0, (goal + difficulty).toDouble());
  final minW = max(0.0, (minWpm + difficulty).toDouble());
  // margin sama dgn planStars (edclub membulatkan wpm)
  final wMin = minW > 0 ? (minW * 1.2 + 0.5).ceilToDouble() : 0.0;
  final w = max(wpm.toDouble(), wMin);
  final fixed = !canErr || chars < 25;
  var a = acc.clamp(1, 100);
  var accRaised = false;
  if (fixed) {
    a = 100;
  } else {
    // batas + 5 poin (sama dgn planStars)
    final floor = min(100, minAcc.ceil() + 5);
    if (minAcc > 0 && a < floor) {
      a = floor;
      accRaised = true;
    }
  }
  final e = fixed ? 0 : (chars * (100 - a) / 100).floor();
  final af = (chars - e) / max(chars, 1);
  final ratio = min(2.0, af * af * min(w, 200) / g);
  return ManualPace(
      wpm: w,
      acc: e == 0 ? 100 : (100 * af).floor(),
      errors: e,
      chars: chars,
      ratio: ratio,
      wpmRaised: w > wpm,
      accRaised: accRaised,
      accFixed: fixed && acc < 100);
}

/// Mode Manual di game (yang teruji, mode blokir). Game berwaktu: kecepatan
/// minimal 1.25x goal (lihat planGame), maksimal [gamePaceMaxWpm]. Akurasi =
/// akurasi asli (huruf benar-pertama-kali); akurasi biasa tetap 100%.
/// null = game diketik seperti biasa (secepatnya): 100% dan >= batas atas,
/// sama dgn perilaku sebelum mode Manual, atau goal terlalu tinggi.
(GamePace, ManualPace)? planManualGame(
    {required int wpm,
    required int acc,
    required num goal,
    num minWpm = 0,
    num difficulty = 0}) {
  final g = max(1.0, (goal + difficulty).toDouble());
  final minW = max(0.0, (minWpm + difficulty).toDouble());
  final lower = max(max(g * 1.25, gameMinWpm.toDouble()), minW * 1.2 + 0.5).ceilToDouble();
  if (lower > gamePaceMaxWpm) return null;
  final a = acc.clamp(1, 100);
  if (a == 100 && wpm >= gamePaceMaxWpm) return null;
  final w = wpm.toDouble().clamp(lower, gamePaceMaxWpm.toDouble());
  // rasio TANPA batas 2 utk loop game: gameMiss mengejar akurasi asli
  // ratio * goal / wpm = a (dibatasi 2 -> akurasi asli ikut turun)
  final raw = a / 100 * w / g;
  final ratio = min(2.0, raw);
  final mp = ManualPace(
      wpm: w,
      acc: a,
      errors: a == 100 ? 0 : 1,
      chars: 0,
      ratio: ratio,
      wpmRaised: w > wpm,
      accRaised: false,
      accFixed: false);
  return (GamePace(stars: mp.stars, ratio: raw, goal: g, wpm: w), mp);
}

/// Perkiraan bintang mode Manual untuk target lesson [g] (isi
/// EngineState.lessonGoal) dengan pengaturan [wpm]/[acc] sekarang.
/// null = tidak bisa diperkirakan (level tes, game yang tidak diatur).
ManualPace? guessManual(Map g, int wpm, int acc) {
  num n(String k) => (g[k] as num?) ?? 0;
  switch (g['kind']) {
    case 'lesson':
      return planManual(
          wpm: wpm,
          acc: acc,
          goal: n('goal'),
          minWpm: n('min_wpm'),
          minAcc: n('min_acc'),
          difficulty: n('diff'),
          chars: n('chars').toInt(),
          canErr: g['can_err'] == true);
    case 'game':
      return planManualGame(
              wpm: wpm, acc: acc, goal: n('goal'), minWpm: n('min_wpm'), difficulty: n('diff'))
          ?.$2;
  }
  return null;
}

/// Posisi salah ketik untuk [chars] karakter: [errors] posisi tersebar
/// rata di [2, chars-3], tiap posisi digeser acak maks seperempat jarak
/// antar-salah. Jarak antar-salah selalu >= setengah jarak rata2, jadi
/// tidak pernah menggerombol (edclub menegur salah yang beruntun).
Set<int> spreadErrors(int chars, int errors, Random rnd) {
  const lo = 2;
  final hi = chars - 3;
  final span = hi - lo + 1;
  if (errors <= 0 || span <= 0) return {};
  if (errors >= span) return {for (var i = lo; i <= hi; i++) i};
  final stride = span / errors;
  final out = <int>{};
  for (var i = 0; i < errors; i++) {
    final tengah = lo + (i + 0.5) * stride;
    final geser = (rnd.nextDouble() - 0.5) * stride * 0.5;
    out.add((tengah + geser).floor().clamp(lo, hi));
  }
  // jarak rapat sekali (stride < 2) bisa bertabrakan: isi sisanya
  for (var i = lo; out.length < errors && i <= hi; i++) {
    out.add(i);
  }
  return out;
}

/// Angka 'nyawa' game (kunci live/life/heart/health) dari core & state
/// Phaser, untuk bot.log: belum diketahui apakah salah ketik mengurangi
/// nyawa (bahan menyetel salah disengaja di game).
const nyawaJs = r'''
const out = {};
const look = (o, pre) => {
  if (!o) return;
  for (const k of Object.keys(o)) {
    if (!/live|life|heart|health|nyawa/i.test(k)) continue;
    const v = o[k];
    if (typeof v === 'number' || typeof v === 'boolean') out[pre + k] = v;
  }
};
try { look(window.core, 'core.'); } catch (e) {}
try {
  if (window.Phaser && Phaser.GAMES) for (const g of Phaser.GAMES) {
    const s = g.state.states[g.state.current];
    look(s, 'state.');
    look(s && s.core, 'state.core.');
  }
} catch (e) {}
return out;
''';

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
    final m = manual?.call('lesson');
    // platinum santai: info lesson selalu perlu (kecepatannya dari goal)
    final santai = m == null && (platinumRelaxed?.call() ?? false);
    // lihat dulu tanpa mengambil giliran: platinum tetap = tak perlu dibaca
    final lihat = m != null ? 0 : starTarget?.call('lesson', false) ?? 0;
    // platinum: info lesson cuma dibaca kalau jenis level ini belum dikenal
    final kenal = levelKnown?.call() ?? true;
    if (m == null && lihat == 0 && kenal && !santai) return null;
    final info = await runJs(lessonGoalJs, frame);
    if (m == null && lihat == 0 && !santai) {
      if (info is Map) {
        levelKind?.call(_truthy(info['objc']) || _truthy(info['test']) ? 'test' : 'star');
      }
      return null;
    }
    if (info is! Map) {
      log(m != null
          ? '[Manual] target kecepatan lesson tidak terbaca - ketik biasa '
              '(${m.wpm} wpm, tanpa salah)'
          : '[Bintang] target ${lihat < 0 ? 'pola/acak' : lihat == 0 ? 'platinum' : lihat}, tapi target '
              'kecepatan lesson tidak terbaca - ketik biasa');
      return null;
    }
    if (_truthy(info['objc']) || _truthy(info['test'])) {
      levelKind?.call('test');
      if (m != null) st.lessonGoal = {'kind': 'skip'};
      return null;
    }
    levelKind?.call('star');
    final n = (info['n'] as num?)?.toInt() ?? 0;
    final pos = max((info['pos'] as num?)?.toInt() ?? 0, 0);
    final sisa = n - pos;
    if (sisa < 5) return null;
    // akurasi diatur lewat salah ketik yang maju (on_error 'continue');
    // mode lain (blokir) -> tanpa salah, hanya kecepatan
    final bolehSalah = '${info['on_error']}' == 'continue';
    if (m != null) return _manualLesson(m, info, sisa, bolehSalah);
    // level ini dinilai bintang: ambil target (giliran pola/acak)
    final target = lihat == 0 ? 0 : starTarget?.call('lesson', true) ?? 0;
    if (target == 0 && santai) {
      final pp = planPlatinum(
          goal: (info['goal'] as num?) ?? 0,
          minWpm: (info['min_wpm'] as num?) ?? 0,
          difficulty: (info['diff'] as num?) ?? 0,
          chars: sisa,
          rnd: rnd);
      if (pp == null) {
        log('[Bintang] platinum santai: goal ${info['goal']} wpm terlalu tinggi '
            '(platinum butuh lebih dari ${edclubWpmCap - 5} wpm) - ketik secepatnya');
        return null;
      }
      log('[Bintang] platinum santai: goal ${info['goal']} wpm -> ketik '
          'rata2 ${pp.wpm.toStringAsFixed(1)} wpm tanpa salah, perkiraan '
          '${(pp.chars * pp.dt / 60).toStringAsFixed(1)} menit');
      return pp;
    }
    if (target < 1 || target > 5) return null;
    final p = planStars(target,
        goal: (info['goal'] as num?) ?? 0,
        minWpm: (info['min_wpm'] as num?) ?? 0,
        minAcc: bolehSalah ? ((info['min_acc'] as num?) ?? 0) : 100,
        difficulty: (info['diff'] as num?) ?? 0,
        chars: sisa,
        rnd: rnd);
    if (p == null) return null;
    log('[Bintang] target $target: goal ${info['goal']} wpm -> ketik '
        'rata2 ${p.wpm.toStringAsFixed(1)} wpm (naik-turun tiap frasa), akurasi ${p.accuracy}% '
        '(${p.errors} salah dari ${p.chars}), perkiraan '
        '${(p.chars * p.dt / 60).toStringAsFixed(1)} menit');
    return p;
  }

  /// Mode Manual di lesson biasa: catat target lesson (perkiraan bintang di
  /// UI), lalu rencana ketik. null = cukup jalur ketik biasa (100% tanpa
  /// kecepatan yang perlu dinaikkan, persis perilaku lama).
  StarPace? _manualLesson(({int wpm, int acc}) m, Map info, int sisa, bool bolehSalah) {
    final goal = {
      'kind': 'lesson',
      'goal': (info['goal'] as num?) ?? 0,
      'min_wpm': (info['min_wpm'] as num?) ?? 0,
      'min_acc': (info['min_acc'] as num?) ?? 0,
      'diff': (info['diff'] as num?) ?? 0,
      'chars': sisa,
      'can_err': bolehSalah,
    };
    st.lessonGoal = goal;
    final p = guessManual(goal, m.wpm, m.acc)!;
    final naik = [
      if (p.wpmRaised) 'kecepatan dinaikkan ke ${p.wpm.round()} wpm (minimum level ini)',
      if (p.accRaised) 'akurasi dinaikkan ke ${p.acc}% (minimum level ini)',
      if (p.accFixed) 'akurasi 100% (level ini tidak bisa diberi salah ketik)',
    ];
    log('[Manual] ${m.wpm} wpm, akurasi ${m.acc}%: goal ${info['goal']} wpm '
        '-> ketik ${p.wpm.round()} wpm, akurasi ${p.acc}% (${p.errors} salah '
        'dari ${p.chars}), perkiraan ${p.silver ? '5 platinum' : '${p.stars} bintang'}'
        '${naik.isEmpty ? '' : ' - ${naik.join(', ')}'}');
    if (p.errors == 0 && !p.wpmRaised) return null;
    return p.pace;
  }

  /// Ketik sisa lesson sesuai [p]: jadwal jam dinding (tombol ke-k pada
  /// t0 + k*dt) supaya overhead tidak menumpuk, salah ketik di posisi
  /// acak (hanya huruf). Return 'done' | 'stall' | 'gone' | 'stop'.
  Future<String> typePaced(Frame frame, String rem0, StarPace p,
      {String? avoid}) async {
    // posisi salah: tersebar rata (acak sedikit) di [2, chars-3]. Dulu
    // acak murni: di akurasi 85% salah sering menggerombol beberapa
    // berturut2 -> edclub memunculkan "focus on accuracy" (laporan 28 Nov)
    final salahDi = spreadErrors(p.chars, p.errors, rnd);
    // kecepatan naik-turun tiap frasa, rata2 tetap p.wpm
    final jadwal = phraseSchedule(p.chars, rnd);
    double waktu(int k) => k < jadwal.length ? jadwal[k] : jadwal.last + (k - jadwal.length + 1);
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
      final tunggu = t0 + waktu(k) * p.dt - now;
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
    final nama = '${s['app']} ${s['host']}'.toLowerCase();
    final label = '${s['app']}'.split('.').last;
    final jenis = gameKindOf(nama);
    final kind = jenis.isEmpty ? 'game' : jenis;
    final m = manual?.call(kind);
    final lihat = m != null ? 0 : starTarget?.call(kind, false) ?? 0;
    // jenis level (peta level): data game sudah terbaca, gratis
    final tes = _truthy(s['objc']) || _truthy(s['test']);
    levelKind?.call(tes
        ? 'test'
        : jenis.isEmpty || !_truthy(s['blok'])
            ? 'game'
            : jenis);
    if (m == null && lihat == 0) return null;
    final tgt = lihat < 0 ? 'pola/acak' : '$lihat';
    if (_truthy(s['objc']) || _truthy(s['test'])) {
      if (m != null) st.lessonGoal = {'kind': 'skip'};
      return null;
    }
    if (m != null) return _manualGame(m, s, label, nama);
    if (jenis.isEmpty) {
      log('[Bintang] target $tgt, tapi game $label belum teruji untuk '
          'target bintang - diketik secepatnya');
      return null;
    }
    if (!_truthy(s['blok'])) {
      log('[Bintang] target $tgt, tapi game $label bukan mode blokir - '
          'diketik secepatnya');
      return null;
    }
    // game ini dinilai bintang & bisa diatur: ambil target
    final target = starTarget?.call(kind, true) ?? 0;
    if (target < 1 || target > 5) return null;
    // game ini pernah gagal (nyawa habis) di URL yang sama: lebih cepat
    final gagal = _gameFails[url] ?? 0;
    if (gagal >= 2) {
      log('[Bintang] game $label sudah gagal $gagal kali - diketik secepatnya supaya lulus');
      return null;
    }
    final p = planGame(target,
        goal: (s['goal'] as num?) ?? 0,
        minWpm: (s['min_wpm'] as num?) ?? 0,
        difficulty: (s['diff'] as num?) ?? 0,
        faster: gagal == 1 ? 1.5 : 1);
    if (p != null && p.stars != target) {
      log('[Bintang] target $target tidak terjangkau di game $label (kecepatan minimum '
          '${p.wpm.toStringAsFixed(0)} wpm, salah disengaja maks ${(100 * (1 - gameRealAccMin)).round()}%) '
          '- jadi ${p.stars} bintang');
    }
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

  /// Mode Manual di game: hanya game yang teruji & mode blokir yang diatur
  /// (sama dgn target bintang); lainnya diketik seperti biasa.
  GamePace? _manualGame(({int wpm, int acc}) m, Map s, String label, String nama) {
    if (gameKindOf(nama).isEmpty || !_truthy(s['blok'])) {
      st.lessonGoal = {'kind': 'game_free'};
      log('[Manual] game $label tidak bisa diatur - diketik seperti biasa');
      return null;
    }
    final goal = {
      'kind': 'game',
      'goal': (s['goal'] as num?) ?? 0,
      'min_wpm': (s['min_wpm'] as num?) ?? 0,
      'diff': (s['diff'] as num?) ?? 0,
    };
    st.lessonGoal = goal;
    final r = planManualGame(
        wpm: m.wpm,
        acc: m.acc,
        goal: goal['goal'] as num,
        minWpm: goal['min_wpm'] as num,
        difficulty: goal['diff'] as num);
    if (r == null) {
      st.lessonGoal = {'kind': 'game_free'};
      log('[Manual] game $label diketik seperti biasa (secepatnya)');
      return null;
    }
    final (p, mp) = r;
    _gamePace = p;
    st.paceWpm = p.wpm;
    log('[Manual] game $label: goal ${s['goal']} wpm -> ketik '
        '${p.wpm.toStringAsFixed(0)} wpm, akurasi asli ~${mp.acc}%, perkiraan '
        '${mp.silver ? '5 platinum' : '${mp.stars} bintang'}'
        '${mp.wpmRaised ? ' (kecepatan dinaikkan, game berwaktu)' : ''}'
        '${mp.wpm < m.wpm ? ' (game maks $gamePaceMaxWpm wpm)' : ''}');
    return p;
  }

  /// false = sudah pasti tidak diatur di lesson ini (hemat satu eval per
  /// putaran saat target perak / game belum teruji).
  bool get gamePaceMaybe =>
      gamePacingOn && !(_gamePaceUrl == page.url && _gamePace == null);

  /// Data game belum terbaca (core belum siap): tahan dulu supaya huruf
  /// pertama tidak diketik secepatnya; menyerah setelah 15 putaran.
  bool gamePaceHold() {
    // mode Manual = sama2 perlu data game dulu (anggap target 'ada');
    // -1 = pola/acak (juga diatur)
    final target = manual?.call('game') != null ? 1 : starTarget?.call('game', false) ?? 0;
    final url = page.url;
    if (_gameHoldUrl != url) {
      _gameHoldUrl = url;
      _gameHoldN = 0;
    }
    _gameHoldN += 1;
    if (target != 0 && _gameHoldN <= 15) return true;
    _gamePaceUrl = url;
    _gamePace = null;
    if (target != 0) {
      log('[Bintang] target ${target < 0 ? 'pola/acak' : target}, tapi data '
          'game tidak terbaca - diketik secepatnya');
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
    final nyawa = await runJs(nyawaJs, fr);
    log('[Bintang] game berakhir di huruf ${s['idx']}/${s['len']}'
        '${nyawa is Map && nyawa.isNotEmpty ? ', nyawa $nyawa' : ''}');
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
