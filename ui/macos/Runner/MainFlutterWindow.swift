import Cocoa
import FlutterMacOS

class MainFlutterWindow: NSWindow {
  // host WKWebView (pasangan web_host.cpp Windows), hidup selama jendela
  var webHost: WebHost?

  override func awakeFromNib() {
    let flutterViewController = FlutterViewController()
    let windowFrame = self.frame
    self.contentViewController = flutterViewController
    self.setFrame(windowFrame, display: true)
    self.title = "TypingBot"
    self.minSize = NSSize(width: 900, height: 600)

    RegisterGeneratedPlugins(registry: flutterViewController)
    webHost = WebHost(messenger: flutterViewController.engine.binaryMessenger,
                      container: flutterViewController.view)

    super.awakeFromNib()
  }
}
