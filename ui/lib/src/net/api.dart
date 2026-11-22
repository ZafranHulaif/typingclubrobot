// Port net/api.py: HTTP tipis ke worker TypingBot (kontrak di
// server/API.md - JANGAN diubah). Cloudflare menolak User-Agent bukan
// browser di sebagian jalur, jadi UA mirip browser + penanda TypingBot.
import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart' show sha256;

const defaultBaseUrl = 'https://typingbot-api.zafranhulaif.workers.dev';

String userAgent(String version) =>
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) TypingBot/$version '
    '(+github.com/ZafranHulaif/typingclubrobot)';

/// Server tidak bisa dihubungi (offline / URL salah).
class Unreachable implements Exception {
  Unreachable(this.message);
  final String message;
  @override
  String toString() => 'Unreachable: $message';
}

class Cancelled implements Exception {}

class Api {
  Api({required this.baseUrl, required this.version, HttpClient? client})
      : _client = client ?? HttpClient();

  /// BASE_URL: env TYPINGBOT_SERVER_URL, lalu server_url.txt di folder
  /// data, lalu bawaan (sama urutannya dgn 3.5.x).
  factory Api.resolve({required String dataDir, required String version}) {
    var v = Platform.environment['TYPINGBOT_SERVER_URL'] ?? '';
    if (v.isEmpty) {
      try {
        final f = File('$dataDir${Platform.pathSeparator}server_url.txt');
        if (f.existsSync()) v = f.readAsStringSync().trim();
      } catch (_) {}
    }
    if (v.isEmpty) v = defaultBaseUrl;
    while (v.endsWith('/')) {
      v = v.substring(0, v.length - 1);
    }
    return Api(baseUrl: v, version: version);
  }

  final String baseUrl;
  final String version;
  final HttpClient _client;

  /// (status, json). Lempar [Unreachable] bila koneksi gagal.
  Future<(int, Map<String, dynamic>)> json(String method, String path,
      {Object? body, Duration timeout = const Duration(seconds: 6)}) async {
    try {
      final req = await _client.openUrl(method, Uri.parse(baseUrl + path)).timeout(timeout);
      req.headers.set(HttpHeaders.userAgentHeader, userAgent(version));
      if (body != null) {
        req.headers.contentType = ContentType('application', 'json', charset: 'utf-8');
        req.add(utf8.encode(jsonEncode(body)));
      }
      final res = await req.close().timeout(timeout);
      final raw = await res.transform(utf8.decoder).join().timeout(timeout);
      Map<String, dynamic> data = {};
      if (raw.trim().isNotEmpty) {
        try {
          final d = jsonDecode(raw);
          if (d is Map) data = Map<String, dynamic>.from(d);
        } catch (_) {}
      }
      return (res.statusCode, data);
    } on Exception catch (e) {
      throw Unreachable('$e');
    }
  }

  /// macOS: rilis GitHub terbaru yang punya aset TypingBot-mac.zip
  /// ({version, notes, size, sha256, url}), atau null.
  Future<Map<String, dynamic>?> latestMacRelease(
      {String repo = 'ZafranHulaif/typingclubrobot'}) async {
    try {
      final req = await _client
          .getUrl(Uri.parse('https://api.github.com/repos/$repo/releases?per_page=15'))
          .timeout(const Duration(seconds: 8));
      req.headers.set(HttpHeaders.userAgentHeader, userAgent(version));
      req.headers.set(HttpHeaders.acceptHeader, 'application/vnd.github+json');
      final res = await req.close().timeout(const Duration(seconds: 8));
      final raw = await res.transform(utf8.decoder).join().timeout(const Duration(seconds: 8));
      if (res.statusCode != 200) return null;
      return pickMacRelease(jsonDecode(raw));
    } on Exception catch (e) {
      throw Unreachable('$e');
    }
  }

  /// Pilih rilis (bukan draft/prarilis) bervers tertinggi yang membawa
  /// TypingBot-mac.zip. Dipisah biar bisa dites.
  static Map<String, dynamic>? pickMacRelease(dynamic list) {
    if (list is! List) return null;
    Map<String, dynamic>? best;
    List<int> ver(String s) => [
          for (final x in s.replaceFirst(RegExp(r'^v'), '').split('-').first.split('.'))
            int.tryParse(x) ?? 0
        ];
    bool lebih(List<int> a, List<int> b) {
      for (var i = 0; i < 3; i++) {
        final x = i < a.length ? a[i] : 0, y = i < b.length ? b[i] : 0;
        if (x != y) return x > y;
      }
      return false;
    }

    for (final r in list) {
      if (r is! Map || r['draft'] == true || r['prerelease'] == true) continue;
      final tag = '${r['tag_name'] ?? ''}';
      Map? aset;
      for (final a in (r['assets'] as List? ?? const [])) {
        if (a is Map && a['name'] == 'TypingBot-mac.zip') aset = a;
      }
      if (aset == null || tag.isEmpty) continue;
      final v = tag.replaceFirst(RegExp(r'^v'), '');
      if (best != null && !lebih(ver(v), ver('${best['version']}'))) continue;
      final dg = '${aset['digest'] ?? ''}';
      final body = '${r['body'] ?? ''}'.trim();
      best = {
        'version': v,
        'notes': body.length > 300 ? '${body.substring(0, 300)}...' : body,
        'size': (aset['size'] as num?)?.toInt() ?? 0,
        'sha256': dg.startsWith('sha256:') ? dg.substring(7) : '',
        'url': '${aset['browser_download_url'] ?? ''}',
      };
    }
    return best;
  }

  /// Info rilis terbaru, atau null bila belum ada.
  Future<Map<String, dynamic>?> fetchLatest() async {
    final (st, data) = await json('GET', '/api/latest');
    return st == 200 ? data : null;
  }

  /// Unduh ke [dest].part lalu rename; hasil = sha256 hex. [progress]
  /// mengembalikan false = batal ([Cancelled]).
  Future<String> download(String pathOrUrl, String dest,
      {bool Function(int got, int? total)? progress,
      Duration timeout = const Duration(seconds: 60)}) async {
    final url = pathOrUrl.contains('://') ? pathOrUrl : baseUrl + pathOrUrl;
    final part = File('$dest.part');
    var got = 0;
    final chunks = <List<int>>[];
    try {
      final req = await _client.getUrl(Uri.parse(url)).timeout(timeout);
      req.headers.set(HttpHeaders.userAgentHeader, userAgent(version));
      final res = await req.close().timeout(timeout);
      if (res.statusCode != 200) throw Unreachable('HTTP ${res.statusCode}');
      final total = res.contentLength >= 0 ? res.contentLength : null;
      final sink = part.openWrite();
      try {
        await for (final b in res.timeout(timeout)) {
          got += b.length;
          chunks.add(b);
          sink.add(b);
          if (progress != null && progress(got, total) == false) throw Cancelled();
        }
      } finally {
        await sink.close();
      }
    } on Cancelled {
      _rm(part);
      rethrow;
    } on Exception catch (e) {
      _rm(part);
      throw e is Unreachable ? e : Unreachable('$e');
    }
    final f = File(dest);
    if (f.existsSync()) f.deleteSync();
    part.renameSync(dest);
    return sha256.convert(chunks.expand((c) => c).toList()).toString();
  }

  void _rm(File f) {
    try {
      if (f.existsSync()) f.deleteSync();
    } catch (_) {}
  }
}
