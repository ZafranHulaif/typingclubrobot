import 'dart:io';

import 'launch_params.dart';

LaunchParams read() {
  final env = Platform.environment;
  final port = env['TYPINGBOT_IPC_PORT'] ?? '8766';
  return LaunchParams(
    Uri.parse('ws://127.0.0.1:$port/'),
    env['TYPINGBOT_IPC_TOKEN'] ?? '',
    embedded: Platform.isWindows && env['TYPINGBOT_IPC_PORT'] != null,
  );
}
