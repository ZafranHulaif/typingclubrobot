// Backend native hanya ada di desktop (dart:io); build web pakai stub.
export 'factory_stub.dart' if (dart.library.io) 'factory_io.dart';
