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

class FakeEdclub {
  FakeEdclub({String url = 'https://www.edclub.com/student/course/3/lesson/116', this.keyCostMs = 0})
      : bridge = FakeBridge(),
        clock = FakeClock() {
    this.url = url;
    final b = bridge;
    b.handlers['Page.getFrameTree'] = (p, s) => {
          'frameTree': {
            'frame': {'id': 'MAIN', 'url': this.url}
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
      _go(this.url);
      return {};
    };
  }

  final FakeBridge bridge;
  final FakeClock clock;
  final double keyCostMs;
  late String url;
  FakeLesson? lesson;
  final keyEvents = <Map<String, dynamic>>[];
  final clicks = <Point>[];
  final navigations = <String>[];
  int reloads = 0;
  int enterOnScore = 0;

  /// penanda login di DOM: 'in' / 'out' / null
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
    if (l.done) scoreShown = true;
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
