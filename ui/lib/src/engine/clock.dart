// Jam mesin: semua jeda & waktu lewat sini supaya tes bisa memakai jam
// palsu (tidur instan, waktu maju sendiri). Satuan detik (double) biar
// port dari python (time.time / time.sleep) tetap mirip aslinya.
import 'dart:async';

abstract class Clock {
  /// Detik sejak titik acuan (monoton).
  double get now;

  /// Tidur [seconds] detik.
  Future<void> sleep(double seconds);
}

class SystemClock implements Clock {
  SystemClock() : _sw = Stopwatch()..start();
  final Stopwatch _sw;
  // titik acuan = jam dinding saat dibuat (angka mirip time.time())
  final double _base = DateTime.now().millisecondsSinceEpoch / 1000.0;

  @override
  double get now => _base + _sw.elapsedMicroseconds / 1e6;

  @override
  Future<void> sleep(double seconds) => seconds <= 0
      ? Future<void>.delayed(Duration.zero)
      : Future<void>.delayed(
          Duration(microseconds: (seconds * 1e6).round()));
}

/// Jam palsu utk tes: sleep memajukan waktu lalu langsung kembali.
class FakeClock implements Clock {
  FakeClock([this._t = 1000.0]);
  double _t;
  final sleeps = <double>[];

  @override
  double get now => _t;

  void advance(double s) => _t += s;

  @override
  Future<void> sleep(double seconds) async {
    if (seconds > 0) {
      _t += seconds;
      sleeps.add(seconds);
    }
    // beri giliran ke microtask lain (event bridge palsu dst)
    await Future<void>.delayed(Duration.zero);
  }
}
