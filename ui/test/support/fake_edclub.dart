// edclub palsu di balik bridge CDP palsu: cukup pintar utk menguji mesin
// bot tanpa browser. Mengenali payload JS (konstanta yang SAMA dgn yang
// dikirim mesin) lalu menjawab dari model lesson di bawah ini.
//
// Model lesson ketik (span.token_unit): pos = karakter berikut yang
// ditunggu; keyDown dgn teks -> benar: maju; salah: ditandai _err lalu
// maju (seperti edclub). Backspace mundur satu & hapus tanda salah.
import 'dart:async';
import 'dart:math';

import 'package:typingbot/src/engine/clock.dart';
import 'package:typingbot/src/engine/js.dart';
import 'package:typingbot/src/engine/js_inline.dart';

import 'fake_bridge.dart';

class FakeLesson {
  FakeLesson(this.text, {this.label = 'L1'});
  final String text;
  final String label;
  int pos = 0;
  final errs = <int>{};

  /// keystroke ke-n (0-based) yang dibuang (tidak sampai ke lesson)
  final dropAt = <int>{};

  /// posisi yang SEKALI salah walau tombol benar (jari meleset)
  final wrongOnceAt = <int>{};

  /// keystroke awal yang diabaikan (stage belum siap)
  int ignoreFirst = 0;

  /// render progresif: baris berikut baru muncul setelah baris ini habis
  /// & [revealDelay] keystroke/iterasi baca berlalu
  bool progressive = false;
  int revealDelay = 0;
  int _hiddenReads = 0;

  bool get done => pos >= text.length;
  int keystrokes = 0;
  final typed = StringBuffer();

  void key(String ch) {
    final n = keystrokes++;
    if (n < ignoreFirst || dropAt.contains(n) || done) return;
    typed.write(ch);
    final want = text[pos];
    if (ch == want && !wrongOnceAt.remove(pos)) {
      pos++;
    } else {
      errs.add(pos);
      pos++;
    }
  }

  void backspace() {
    keystrokes++;
    if (pos == 0) return;
    pos--;
    errs.remove(pos);
  }

  /// sisa yang TERLIHAT (token pending) - null = tak ada token
  String? visibleRemaining() {
    if (done) return null;
    var rest = text.substring(pos);
    if (progressive) {
      // baris yang belum boleh tampil disembunyikan sebentar
      final nl = pos == 0 ? -1 : text.lastIndexOf('\n', pos - 1);
      final lineStart = nl < 0 ? 0 : nl + 1;
      if (pos == lineStart && pos > 0 && _hiddenReads < revealDelay) {
        _hiddenReads++;
        return '';
      }
      if (pos != lineStart) _hiddenReads = 0;
    }
    return rest;
  }
}

/// Tutorial boxed (.boxed-line > span > .boxed-char). Tiap karakter
/// punya tanda class: 'done' (sudah diketik), 'active' (giliran), 'pend'.
/// Selesai -> layar 'Good job!' menutupi, kotak TETAP di DOM (semua
/// 'done'); Enter baru diterima [enterDelay] dtk setelah selesai.
class FakeTutorial {
  FakeTutorial(this.text,
      {this.enterDelay = 0,
      this.rejects = 0,
      this.sigTetap = false,
      this.settle = 0,
      this.autoSkor});
  final String text;
  final double enterDelay;

  /// tanda class TIDAK berubah saat diketik (kotak selalu tampak sama):
  /// deteksi selalu membaca teks penuh
  final bool sigTetap;

  /// animasi selesai: selama ini karakter terakhir masih bertanda
  /// 'active' (belum seragam 'done')
  final double settle;

  /// layar skor muncul SENDIRI sekian dtk sesudah selesai (kotak hilang);
  /// Enter sebelum itu terbuang
  final double? autoSkor;

  /// jam (diisi FakeEdclub)
  double Function() jam = () => 0;

