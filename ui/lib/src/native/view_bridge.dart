// Adaptor: WebView native (web_host.dart) -> CdpBridge mesin bot.
import '../engine/page.dart';
import '../web/web_host.dart';

class WebViewBridge implements CdpBridge {
  WebViewBridge(this.view);
  final WebView view;

  @override
  Future<Map<String, dynamic>> send(String method,
      [Map<String, dynamic>? params, String session = '']) async {
    try {
      return await view.cdp(method, params, session);
    } on WebHostException catch (e) {
      throw PageError('$method: ${e.message}');
    }
  }

  @override
  Stream<CdpEvent> listen(String method) => view
      .onSession(method)
      .map((e) => CdpEvent(method, e.params, e.session));
}
