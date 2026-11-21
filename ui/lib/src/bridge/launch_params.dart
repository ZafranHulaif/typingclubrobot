// Alamat + token sidecar. Desktop: env dari peluncur (TypingBot.exe).
// Web (preview dev): query ?port=..&token=..
import 'launch_params_io.dart'
    if (dart.library.js_interop) 'launch_params_web.dart' as impl;

class LaunchParams {
  const LaunchParams(this.url, this.token, {this.embedded = false});
  final Uri url;
  final String token;

  /// true = jendela desktop Windows: WebView2 native di dalam proses,
  /// backend Dart (tanpa sidecar)
  final bool embedded;

  static LaunchParams read() => impl.read();
}