  /// berapa kali penyelesaian DITOLAK (kotak kembali kosong, tanpa layar
  /// selesai) - anti-buru-buru edclub
  int rejects;
  int pos = 0;
  bool done = false;
  double doneAt = 0;
  int completions = 0;

  /// tombol yang jatuh ke layar selesai (harus 0: tak boleh ketik ulang)
  int strayKeys = 0;
  int earlyEnters = 0;
  double advancedAt = 0;

  List<String> get _sigs {
    if (sigTetap) return List.filled(text.length, 'x');
    final animasi = done && jam() - doneAt < settle;
    return [
      for (var i = 0; i < text.length; i++)
        done
            ? (animasi && i == text.length - 1 ? 'active' : 'done')
            : (i < pos ? 'done' : (i == pos ? 'active' : 'pend'))
    ];
  }

  /// sama dgn TUT_REMAIN_JS / cabang tut DETECT_JS
  Map<String, dynamic> remain() {
    final sigs = _sigs;
    final last = sigs.last;
    var i = sigs.length - 1;
    while (i >= 0 && sigs[i] == last) {
      i--;
    }
    var start = i + 1;
    if (i >= 0) {
      var j = i;
      while (j >= 0 && sigs[j] == sigs[i]) {
        j--;
      }
      if (i - j <= 2) start = j + 1;
    }
    return {
      'rem': text.substring(start),
      'total': text.length,
      'firstSig': sigs.first,
      'lastSig': last,
      'allSame': sigs.every((s) => s == last),
    };
  }
}

/// Game edclub palsu (core typing mode blokir, seperti BalloonValley /
/// MonsterAttack): huruf salah tidak maju & tidak menurunkan akurasi,
/// hanya menandai huruf itu bukan benar-pertama-kali. Spasi dilompati
/// (yeti). Skor = rumus edclub dari statistik core.
class FakeGame {
  FakeGame(this.text,
      {this.app = 'typing.games.BalloonValley',
      this.goal = 10,
      this.minWpm = 1,
      this.endAfter,
      this.spaceStart = false,
      this.onError = 'block'})
      : dirty = List.filled(text.length, false),
        realValid = List.filled(text.length, true) {
    while (idx < text.length && text[idx] == ' ') {
      idx++;
    }
  }

  final String text;
  final String app;
  final num goal;
  final num minWpm;
  final String onError;

  /// yeti: huruf pertama baru ada setelah spasi (feed JS yang mengetuk)
  bool spaceStart;

  /// yeti: game tamat setelah sekian huruf benar (monster jatuh duluan)
  final int? endAfter;
  final List<bool> dirty;
  final List<bool> realValid;
  int idx = 0;
  int valids = 0;
  int misses = 0;
  double duration = 0;
  bool started = false;
  bool ended = false;

  /// jeda terpanjang antar huruf BENAR (ms) = ukuran bahaya balon jatuh
  double maxGap = 0;
  double _sinceValid = 0;

  /// jeda terpendek antar tombol (ms)
  double minDelay = double.infinity;

  /// satu tombol dengan jeda [ms]; true = maju
  bool key(String k, num ms) {
    if (ended || idx >= text.length) return false;
    started = true;
    duration += ms;
    if (valids + misses > 0) minDelay = min(minDelay, ms.toDouble());
    _sinceValid += ms;
    if (k != text[idx]) {
      realValid[idx] = false;
      misses++;
      return false;
    }
    if (valids > 0) maxGap = max(maxGap, _sinceValid);
    _sinceValid = 0;
    dirty[idx] = true;
    valids++;
    idx++;
    while (idx < text.length && text[idx] == ' ') {
      idx++;
    }
    if (idx >= text.length || (endAfter != null && valids >= endAfter!)) {
      ended = true;
      if (idx >= text.length) idx = text.length - 1;
    }
    return true;
  }

  int get _pn => dirty.lastIndexOf(true) + 1;
  int get _prv => realValid.take(_pn).where((x) => x).length;

