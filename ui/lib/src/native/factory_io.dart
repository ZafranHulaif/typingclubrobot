import '../bridge/bridge.dart';
import 'native_backend.dart';

Backend createNativeBackend(String version) => NativeBackend(version: version);
