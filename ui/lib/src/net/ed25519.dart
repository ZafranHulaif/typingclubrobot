// Verifikasi tanda tangan Ed25519 (RFC 8032, implementasi referensi
// "slow but simple" pakai BigInt). Cukup utk memeriksa token lisensi
// sesekali; TIDAK dipakai utk menandatangani (kunci privat cuma di server).
import 'dart:typed_data';

import 'package:crypto/crypto.dart' show sha512;

final _p = (BigInt.one << 255) - BigInt.from(19);
final _q = (BigInt.one << 252) + BigInt.parse('27742317777372353535851937790883648493');
final _d = (BigInt.from(-121665) * BigInt.from(121666).modInverse(_p)) % _p;
final _sqrtM1 = BigInt.two.modPow((_p - BigInt.one) ~/ BigInt.from(4), _p);

typedef _Pt = (BigInt, BigInt, BigInt, BigInt);

BigInt _leInt(List<int> b) {
  var r = BigInt.zero;
  for (var i = b.length - 1; i >= 0; i--) {
    r = (r << 8) | BigInt.from(b[i]);
  }
  return r;
}

BigInt? _recoverX(BigInt y, int sign) {
  if (y >= _p) return null;
  final x2 = (y * y - BigInt.one) * (_d * y * y + BigInt.one).modInverse(_p) % _p;
  if (x2 == BigInt.zero) return sign == 1 ? null : BigInt.zero;
  var x = x2.modPow((_p + BigInt.from(3)) ~/ BigInt.from(8), _p);
  if ((x * x - x2) % _p != BigInt.zero) x = x * _sqrtM1 % _p;
  if ((x * x - x2) % _p != BigInt.zero) return null;
  if ((x & BigInt.one).toInt() != sign) x = _p - x;
  return x;
}

_Pt? _decompress(List<int> s) {
  if (s.length != 32) return null;
  var y = _leInt(s);
  final sign = (y >> 255).toInt() & 1;
  y &= (BigInt.one << 255) - BigInt.one;
  final x = _recoverX(y, sign);
  if (x == null) return null;
  return (x, y, BigInt.one, x * y % _p);
}

_Pt _add(_Pt p, _Pt q) {
  final a = (p.$2 - p.$1) * (q.$2 - q.$1) % _p;
  final b = (p.$2 + p.$1) * (q.$2 + q.$1) % _p;
  final c = BigInt.two * p.$4 * q.$4 * _d % _p;
  final d = BigInt.two * p.$3 * q.$3 % _p;
  final e = b - a, f = d - c, g = d + c, h = b + a;
  return (e * f % _p, g * h % _p, f * g % _p, e * h % _p);
}

_Pt _mul(BigInt s, _Pt p) {
  _Pt q = (BigInt.zero, BigInt.one, BigInt.one, BigInt.zero);
  while (s > BigInt.zero) {
    if ((s & BigInt.one) == BigInt.one) q = _add(q, p);
    p = _add(p, p);
    s >>= 1;
  }
  return q;
}

bool _equal(_Pt p, _Pt q) =>
    (p.$1 * q.$3 - q.$1 * p.$3) % _p == BigInt.zero &&
    (p.$2 * q.$3 - q.$2 * p.$3) % _p == BigInt.zero;

final _Pt _g = () {
  final gy = BigInt.from(4) * BigInt.from(5).modInverse(_p) % _p;
  final gx = _recoverX(gy, 0)!;
  return (gx, gy, BigInt.one, gx * gy % _p);
}();

/// True kalau [sig] (64 byte) sah utk [msg] dgn kunci publik [pub] (32 byte).
bool ed25519Verify(List<int> pub, List<int> msg, List<int> sig) {
  if (pub.length != 32 || sig.length != 64) return false;
  final a = _decompress(pub);
  if (a == null) return false;
  final rs = sig.sublist(0, 32);
  final r = _decompress(rs);
  if (r == null) return false;
  final s = _leInt(sig.sublist(32));
  if (s >= _q) return false;
  final h = _leInt(sha512.convert(Uint8List.fromList([...rs, ...pub, ...msg])).bytes) % _q;
  return _equal(_mul(s, _g), _add(r, _mul(h, a)));
}

List<int> hexBytes(String hex) {
  final h = hex.trim();
  if (h.length.isOdd) throw const FormatException('hex ganjil');
  return [for (var i = 0; i < h.length; i += 2) int.parse(h.substring(i, i + 2), radix: 16)];
}