  /// wpm seperti edclub (dibulatkan)
  int get wpm => duration <= 0 ? 0 : (valids / 5 / (duration / 60000) + 0.5).floor();
  int get realAccuracy => _pn == 0 ? 100 : (100 * _prv / _pn).ceil();

  /// rasio edclub (akurasi selalu 100 di mode blokir)
  double get ratio => min(2.0, 100 * realAccuracy * min(wpm, 200) / (1e4 * max(1, goal)));
  int get stars {
    final r = ratio;
    return r >= 1 ? 5 : r >= .8 ? 4 : r >= .6 ? 3 : r >= .4 ? 2 : r >= .2 ? 1 : 0;
  }

  Map<String, dynamic> stat() => {
        'app': app,
        'host': 'phaser.edclub.app',
        'pn': _pn,
        'prv': _prv,
        'goal': goal,
        'min_wpm': minWpm,
        'min_acc': 80,
        'diff': 0,
        'objc': false,
        'test': false,
        'blok': onError == 'block',
        'started': started,
        'ended': ended,
        'idx': idx,
        'len': text.length,
        'rvb': realValid.take(idx).where((x) => x).length,
        'chr': ended || spaceStart ? '' : text[idx],
        'cur_rv': realValid[min(idx, text.length - 1)],
        'v': valids,
        't': valids,
        'd': duration,
      };
}

final _balloonStateJs = balloonBridgeJs.replaceAll("'FEED'", '0');
final _paceRe = RegExp(r'window\.__tbPace = \{ms: (\d+), salah: (true|false)\}');

class FakeEdclub {
  FakeEdclub({this.url = 'https://www.edclub.com/student/course/3/lesson/116', this.keyCostMs = 0})
      : bridge = FakeBridge(),
        clock = FakeClock() {
    final b = bridge;
    b.handlers['Page.getFrameTree'] = (p, s) => {
          'frameTree': {
            'frame': {'id': 'MAIN', 'url': url}
          }
        };
    b.handlers['Runtime.evaluate'] = (p, s) => _eval('${p['expression']}');
    b.handlers['Input.dispatchKeyEvent'] = (p, s) {
      if (keyCostMs > 0) clock.advance(keyCostMs / 1000);
      keyEvents.add(p);
      if (p['type'] == 'keyDown') keyTimes.add(clock.now);
      if (p['type'] == 'keyDown' || p['type'] == 'rawKeyDown') _onKey(p);
      return {};
    };
    b.handlers['Input.dispatchMouseEvent'] = (p, s) {
      if (p['type'] == 'mousePressed') {
        clicks.add(Point(p['x'] as num, p['y'] as num));
        // klik di X modal 'Upgrade to Pro' = modal tertutup
        if (proModal && (p['x'] as num) == 900 && (p['y'] as num) == 80) proModal = false;
      }
      return {};
    };
    b.handlers['Page.navigate'] = (p, s) {
      navigations.add('${p['url']}');
      _go('${p['url']}');
      return {'frameId': 'MAIN', 'loaderId': 'L${navigations.length}'};
    };
    b.handlers['Page.reload'] = (p, s) {
      reloads++;
      _go(url);
      return {};
    };
  }

  final FakeBridge bridge;
  final FakeClock clock;
  final double keyCostMs;
  String url;
  FakeLesson? lesson;
  FakeTutorial? tutorial;
  final keyEvents = <Map<String, dynamic>>[];
  final clicks = <Point>[];
  final navigations = <String>[];
  int reloads = 0;
  int enterOnScore = 0;

  /// penanda login di DOM: 'in' / 'out' / null
  /// modal iklan/langganan muncul setelah lesson menerima sekian tombol:
  /// merebut fokus (tombol berikutnya tertelan) + memicu blur
  int? adAfterKeys;
  bool adUp = false;
  double adAt = -1;
  double adClosedAt = -1;
  int adSwallowed = 0;

