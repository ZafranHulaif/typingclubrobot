// Tombol 'Move on' layar hasil game: tetap ketemu walau animasi masuknya
// beku di skala ~0 (app disembunyikan / diperkecil).
import 'package:flutter_test/flutter_test.dart';
import 'package:typingbot/src/engine/engine.dart';

void main() {
  test('pencari tombol maju punya cadangan ukuran tata letak', () {
    final js = majuJsForTest;
    expect(js, contains('el.offsetWidth >= 30'));
    expect(js, isNot(contains('const r = el.getBoundingClientRect();')));
    expect(js, contains("'move on'"));
  });
}
