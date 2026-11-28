// Mesin bot v4: port engine/*.py ke Dart (docs/architecture/v4-native-plan.md N3).
//
// Satu library, satu file per modul python (part + extension), supaya tiap
// fungsi gampang dicocokkan dgn aslinya. Python memblokir (time.sleep);
// di sini semua async + Clock (tes memakai jam palsu).
//
// Mode yang dipakai = mode WebView2 3.5.x (BROWSER_WV2 + EMBED_BROWSER):
// satu halaman, tanpa tab cadangan, tanpa luncur/restart browser.
import 'dart:async';
import 'dart:convert';
import 'dart:io' show File, Platform;
import 'dart:math' show Random, max, min, sqrt;
import 'dart:typed_data';

import 'clock.dart';
import 'js.dart';
import 'js_extra.dart';
import 'js_inline.dart';
import 'level_map.dart';
import 'ocr.dart';
import 'page.dart';
import 'state.dart';
import 'urls.dart';

export 'state.dart';

part 'jsutil.dart';
part 'typing_core.dart';
part 'levels.dart';
part 'rentang.dart';
part 'session.dart';
part 'recovery.dart';
part 'supervisor.dart';
part 'lessons/standard.dart';
part 'lessons/tutorial.dart';
part 'lessons/games.dart';
part 'lessons/video.dart';
part 'lessons/holdkey.dart';
part 'lessons/screenkey.dart';
part 'lessons/intro.dart';
part 'lessons/balloon.dart';
part 'lessons/stars.dart';

const listUrl = 'https://www.edclub.com/sportal/program-3.game';
const courseUrl = 'https://www.edclub.com/student/course/3';
const loginUrlIndividual = 'https://www.edclub.com/signin';
const loginUrlSchool = 'https://sportal.edclub.com/';
const birthMonth = 'January';
const birthYear = '2000';
const ocrMinInterval = 3.0;

class Engine {
  /// Diagnosa: log event tombol halaman di titik masalah (TB_KEYLOG).
  static bool keyLog = false;

  Engine({
    required this.page,
    Clock? clock,
    LevelMap? levels,
    OcrService? ocr,
    this.dataDir,
    this.onLog,
    Random? random,
  })  : clock = clock ?? page.clock,
        levels = levels ?? LevelMap(),
        ocr = ocr ?? const NoOcr(),
        rnd = random ?? Random();

  Page page;
  final Clock clock;
  final LevelMap levels;
  final OcrService ocr;
  final String? dataDir;
  final Random rnd;
  final void Function(String line)? onLog;
  final st = EngineState();

  /// Jawaban dialog 'level masih terkunci' dari UI: 'mulai' / 'stop'
  /// (null = tak dijawab -> lanjut dari level terdepan, sama dgn 3.5.x).
  Future<String?> Function(int start, int fallback)? askLocked;

  /// Target bintang level sekarang (N7): 1-5 = atur kecepatan/akurasi,
  /// 0/null = perak (ketik secepatnya tanpa salah, perilaku lama).
  /// [kind] = 'lesson' | 'balloon' | 'monster' | 'game' (game apa saja,
  /// belum terbaca). [assign] = level ini PASTI dinilai bintang & bisa
  /// diatur: aturan pola/acak mengambil giliran berikutnya. Tanpa assign
  /// (cuma melihat): -1 = target belum ditentukan (pola/acak).
  int Function(String kind, bool assign)? starTarget;

  /// Mode Manual: kecepatan (wpm bersih) & akurasi (%) pilihan user,
  /// bintang tinggal hasilnya. null = mode bintang / rencana.
  ({int wpm, int acc})? Function(String kind)? manual;

  /// Jenis level yang sedang dibuka, utk peta level di editor rencana:
  /// 'star' (lesson dinilai bintang), 'balloon' / 'monster' (game yang
  /// bisa diatur), atau yang dilewati tanpa giliran pola: 'video',
  /// 'tutorial', 'test' (tes/objektif), 'hold' (tahan tombol), 'game'
  /// (game lain), 'premium' (terkunci Pro).
  void Function(String kind)? levelKind;

  /// false = jenis level ini belum dikenal: info lesson tetap dibaca
  /// walau target platinum (sekali per level).
  bool Function()? levelKnown;

  // pacing target bintang di game (per lesson, lihat lessons/stars.dart)
  GamePace? _gamePace;

  /// game yang gagal (nyawa habis, layar 'Type SPACE to try again') per
  /// URL: coba lagi lebih cepat, lalu secepatnya
  final _gameFails = <String, int>{};
  double _gameRetryT = -1;
  String _gamePaceUrl = '';
  int _gameK = 0;
  int _gameMiss = 0;
  int _gameIdx = -1;
  int _gameHoldN = 0;
  String _gameHoldUrl = '';
  double _gameLastT = 0;
  double _gameT0 = 0;

  bool _running = false;
  bool get running => _running;

  double get now => clock.now;
  Future<void> sleep(double s) => clock.sleep(s);
  double uniform(double a, double b) => a + rnd.nextDouble() * (b - a);

  void log(String line) {
    final f = onLog;
    if (f != null) {
      f(line);
    }
  }

  /// Jalankan loop utama sampai stop. Error tak terduga tidak membunuh
  /// loop (ditangani di dalam), jadi Future ini selesai = bot berhenti.
  Future<void> run() async {
    if (_running) return;
    _running = true;
    try {
      levels.muatPosisi();
      await mainLoop();
    } finally {
      _running = false;
    }
  }

  void requestStop() => st.stop = true;
}