  String? profile = 'in';
  bool alive = true;
  bool premiumSkip = false;
  /// modal 'Upgrade to Pro' tampil (X di 900,80); [proXDead] = X tak mempan
  bool proModal = false;
  /// game core (jalur tryBalloonCore); url harus sportal ...play
  FakeGame? game;
  /// target lesson (lessonGoalJs); null = tidak terbaca
  Map<String, dynamic>? lessonGoal;
  /// waktu (jam palsu) tiap keyDown
  final keyTimes = <double>[];
  bool proXDead = false;
  bool scoreShown = false;

  /// lesson berikutnya saat Enter ditekan di layar skor
  String? nextUrl;
  FakeLesson? nextLesson;

  /// jawaban custom per payload (dicek sebelum bawaan)
  final overrides = <String, dynamic Function()>{};

  /// dipanggil tiap evaluate (tes memakai ini utk mengubah keadaan /
  /// menghentikan loop)
  void Function(int n)? onEval;
  int evals = 0;

  void _go(String u) {
    url = u;
    scheduleMicrotask(() {
      bridge.emit('Page.frameNavigated', {
        'frame': {'id': 'MAIN', 'url': u}
      });
      bridge.emit('Page.loadEventFired', {'timestamp': clock.now});
    });
  }

  void _onKey(Map<String, dynamic> p) {
    final l = lesson;
    final code = p['windowsVirtualKeyCode'];
    final tu = tutorial;
    if (tu != null) {
      tu.jam = () => clock.now;
      _autoSkor();
    }
    if (tutorial != null && tu != null) {
      final t = '${p['text'] ?? ''}';
      if (tu.done) {
        if (code != 13) {
          tu.strayKeys++;
        } else if (tu.autoSkor != null || clock.now - tu.doneAt < tu.enterDelay) {
          tu.earlyEnters++;
        } else {
          tu.advancedAt = clock.now;
          tutorial = null;
          if (nextUrl != null) {
            lesson = nextLesson;
            _go(nextUrl!);
            nextUrl = null;
          }
        }
        return;
      }
      if (t.isEmpty || code == 13) return;
      if (t == tu.text[tu.pos]) tu.pos++;
      if (tu.pos >= tu.text.length) {
        tu.completions++;
        if (tu.rejects > 0) {
          tu.rejects--;
          tu.pos = 0;
        } else {
          tu.done = true;
          tu.doneAt = clock.now;
        }
      }
      return;
    }
    if (scoreShown && code == 13) {
      enterOnScore++;
      scoreShown = false;
      if (nextUrl != null) {
        lesson = nextLesson;
        _go(nextUrl!);
        nextUrl = null;
      }
      return;
    }
    if (l == null) return;
    if (adUp) {
      adSwallowed++;
      return;
    }
    if (code == 8) {
      l.backspace();
      return;
    }
    if (code == 9) {
      l.key('\t');
    } else {
      final t = '${p['text'] ?? ''}';
      if (t.isEmpty) return;
      l.key(t == '\r' ? '\n' : t);
    }
    if (adAfterKeys != null && l.keystrokes >= adAfterKeys! && !l.done) {
      adAfterKeys = null;
      adUp = true;
      adAt = clock.now;
    }
    if (l.done) scoreShown = true;
  }

  void _autoSkor() {
    final tu = tutorial;
    if (tu == null || !tu.done || tu.autoSkor == null) return;
    if (clock.now - tu.doneAt >= tu.autoSkor!) {
      tu.advancedAt = clock.now;
      tutorial = null;
      scoreShown = true;
    }
  }

  Map<String, dynamic> _val(dynamic v) => v == null
      ? {'result': {'type': 'object', 'subtype': 'null', 'value': null}}
      : {'result': {'type': 'object', 'value': v}};

