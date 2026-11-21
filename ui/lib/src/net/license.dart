// Port net/license.py + bagian lisensi gui/licensing.py. Kontrak SAMA
// dgn 3.5.x (server/API.md): token {mc, exp, sig} Ed25519 atas
// "v1|{mc}|{exp}", license.dat satu baris JSON {"v":1,"token":...}
// atau kunci HMAC lama (teks).
import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart' show Hmac, sha256;

import 'api.dart';
import 'ed25519.dart';

const serverPublicKeyHex =
    '0e93efe0f59f9af8dd1bf514aac9cec553aa02d4c2b8ca7da5688b1936ab48a2';

/// Rahasia kunci lama (HMAC). Nilai asli TIDAK ada di repo
/// (_license_secret.py di-gitignore): isi saat build dgn
/// --dart-define=TB_LICENSE_SECRET=... supaya kunci manual lama tetap sah.
const _secretEnv = String.fromEnvironment('TB_LICENSE_SECRET');
const licenseSecret = _secretEnv == '' ? 'DEV-ONLY-BUKAN-SECRET-ASLI' : _secretEnv;

/// Kunci publik pengganti utk tes (null = env / kunci server asli).
String? debugPublicKeyHex;

String _pubHex() {
  if (debugPublicKeyHex != null) return debugPublicKeyHex!;
  final env = Platform.environment['TYPINGBOT_SERVER_PUBKEY'] ?? '';
  return env.isNotEmpty ? env : serverPublicKeyHex;
}

List<int> tokenMessage(Map tok) => utf8.encode('v1|${tok['mc']}|${tok['exp']}');

int _nowS() => DateTime.now().millisecondsSinceEpoch ~/ 1000;

/// Cek tanda tangan + kedaluwarsa (offline). True = masih sah.
bool verifyToken(Object? tok, {int? now, String? pubHex}) {
  if (tok is! Map) return false;
  try {
    final exp = int.parse('${tok['exp']}');
    if (exp < (now ?? _nowS())) return false;
    return ed25519Verify(hexBytes(pubHex ?? _pubHex()), tokenMessage(tok), hexBytes('${tok['sig']}'));
  } catch (_) {
    return false;
  }
}

int daysLeft(Object? tok, {int? now}) {
  try {
    final exp = int.parse('${(tok as Map)['exp']}');
    final d = (exp - (now ?? _nowS())) ~/ 86400;
    return d < 0 ? 0 : d;
  } catch (_) {
    return 0;
  }
}

Map<String, dynamic>? loadToken(String path) {
  try {
    final isi = File(path).readAsStringSync().trim();
    if (!isi.startsWith('{')) return null;
    final t = (jsonDecode(isi) as Map)['token'];
    return t is Map ? Map<String, dynamic>.from(t) : null;
  } catch (_) {
    return null;
  }
}

void saveToken(String path, Map tok) =>
    File(path).writeAsStringSync(jsonEncode({'v': 1, 'token': tok}));

/// Huruf base32 saja, kapital (sama dgn _norm).
String norm(String s) => s
    .toUpperCase()
    .split('')
    .where((c) => 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'.contains(c))
    .join();

const _b32 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';

String base32(List<int> data) {
  final out = StringBuffer();
  var buf = 0, bits = 0;
  for (final b in data) {
    buf = (buf << 8) | b;
    bits += 8;
    while (bits >= 5) {
      out.write(_b32[(buf >> (bits - 5)) & 31]);
      bits -= 5;
    }
    buf &= (1 << bits) - 1;
  }
  if (bits > 0) out.write(_b32[(buf << (5 - bits)) & 31]);
  return out.toString();
}

/// Kode mesin "XXXXX-XXXXX" dari sidik jari (lihat machine.dart).
String machineCodeFrom(String machineData) {
  final k = base32(sha256.convert(utf8.encode(machineData)).bytes).substring(0, 10);
  return '${k.substring(0, 5)}-${k.substring(5)}';
}

/// Kunci manual lama: HMAC-SHA256(secret, norm(kode)) -> base32[:20].
String makeKey(String kodeMesin, [String secret = licenseSecret]) {
  final dig = Hmac(sha256, utf8.encode(secret)).convert(utf8.encode(norm(kodeMesin))).bytes;
  final b = base32(dig).substring(0, 20);
  return [for (var i = 0; i < 20; i += 5) b.substring(i, i + 5)].join('-');
}

String savedLicense(String path) {
  try {
    return File(path).readAsStringSync().trim();
  } catch (_) {
    return '';
  }
}

/// license.dat sah? (token online ATAU kunci HMAC lama utk mesin ini)
bool licenseValid(String path, String machineCode, {String secret = licenseSecret}) {
  final s = savedLicense(path);
  if (s.startsWith('{')) return verifyToken(loadToken(path));
  return s.isNotEmpty && norm(s) == norm(makeKey(machineCode, secret));
}

Future<Map<String, dynamic>> requestApproval(Api api, String mc, String nickname, String appVersion) async {
  final (_, data) = await api.json('POST', '/api/license/request',
      body: {'mc': mc, 'nickname': nickname, 'app_version': appVersion});
  return data;
}

Future<Map<String, dynamic>> fetchStatus(Api api, String mc) async {
  final (_, data) = await api.json('GET', '/api/license/status?mc=${mc.replaceAll('-', '%2D')}');
  return data;
}

/// Parameter ?t= utk /api/download (base64 JSON token, di-URL-encode).
String downloadParam(Map tok) => Uri.encodeComponent(base64.encode(utf8.encode(jsonEncode(tok))));
