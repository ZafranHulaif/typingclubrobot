import 'launch_params.dart';

LaunchParams read() {
  final q = Uri.base.queryParameters;
  final host = q['host'] ?? '127.0.0.1';
  return LaunchParams(
    Uri.parse('ws://$host:${q['port'] ?? '8766'}/'),
    q['token'] ?? '',
  );
}