  Future<Map<String, dynamic>> _eval(String e) async {
    onEval?.call(++evals);
    if (!alive) return Completer<Map<String, dynamic>>().future;
    for (final o in overrides.entries) {
      if (e.contains(o.key)) return _val(o.value());
    }
    final l = lesson;
    if (e == '1') return _val(1);
    if (e.contains('location.href') && e.length < 40) return _val(url);
    if (e.contains(stateJs)) {
      return _val([l?.visibleRemaining() ?? '', l?.errs.length ?? 0]);
    }
    if (e.contains(readRemainingJs)) {
      final r = l?.visibleRemaining();
      return _val(r == null || r.isEmpty ? null : r);
    }
    if (e.contains(errCountJs)) return _val(l?.errs.length ?? 0);
    tutorial?.jam = () => clock.now;
    _autoSkor();
    final tu = tutorial;
    if (e.contains(adModalCloseJs)) {
      if (!adUp) return _val([]);
      adUp = false;
      adClosedAt = clock.now;
      return _val(['tutup-teks:"close"']);
    }
    if (e.contains(userWatchJs) && adAt >= 0) return _val(clock.now - adAt);
    if (e.contains(tutRemainJs)) return _val(tu?.remain());
    if (tu != null && e.contains(detectJs)) {
      return _val({
        'std': null,
        'tut': {'text': tu.remain()['rem']},
        'canvases': 0,
      });
    }
    if (e.contains(detectJs)) {
      final r = l?.visibleRemaining();
      return _val({
        'std': (r != null && r.isNotEmpty) ? r : null,
        'canvases': 0,
      });
    }
    if (e.contains(scoreJs)) return _val(scoreShown);
    if (e.contains(profileCheckJs)) return _val(profile);
    if (e.contains(levelLabelJs)) {
      final m = RegExp(r'\d+').firstMatch(l?.label ?? '');
      return _val(m?[0]);
    }
    if (e.contains(lessonGoalJs)) return _val(lessonGoal);
    final g = game;
    if (g != null) {
      if (e.contains(coreMainJs)) return _val(true);
      if (e.contains(gameStatJs)) return _val(g.stat());
      if (e.contains(balloonFeedJs)) {
        if (g.ended) return _val({'ended': true});
        final m = _paceRe.firstMatch(e);
        final mulai = g.spaceStart;
        g.spaceStart = false;
        final cur = g.text[g.idx];
        if (m == null) {
          // tanpa target: rantai cepat 109 ms/huruf (setelah spasi huruf2
          // pertama langsung tersambar)
          for (var i = 0; i < (mulai ? 20 : 1) && !g.ended; i++) {
            g.key(g.text[g.idx], 109);
          }
          return _val({'fed': true, 'idx': g.idx, 'huruf': cur});
        }
        final salah = m[2] == 'true' && RegExp(r'[a-zA-Z]').hasMatch(cur);
        final k = salah ? (cur == 'x' ? 'q' : 'x') : cur;
        g.key(k, int.parse(m[1]!));
        return _val({'fed': true, 'idx': g.idx, 'huruf': k, 'salah': salah, 'paced': true});
      }
      if (e.contains(_balloonStateJs)) {
        if (g.ended) return _val({'ended': true});
        if (g.spaceStart) return _val({'wait': true, 'idx': -1, 'mulai': true});
        return _val({'chr': g.text[g.idx], 'idx': g.idx, 'ended': false});
      }
    }
    if (e.contains(proModalJs)) {
      if (!proModal) return _val(null);
      return _val(proXDead ? {'modal': true} : {'x': 900, 'y': 80});
    }
    if (e.contains(premiumSkipJs)) {
      if (proModal && premiumSkip) proModal = false;
      final v = premiumSkip;
      premiumSkip = false;
      return _val(v);
    }
    if (e.contains(userWatchJs)) return _val(1e6);
    // sisanya (pop-up, video, game, intro, dll) = tidak ada apa-apa
    if (e.contains(focusFrameJs)) return _val(null);
    return _val(null);
  }

  /// teks yang benar2 diterima lesson
  String get typed => lesson?.typed.toString() ?? '';
}
