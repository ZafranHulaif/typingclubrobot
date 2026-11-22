import '../bridge/bridge.dart';
import '../state/store.dart';
import 'native_backend.dart';
import 'mac_selftest.dart';
import 'selftest.dart';

Backend createNativeBackend(String version) => NativeBackend(version: version);

/// Uji mandiri CI (TB_SELFTEST); null = tidak aktif.
void maybeSelfTest(AppStore s) {
  final d = selfTestDir();
  if (d != null) runSelfTest(s, d);
}

/// Uji mandiri macOS (TB_MACTEST): jalan TANPA app biasa. true = aktif.
bool maybeMacSelfTest() {
  final d = macTestDir();
  if (d == null) return false;
  runMacSelfTest(d);
  return true;
}
