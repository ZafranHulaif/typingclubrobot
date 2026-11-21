import 'package:material_ui/material_ui.dart';

import 'src/bridge/bridge.dart';
import 'src/bridge/launch_params.dart';
import 'src/native/factory.dart';
import 'src/state/store.dart';
import 'src/theme/theme.dart';
import 'src/ui/shell.dart';
import 'src/version.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final lp = LaunchParams.read();
  // Windows: semua di dalam proses. Preview (web/Linux): sidecar mock.
  final Backend backend = lp.embedded
      ? createNativeBackend(appVersion)
      : Bridge(url: lp.url, token: lp.token);
  final store = AppStore(backend, embedded: lp.embedded);
  backend.connect();
  runApp(TypingBotApp(store: store));
}

class TypingBotApp extends StatelessWidget {
  const TypingBotApp({super.key, required this.store});
  final AppStore store;

  @override
  Widget build(BuildContext context) {
    return StoreScope(
      store: store,
      child: MaterialApp(
        title: 'TypingBot',
        debugShowCheckedModeBanner: false,
        theme: buildTheme(),
        home: const Shell(),
      ),
    );
  }
}
