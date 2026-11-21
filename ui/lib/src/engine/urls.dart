// Aturan URL edclub (port fungsi murni engine/browser.py). Semua cek
// "sedang di level" & normalisasi rute lesson lewat sini.

String _host(String url) {
  try {
    return Uri.parse(url).host.toLowerCase();
  } catch (_) {
    return '';
  }
}

String _path(String url) {
  try {
    return Uri.parse(url).path.toLowerCase();
  } catch (_) {
    return '';
  }
}

/// Hostname ASLI edclub/typingclub (bukan substring: URL Stripe yang
/// menyebut edclub.com di parameternya pernah menipu cek substring).
bool isEdclubUrl(String url) {
  final h = _host(url);
  return h.endsWith('edclub.com') || h.endsWith('typingclub.com');
}

/// URL di tengah alur OAuth/login eksternal (pilih akun Google dll):
/// jangan disentuh healing apa pun.
bool isOauthUrl(String url) {
  final h = _host(url);
  return h.endsWith('accounts.google.com') ||
      h.endsWith('accounts.youtube.com') ||
      h.endsWith('googleusercontent.com') ||
      _path(url).contains('auth_callback');
}

final _routeRe = RegExp(r'/student/course/(\d+)/lesson/(\d+)');
final _playRe = RegExp(r'/program-(\d+)/(\d+)\.play');

/// `/student/course/C/lesson/ID` -> `.../program-C/ID.play` (bentuk
/// internal; id lesson-nya sama).
String lessonPlayUrl(String u) {
  if (u.isEmpty || !u.contains('/lesson/')) return u;
  final m = _routeRe.firstMatch(u);
  if (m == null) return u;
  return 'https://www.edclub.com/sportal/program-${m[1]}/${m[2]}.play';
}

/// URL = halaman lesson (rute .play klasik ATAU /lesson/ UI baru).
bool diLesson(String? u) =>
    u != null && u.isNotEmpty && (u.contains('/lesson/') || u.contains('.play'));

/// URL lesson -> rute UI baru utk navigasi yang terlihat user.
String lessonRouteUrl(String u) {
  if (u.isEmpty) return u;
  final m = _playRe.firstMatch(u);
  if (m != null) {
    return 'https://www.edclub.com/student/course/${m[1]}/lesson/${m[2]}';
  }
  return u;
}

/// Frame milik edclub? (frame Stripe checkout tak boleh disentuh;
/// edclub.app = player video & game UI baru).
bool isEdclubFrameUrl(String u) {
  if (u.isEmpty || u.startsWith('about:')) return true;
  final h = _host(u);
  return h.endsWith('edclub.com') ||
      h.endsWith('typingclub.com') ||
      h.endsWith('edclub.app');
}

/// id lesson dari URL bentuk .play.
int? lessonId(String? url) {
  final m = _playRe.firstMatch(url ?? '');
  return m == null ? null : int.parse(m[2]!);
}

/// URL tampak halaman login/daftar.
bool looksLikeLogin(String url) {
  final low = url.toLowerCase();
  return low.contains('login') ||
      low.contains('signin') ||
      low.contains('sign-in') ||
      low.contains('signup');
}

/// Bagian terakhir URL (utk log singkat).
String tail(String url) {
  final i = url.lastIndexOf('/');
  return i < 0 ? url : url.substring(i + 1);
}
