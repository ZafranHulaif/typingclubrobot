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

extension StarLesson on Engine {
  /// Rencana bintang untuk lesson di [frame] (null = ketik biasa).
  Future<StarPace?> starPace(Frame frame) async {
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
  Future<String> typePaced(Frame frame, String rem0, StarPace p) async {
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
        while (w == c) {
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
}
