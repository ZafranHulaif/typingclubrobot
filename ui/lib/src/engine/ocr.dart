// OCR utk minigame canvas tanpa API core (port engine/lessons/ocr.py,
// bagian winocr). 3.5.x memakai winocr (Windows.Media.Ocr lewat Python).
//
// TODO(N3+): implementasi asli = Windows.Media.Ocr di runner C++
// (ui/windows/runner), dipanggil lewat channel web_host. Sampai itu ada,
// [NoOcr] dipakai: sama persis dgn 3.5.x saat winocr tidak terpasang
// (OCR_AVAILABLE=False) - jalur OCR dilewati, game core API tetap jalan.
import 'dart:typed_data';

class OcrWord {
  const OcrWord(this.text, this.cx, this.cy);

  /// teks kata (belum dibersihkan)
  final String text;

  /// titik tengah kata, ternormalisasi 0..1 terhadap gambar
  final double cx;
  final double cy;
}

abstract interface class OcrService {
  bool get available;

  /// Kenali teks di [png]. [upscale] = perbesar dulu (huruf tunggal balon
  /// jauh lebih terbaca di 3x). Hasil kosong = gagal / tak ada teks.
  Future<List<OcrWord>> recognize(Uint8List png, {int upscale = 1});
}

class NoOcr implements OcrService {
  const NoOcr();
  @override
  bool get available => false;
  @override
  Future<List<OcrWord>> recognize(Uint8List png, {int upscale = 1}) async =>
      const [];
}

/// Kata antarmuka yang bukan bagian permainan (config.UI_WORDS).
const uiWords = {
  'settings', 'setting', 'account', 'profile', 'dashboard', 'school', 'class',
  'teacher', 'student', 'lesson', 'unit', 'level', 'levels', 'score', 'wpm',
  'accuracy', 'akurasi', 'kecepatan', 'practice', 'review', 'test', 'speed',
  'next', 'continue', 'lanjut', 'mulai', 'play', 'start', 'begin', 'pause',
  'menu', 'back', 'restart', 'exit', 'sound', 'music', 'help', 'premium',
  'upgrade', 'langganan', 'berlangganan', 'skip', 'lewati', 'close', 'tutup',
  'ok', 'okay', 'cancel', 'batal', 'save', 'simpan', 'brave', 'edclub',
  'typingclub', 'typing', 'club', 'live', 'progress', 'progres', 'sign',
  'login', 'logout', 'search', 'cari', 'home', 'beranda', 'end', 'fin',
};
