import '../bridge/bridge.dart';
import '../state/store.dart';

Backend createNativeBackend(String version) =>
    throw UnsupportedError('backend native hanya di Windows');

void maybeSelfTest(AppStore s) {}
