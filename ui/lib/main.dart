import 'package:material_ui/material_ui.dart';

import 'src/bridge/bridge.dart';
import 'src/bridge/launch_params.dart';
import 'src/state/store.dart';
import 'src/theme/theme.dart';
import 'src/ui/shell.dart';

void main() {
  final lp = LaunchParams.read();
  final bridge = Bridge(url: lp.url, token: lp.token);
  final store = AppStore(bridge, embedded: lp.embedded);
  bridge.connect();
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
