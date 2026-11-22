// State mesin bot (port engine/state.py). Python memakai variabel modul
// global; di sini satu objek per sesi bot. Nama dipertahankan mirip
// aslinya (komentar = nama python) supaya gampang dicocokkan.
import 'page.dart';

class LoginSentinel {
  bool ok = true;
  String alasan = '';
  double gagal403 = 0;
  double terakhir401 = 0;
  final path401 = <String, double>{};
  double log401 = 0;
  bool pernahIn = false;
  double unknownMulai = 0;
}

class LevelAsk {
  bool aktif = false;
  int start = 0;
  int fallback = 0;
  String jawab = '';
}

class EngineState {
  // ---- kontrol (dibaca/ditulis backend)
  bool stop = false; // STOP
  bool needsLogin = false; // NEEDS_LOGIN
  bool askLoginNav = false; // ASK_LOGIN_NAV
  String askLoginUrl = ''; // ASK_LOGIN_URL
  bool loginDicek = false; // LOGIN_DICEK
  bool awaitRange = false; // AWAIT_RANGE
  bool askBuildMap = false; // ASK_BUILD_MAP
  bool askRecovery = false; // ASK_RECOVERY
  bool browserClosed = false; // BROWSER_CLOSED
  bool rangeDone = false; // RANGE_DONE
  int levelStart = 1; // LEVEL_START
  int levelEnd = 0; // LEVEL_END (0 = tanpa batas)
  bool rangeReady = false; // RANGE_READY
  int speedWpm = 400; // SPEED_WPM
  bool askNextLevel = false; // ASK_NEXT_LEVEL
  final levelAsked = LevelAsk(); // LEVEL_ASKED
  bool petaBangun = false; // PETA_BANGUN
  String? tahanNav; // TAHAN_NAV

  // ---- status utk UI
  String statusUrl = ''; // STATUS_URL
  String statusLabel = ''; // STATUS_LABEL
  /// kemajuan lesson ketik saat ini 0..1 (baru di v4, utk bilah UI)
  double levelProgress = 0;

  // ---- level & rentang
  double labelRetry = 0;
  double rangeNav = 0;
  bool rangeJumpDone = false;
  int rangeMaxSeen = 0;
  Set<int>? unlockSet;
  bool rangeValidated = false;
  bool userLepas = false;

  // ---- loop
  double lastLoopErr = 0;
  String lastTypedText = '';
  double lastActionTime = 0;
  double lastDebugDump = 0;
  String lastUrl = '';
  double premlockSince = 0;
  double loginNotice = 0;
  double navTry = 0;
  double lastRecovery = 0;
  double lastResync = 0;
  final recoveryCounts = <String, int>{};
  final hijackCounts = <String, int>{};
  final brokenLessons = <int>{};
  final levelLabelCache = <String, String>{};
  double unlockCk = 0;
  double popupT = 0;
  double premSkipT = 0;
  // modal 'Upgrade to Pro': berapa kali X sudah diklik (reset saat modal hilang)
  int proXTries = 0;
  /// wpm bersih yang sedang dipakai target bintang (0 = tidak diatur)
  double paceWpm = 0;
  double proWaitSince = 0;

  // ---- pop-up
  String repeatLabel = '';
  int repeatCount = 0;
  double repeatUntil = 0;
  double repeatT = 0;
  /// modal iklan/langganan di tengah lesson: kapan terakhir dicek
  double adModalT = 0;
  /// pembacaan ulang frame per level (lihat Supervisor._unknownStep)
  int resyncN = 0;
  /// dump [TUNDA] per masa diam (dibatasi supaya log tidak banjir)
  int dumpN = 0;
  double dumpRef = -1;

  // ---- mesin ketik
  double loopOverhead = 0.030;
  double lastCharDelay = 0;
  double userWatchT = 0;
  double userWatchElapsed = 1e9;
  /// saat user menyerahkan kendali (Mulai/Lanjut): aktivitas user yang
  /// lebih lama dari ini diabaikan (baru di v4, lihat Engine.handOver)
  double handOverT = 0;
  String waitUserUrl = '';
  double waitUserT = 0;
  final enterTimes = <double>[];
  int burstLen = 1;
  int burstStreak = 0;
  double burstOverheadMs = 18.0;

  // ---- standard
  String? stdLastRem;
  int stdAttempts = 0;
  double stdLastTry = 0;
  bool stallUserNote = false;

  // ---- tutorial
  String? tutSig;
  int tutAttempts = 0;
  String? tutFull;
  // layar selesai tutorial (baru di v4): teks yang terbaca saat semua
  // karakter sudah terketik + tanda class 'BELUM diketik' (null = tanda
  // tak membedakan) -> jangan diketik ulang, cukup Enter lagi
  String? tutDoneText;
  String? tutDoneSig;
  double tutDoneT = 0;
  double tutEnterT = 0;
  bool tutDoneNote = false;

  // ---- minigame / phaser
  final lastFocusClick = <String, double>{};
  double phaserCooldownUntil = 0;
  String phaserFreezeUrl = '';
  int phaserFreezeCount = 0;
  bool phaserFreezeClicked = false;
  int miniVoidTahan = 0;
  int balloonTahanN = 0;
  double balloonFrameSeen = 0;
  Frame? balloonBridgeFrame;
  double balloonBridgeT = 0;
  double balloonEndT = 0;
  double balloonSkipT = 0;
  String? balloonCoreChr;
  Object? balloonCoreIdx;
  double balloonCoreLastT = 0;
  bool hasBalloonCoreLast = false;
  double balloonCoreTyped = 0;
  double gerbangAudioT = 0;
  double lastBalloonOcr = 0;
  double balloonEmptyCk = 0;
  Frame? balloonEmptyFrame;
  bool balloonProbeDone = false;

  // ---- hold / layar / intro
  String lastHoldRaw = '';
  int holdAttempts = 0;
  String scrkeyKey = '';
  int scrkeyCount = 0;
  double scrkeyUntil = 0;
  String? introSig;
  int introAttempts = 0;
  bool introFlow = false;

  // ---- ocr
  double lastOcrTime = 0;

  // ---- login
  final loginSentinel = LoginSentinel();
  double loginCkTerakhir = 0;
  bool loginSeedCek = false;
  double probeTabCk = 0;

  final stats = <String, int>{
    'std': 0,
    'mini': 0,
    'ocr': 0,
    'popup': 0,
    'hold': 0,
    'uikey': 0,
    'tut': 0,
    'phaser': 0,
    'video': 0,
    'intro': 0,
  };

  void bump(String k, [int n = 1]) => stats[k] = (stats[k] ?? 0) + n;
}
