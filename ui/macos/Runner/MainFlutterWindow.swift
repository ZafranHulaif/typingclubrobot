import Cocoa
import FlutterMacOS

class MainFlutterWindow: NSWindow {
  // host WKWebView (pasangan web_host.cpp Windows), hidup selama jendela
  var webHost: WebHost?

  override func awakeFromNib() {
    // tahan tombol (level 'tahan j') jangan memunculkan menu aksen macOS
    UserDefaults.standard.set(false, forKey: "ApplePressAndHoldEnabled")
    let flutterViewController = FlutterViewController()
    let windowFrame = self.frame
    self.contentViewController = flutterViewController
    self.setFrame(windowFrame, display: true)
    self.title = "TypingBot"
    self.minSize = NSSize(width: 900, height: 600)
    // ukuran awal spt Windows (1280x800), di tengah layar
    self.setContentSize(NSSize(width: 1280, height: 800))
    self.center()

    RegisterGeneratedPlugins(registry: flutterViewController)
    webHost = WebHost(messenger: flutterViewController.engine.binaryMessenger,
                      container: flutterViewController.view)

    super.awakeFromNib()
  }
}
