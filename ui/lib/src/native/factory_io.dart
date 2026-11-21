import '../bridge/bridge.dart';
import '../state/store.dart';
import 'native_backend.dart';
import 'selftest.dart';

Backend createNativeBackend(String version) => NativeBackend(version: version);

/// Uji mandiri CI (TB_SELFTEST); null = tidak aktif.
void maybeSelfTest(AppStore s) {
  final d = selfTestDir();
  if (d != null) runSelfTest(s, d);
}
