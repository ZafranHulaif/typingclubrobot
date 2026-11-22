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
      if (p['type'] == 'keyDown' || p['type'] == 'rawKeyDown') _onKey(p);
      return {};
    };
    b.handlers['Input.dispatchMouseEvent'] = (p, s) {
      if (p['type'] == 'mousePressed') clicks.add(Point(p['x'] as num, p['y'] as num));
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
    if (e.contains(premiumSkipJs)) {
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
