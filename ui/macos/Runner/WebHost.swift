// Host WKWebView utk macOS: pasangan ui/windows/runner/web_host.cpp.
// Kanal & nama metode SAMA dgn Windows (lib/src/web/web_host.dart), plus
// primitif khusus Mac yang dipakai peniru CDP (lib/src/web/wk_cdp.dart):
// evalFrame, key, insertText, mouse, cookies, setCookie, clearCookies,
// clearData, snapshot, history.
//
// Semua koordinat dari Dart = piksel fisik relatif ke pojok kiri-atas
// area isi jendela (sama dgn Windows); di sini dibagi backingScaleFactor.
import Cocoa
import CryptoKit
import FlutterMacOS
import WebKit

// Lapor diri tiap frame (termasuk iframe lintas origin) ke host: id acak
// per dokumen, url, utama/bukan. Dipakai peniru CDP utk daftar frame.
private let frameReporterJS = """
(() => {
  if (window.__tbFid) return;
  const fid = 'f' + Math.random().toString(36).slice(2) + Date.now().toString(36);
  try { Object.defineProperty(window, '__tbFid', {value: fid}); } catch (e) { window.__tbFid = fid; }
  const post = (phase) => {
    try {
      window.webkit.messageHandlers.tbframe.postMessage({
        fid: fid, phase: phase, url: location.href, name: window.name || '',
        main: window === window.top
      });
    } catch (e) {}
  };
  post('hello');
  // ack tiap event tombol yang benar2 diproses halaman: host baru
  // menjawab panggilan 'key' sesudah ack (antrean tombol WebKit bisa
  // disalip evaluasi -> bot membaca teks basi lalu mengetik ulang)
  const ack = () => { try { window.webkit.messageHandlers.tbkey.postMessage(1); } catch (e) {} };
  addEventListener('keydown', ack, true);
  addEventListener('keyup', ack, true);
  addEventListener('pagehide', () => post('bye'));
  const wrap = (k) => {
    const o = history[k];
    history[k] = function () { const r = o.apply(this, arguments); post('hash'); return r; };
  };
  try { wrap('pushState'); wrap('replaceState'); } catch (e) {}
  addEventListener('popstate', () => post('hash'));
  addEventListener('hashchange', () => post('hash'));
})();
"""

/// WKWebView yang lapor saat diklik/difokus user (popup Flutter tutup).
final class TBWebView: WKWebView {
  var onFocus: (() -> Void)?
  override func becomeFirstResponder() -> Bool {
    let ok = super.becomeFirstResponder()
    if ok { onFocus?() }
    return ok
  }
}

/// Penerus pesan tanpa retain cycle (WKUserContentController menahan handler).
private final class WeakHandler: NSObject, WKScriptMessageHandler {
  weak var target: WKScriptMessageHandler?
  init(_ t: WKScriptMessageHandler) { target = t }
  func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) {
    target?.userContentController(c, didReceive: m)
  }
}

final class WebHostView: NSObject, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler {
  let id: Int
  let web: TBWebView
  unowned let host: WebHost
  var scripts: [String: String] = [:]  // sid -> js
  var baseScripts: [String] = []
  var frames: [String: WKFrameInfo] = [:]
  var obs: [NSKeyValueObservation] = []
  var sidSeq = 0
  var keyWaiters: [(id: Int, done: FlutterResult)] = []
  var keySeq = 0

  /// Jawab panggilan 'key' sesudah halaman memproses event-nya (atau
  /// batas waktu: tombol yang tidak memicu event DOM tidak menggantung).
  func waitKeyAck(_ result: @escaping FlutterResult) {
    keySeq += 1
    let k = keySeq
    keyWaiters.append((id: k, done: result))
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) { [weak self] in
      guard let s = self, let i = s.keyWaiters.firstIndex(where: { $0.id == k }) else { return }
      let w = s.keyWaiters.remove(at: i)
      w.done(nil)
    }
  }

  func keyAcked() {
    guard !keyWaiters.isEmpty else { return }
    keyWaiters.removeFirst().done(nil)
  }

  init(id: Int, folder: String, scripts: [String], host: WebHost) {
    self.id = id
    self.host = host
    self.baseScripts = scripts
    let cfg = WKWebViewConfiguration()
    if #available(macOS 14.0, *) {
      // satu folder data = satu jar akun (spt user data folder WebView2)
      cfg.websiteDataStore = WKWebsiteDataStore(forIdentifier: WebHost.uuid(folder))
    } else {
      cfg.websiteDataStore = .default()
    }
    cfg.preferences.javaScriptCanOpenWindowsAutomatically = true
    // jalan di latar: WebKit memperlambat timer & menangguhkan proses halaman
    // yang tak terlihat. Matikan (setter privat, dicek dulu: tak ada = lewat).
    WebHostView.setFlag(cfg.preferences, "_setHiddenPageDOMTimerThrottlingEnabled:", false)
    WebHostView.setFlag(cfg.preferences, "_setPageVisibilityBasedProcessSuppressionEnabled:", false)
    cfg.mediaTypesRequiringUserActionForPlayback = []
    web = TBWebView(frame: .zero, configuration: cfg)
    // UA Safari lengkap: tanpa "Version/.. Safari/.." Google menolak login
    // di webview tertanam ("browser ini mungkin tidak aman")
    web.customUserAgent = WebHost.safariUA
    super.init()
    cfg.userContentController.add(WeakHandler(self), name: "tbframe")
    cfg.userContentController.add(WeakHandler(self), name: "tbkey")
    reinstallScripts()
    web.navigationDelegate = self
    web.uiDelegate = self
    web.allowsBackForwardNavigationGestures = false
    // jendela tertutup app lain = halaman tetap dianggap terlihat
    // (requestAnimationFrame, game & video tetap jalan)
    WebHostView.setFlag(web, "_setWindowOcclusionDetectionEnabled:", false)
    web.setValue(false, forKey: "drawsBackground")
    web.onFocus = { [weak self] in
      guard let s = self else { return }
      s.host.emit(s.id, "focus", [:])
    }
    obs.append(web.observe(\.title, options: [.new]) { [weak self] w, _ in
      guard let s = self else { return }
      s.host.emit(s.id, "title", ["title": w.title ?? ""])
    })
    obs.append(web.observe(\.url, options: [.new]) { [weak self] w, _ in
      guard let s = self else { return }
      s.host.emit(s.id, "source", ["url": w.url?.absoluteString ?? ""])
    })
  }

  /// Panggil setter privat BOOL kalau ada (versi WebKit lain bisa tak punya).
  static func setFlag(_ o: NSObject, _ name: String, _ on: Bool) {
    let sel = NSSelectorFromString(name)
    guard o.responds(to: sel) else {
      NSLog("TypingBot: %@ tidak ada", name)
      return
    }
    typealias Fn = @convention(c) (AnyObject, Selector, Bool) -> Void
    unsafeBitCast(o.method(for: sel), to: Fn.self)(o, sel, on)
  }

  func reinstallScripts() {
    let ucc = web.configuration.userContentController
    ucc.removeAllUserScripts()
    ucc.addUserScript(WKUserScript(source: frameReporterJS, injectionTime: .atDocumentStart,
                                   forMainFrameOnly: false))
    for js in baseScripts + scripts.keys.sorted().compactMap({ scripts[$0] }) {
      ucc.addUserScript(WKUserScript(source: js, injectionTime: .atDocumentStart,
                                     forMainFrameOnly: false))
    }
  }

  func dispose() {
    obs.removeAll()
    web.configuration.userContentController.removeScriptMessageHandler(forName: "tbframe")
    web.configuration.userContentController.removeScriptMessageHandler(forName: "tbkey")
    while !keyWaiters.isEmpty { keyWaiters.removeFirst().done(nil) }
    web.stopLoading()
    web.navigationDelegate = nil
    web.uiDelegate = nil
    web.removeFromSuperview()
  }

  // ---------------------------------------------------------------- frame
  func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) {
    if m.name == "tbkey" {
      keyAcked()
      return
    }
    guard m.name == "tbframe", let b = m.body as? [String: Any],
          let fid = b["fid"] as? String else { return }
    let phase = b["phase"] as? String ?? ""
    if phase == "bye" {
      frames.removeValue(forKey: fid)
    } else {
      if m.frameInfo.isMainFrame && phase == "hello" {
        // dokumen utama baru: frame lama sudah tidak ada
        frames.removeAll()
      }
      frames[fid] = m.frameInfo
    }
    host.emit(id, "frame", [
      "fid": fid, "phase": phase,
      "url": b["url"] as? String ?? "",
      "name": b["name"] as? String ?? "",
      "main": m.frameInfo.isMainFrame,
    ])
  }

  // ---------------------------------------------------------------- navigasi
  func webView(_ w: WKWebView, didStartProvisionalNavigation n: WKNavigation!) {
    host.emit(id, "nav", ["phase": "start", "url": w.url?.absoluteString ?? ""])
  }

  func webView(_ w: WKWebView, didFinish n: WKNavigation!) {
    host.emit(id, "nav", ["phase": "done", "ok": true, "error": 0,
                          "url": w.url?.absoluteString ?? ""])
  }

  func webView(_ w: WKWebView, didFail n: WKNavigation!, withError e: Error) {
    navFailed(w, e)
  }

  func webView(_ w: WKWebView, didFailProvisionalNavigation n: WKNavigation!, withError e: Error) {
    navFailed(w, e)
  }

  private func navFailed(_ w: WKWebView, _ e: Error) {
    let ns = e as NSError
    // dibatalkan krn navigasi baru = bukan error
    if ns.domain == NSURLErrorDomain && ns.code == NSURLErrorCancelled { return }
    host.emit(id, "nav", ["phase": "done", "ok": false, "error": ns.code,
                          "url": w.url?.absoluteString ?? ""])
  }

  func webViewWebContentProcessDidTerminate(_ w: WKWebView) {
    host.emit(id, "crash", ["kind": 1])
  }

  // popup = navigasi di halaman yang sama (tanpa jendela kedua), spt Windows
  func webView(_ w: WKWebView, createWebViewWith c: WKWebViewConfiguration,
               for a: WKNavigationAction, windowFeatures f: WKWindowFeatures) -> WKWebView? {
    let u = a.request.url?.absoluteString ?? ""
    if !u.isEmpty && u != "about:blank" { w.load(a.request) }
    host.emit(id, "newWindow", ["url": u])
    return nil
  }

  func webView(_ w: WKWebView, runJavaScriptAlertPanelWithMessage m: String,
               initiatedByFrame f: WKFrameInfo, completionHandler done: @escaping () -> Void) {
    done()
  }

  func webView(_ w: WKWebView, runJavaScriptConfirmPanelWithMessage m: String,
               initiatedByFrame f: WKFrameInfo, completionHandler done: @escaping (Bool) -> Void) {
    done(true)
  }
}

final class WebHost: NSObject {
  let channel: FlutterMethodChannel
  weak var container: NSView?
  var views: [Int: WebHostView] = [:]
  // selama bot jalan: App Nap & tidur saat diam dimatikan
  var awake: NSObjectProtocol?
  var rect = NSRect.zero  // piksel fisik, relatif pojok kiri-atas
  var holes: [NSRect] = []
  var holeRadius: CGFloat = 0
  var lastMouse = NSPoint.zero

  init(messenger: FlutterBinaryMessenger, container: NSView) {
    channel = FlutterMethodChannel(name: "typingbot/web_host", binaryMessenger: messenger)
    self.container = container
    super.init()
    channel.setMethodCallHandler { [weak self] call, result in
      guard let s = self else { return result(nil) }
      s.handle(call, result)
    }
  }

  static let safariUA: String = {
    let v = ProcessInfo.processInfo.operatingSystemVersion
    // Safari asli di macOS 11+ tetap melapor "10_15_7"
    let safari = v.majorVersion >= 26 ? "26.0" : v.majorVersion >= 15 ? "18.0" : "17.0"
    return "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 " +
      "(KHTML, like Gecko) Version/\(safari) Safari/605.1.15"
  }()

  static func uuid(_ s: String) -> UUID {
    let d = Array(SHA256.hash(data: Data(s.utf8)))
    var b = Array(d[0..<16])
    b[6] = (b[6] & 0x0f) | 0x50
    b[8] = (b[8] & 0x3f) | 0x80
    return UUID(uuid: (b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7],
                       b[8], b[9], b[10], b[11], b[12], b[13], b[14], b[15]))
  }

  func emit(_ id: Int, _ type: String, _ f: [String: Any]) {
    var m = f
    m["id"] = id
    m["type"] = type
    channel.invokeMethod("event", arguments: m)
  }

  var scale: CGFloat { container?.window?.backingScaleFactor ?? 2 }

  /// Kotak fisik (kiri-atas) -> frame NSView di container.
  func toView(_ r: NSRect) -> NSRect {
    guard let c = container else { return .zero }
    let s = scale
    let x = r.origin.x / s, y = r.origin.y / s, w = r.width / s, h = r.height / s
    let top = c.isFlipped ? y : c.bounds.height - y - h
    return NSRect(x: x, y: top, width: w, height: h)
  }

  func layout() {
    let f = toView(rect)
    for v in views.values {
      v.web.frame = f
      applyMask(v.web)
    }
  }

  /// Lubangi webview di kotak popup Flutter (halaman tetap hidup).
  func applyMask(_ w: WKWebView) {
    w.wantsLayer = true
    guard let layer = w.layer else { return }
    if holes.isEmpty {
      layer.mask = nil
      return
    }
    let s = scale
    let path = CGMutablePath()
    path.addRect(w.bounds)
    for h in holes {
      // koordinat lokal webview (kiri-atas), lalu ikuti orientasi layer
      let lx = h.origin.x / s - rect.origin.x / s
      let ly = h.origin.y / s - rect.origin.y / s
      let hw = h.width / s, hh = h.height / s
      let y = w.isFlipped ? ly : w.bounds.height - ly - hh
      let r = CGRect(x: lx, y: y, width: hw, height: hh)
      let rad = min(holeRadius / s, hw / 2, hh / 2)
      path.addRoundedRect(in: r, cornerWidth: rad, cornerHeight: rad)
    }
    let m = CAShapeLayer()
    m.frame = w.bounds
    m.path = path
    m.fillRule = .evenOdd
    layer.mask = m
  }

  // ================================================================ dispatch
  func handle(_ call: FlutterMethodCall, _ result: @escaping FlutterResult) {
    let a = call.arguments as? [String: Any] ?? [:]
    func num(_ k: String) -> Double { (a[k] as? NSNumber)?.doubleValue ?? 0 }
    func str(_ k: String) -> String { a[k] as? String ?? "" }
    switch call.method {
    case "version":
      let v = ProcessInfo.processInfo.operatingSystemVersion
      return result("WebKit macOS \(v.majorVersion).\(v.minorVersion)")
    case "setRect":
      rect = NSRect(x: num("x"), y: num("y"), width: num("w"), height: num("h"))
      layout()
      return result(nil)
    case "setHoles":
      let r = (a["rects"] as? [NSNumber] ?? []).map { CGFloat($0.doubleValue) }
      holes = stride(from: 0, to: r.count - 3, by: 4).map {
        NSRect(x: r[$0], y: r[$0 + 1], width: r[$0 + 2], height: r[$0 + 3])
      }
      holeRadius = CGFloat(num("radius"))
      for v in views.values { applyMask(v.web) }
      return result(nil)
    case "blur":
      if let w = container?.window { w.makeFirstResponder(container) }
      return result(nil)
    case "keepAwake":
      // userInitiated = tanpa App Nap + Mac tidak tidur saat diam (layar
      // boleh mati); latencyCritical = timer tidak dilonggarkan
      if a["on"] as? Bool ?? false {
        if awake == nil {
          awake = ProcessInfo.processInfo.beginActivity(
            options: [.userInitiated, .latencyCritical],
            reason: "TypingBot sedang mengerjakan lesson")
        }
      } else if let t = awake {
        ProcessInfo.processInfo.endActivity(t)
        awake = nil
      }
      return result(nil)
    case "appHidden":
      // uji live: sembunyikan app (spt Cmd+H) utk uji jalan di latar
      if a["on"] as? Bool ?? false {
        NSApp.hide(nil)
      } else {
        NSApp.unhide(nil)
        NSApp.activate(ignoringOtherApps: true)
      }
      return result(nil)
    case "create":
      let id = Int(num("id"))
      let v = WebHostView(id: id, folder: str("folder"),
                          scripts: a["scripts"] as? [String] ?? [], host: self)
      views[id]?.dispose()
      views[id] = v
      v.web.isHidden = !(a["visible"] as? Bool ?? false)
      container?.addSubview(v.web)
      layout()
      let u = str("url")
      if !u.isEmpty, let url = URL(string: u) { v.web.load(URLRequest(url: url)) }
      return result(nil)
    default:
      break
    }
    guard let v = views[Int(num("id"))] else {
      return result(FlutterError(code: "no_view", message: "webview tidak ada", details: nil))
    }
    let w = v.web
    switch call.method {
    case "dispose":
      v.dispose()
      views.removeValue(forKey: v.id)
      result(nil)
    case "setVisible":
      w.isHidden = !(a["on"] as? Bool ?? false)
      result(nil)
    case "navigate":
      if let url = URL(string: str("url")) { w.load(URLRequest(url: url)) }
      result(nil)
    case "reload":
      w.reload()
      result(nil)
    case "goBack":
      w.goBack()
      result(nil)
    case "history":
      let l = w.backForwardList
      result(["index": l.backList.count,
              "count": l.backList.count + 1 + l.forwardList.count])
    case "setMuted":
      // bisu seluruh halaman: WKWebView tak punya API publik, pakai
      // _setPageMuted: (dipakai Safari sendiri). 1 = audio dibisukan.
      let sel = NSSelectorFromString("_setPageMuted:")
      if w.responds(to: sel) {
        typealias Fn = @convention(c) (AnyObject, Selector, UInt) -> Void
        let f = unsafeBitCast(w.method(for: sel), to: Fn.self)
        f(w, sel, (a["on"] as? Bool ?? false) ? 1 : 0)
        result(nil)
      } else {
        result(FlutterError(code: "mute_unsupported",
                            message: "WebKit ini tidak bisa dibisukan", details: nil))
      }
    case "memInfo":
      // proses WebKit tidak terbaca dari app (sandbox): kosong = log dilewati
      result([Any]())
    case "focus":
      w.window?.makeFirstResponder(w)
      result(nil)
    case "info":
      result(["url": w.url?.absoluteString ?? "", "title": w.title ?? ""])
    case "addScript":
      v.sidSeq += 1
      let sid = String(format: "s%05d", v.sidSeq)
      v.scripts[sid] = str("js")
      v.reinstallScripts()
      result(sid)
    case "removeScript":
      v.scripts.removeValue(forKey: str("sid"))
      v.reinstallScripts()
      result(nil)
    case "eval":
      // hasil = teks JSON (spt ExecuteScript WebView2)
      let body = "const __v = (\n\(str("js"))\n);\n" +
        "return __v === undefined ? 'null' : JSON.stringify(__v);"
      w.callAsyncJavaScript(body, arguments: [:], in: nil, in: .page) { r in
        switch r {
        case .success(let x): result((x as? String) ?? "null")
        case .failure(let e): result(FlutterError(code: "eval_failed",
                                                   message: Self.jsError(e), details: nil))
        }
      }
    case "evalFrame":
      let fid = str("fid")
      var frame: WKFrameInfo? = nil
      if !fid.isEmpty {
        guard let f = v.frames[fid] else {
          return result(FlutterError(code: "js", message: "frame \(fid) sudah hilang",
                                     details: nil))
        }
        frame = f
      }
      w.callAsyncJavaScript(str("body"), arguments: [:], in: frame, in: .page) { r in
        switch r {
        case .success(let x): result(x as? String)
        case .failure(let e): result(FlutterError(code: "js", message: Self.jsError(e),
                                                   details: nil))
        }
      }
    case "key":
      ensureFocus(w)
      v.waitKeyAck(result)
      Keys.send(to: w, down: str("type") == "down", key: str("key"), code: str("code"),
                text: str("text"), mods: Int(num("mods")), repeat: a["repeat"] as? Bool ?? false)
    case "insertText":
      ensureFocus(w)
      // keyDown + keyUp = dua ack; yang kedua yang menutup panggilan
      v.waitKeyAck({ _ in })
      v.waitKeyAck(result)
      Keys.insert(to: w, text: str("text"))
    case "mouse":
      mouse(w, str("type"), num("x"), num("y"), Int(num("count")))
      result(nil)
    case "cookies":
      cookies(w, url: str("url"), result)
    case "setCookie":
      setCookie(w, a, result)
    case "clearCookies":
      let store = w.configuration.websiteDataStore.httpCookieStore
      store.getAllCookies { all in
        let g = DispatchGroup()
        for c in all {
          g.enter()
          store.delete(c) { g.leave() }
        }
        g.notify(queue: .main) { result(nil) }
      }
    case "clearData":
      clearData(w, origin: str("origin"), result)
    case "snapshot":
      w.takeSnapshot(with: nil) { img, _ in
        guard let img = img, let tiff = img.tiffRepresentation,
              let rep = NSBitmapImageRep(data: tiff),
              let png = rep.representation(using: .png, properties: [:]) else {
          return result("")
        }
        result(png.base64EncodedString())
      }
    case "cdp", "cdpSubscribe", "cdpUnsubscribe":
      // CDP ditiru di Dart (wk_cdp.dart); host tidak punya CDP
      result(FlutterError(code: "cdp_failed", message: "tidak ada CDP di macOS", details: nil))
    default:
      result(FlutterMethodNotImplemented)
    }
  }

  static func jsError(_ e: Error) -> String {
    let ns = e as NSError
    if let m = ns.userInfo["WKJavaScriptExceptionMessage"] as? String { return m }
    return ns.localizedDescription
  }

  /// Tombol hanya sampai ke halaman kalau webview yang dapat fokus.
  /// Fokus diambil HANYA kalau memang bukan di webview: makeFirstResponder
  /// berulang = blur/focus halaman tiap tombol, input lesson kehilangan
  /// fokus sesudah huruf pertama (CI 45014788363: cuma 'H' masuk).
  func ensureFocus(_ w: WKWebView) {
    guard let win = w.window else { return }
    if let r = win.firstResponder as? NSView, r === w || r.isDescendant(of: w) { return }
    win.makeFirstResponder(w)
  }

  // ---------------------------------------------------------------- mouse
  func mouse(_ w: WKWebView, _ type: String, _ x: Double, _ y: Double, _ count: Int) {
    guard let win = w.window else { return }
    // CSS px = titik view (zoom 1)
    let local = NSPoint(x: x, y: w.isFlipped ? y : w.bounds.height - y)
    let p = w.convert(local, to: nil)
    lastMouse = p
    let kind: NSEvent.EventType = type == "down" ? .leftMouseDown
      : type == "up" ? .leftMouseUp : .mouseMoved
    guard let e = NSEvent.mouseEvent(
      with: kind, location: p, modifierFlags: [], timestamp: ProcessInfo.processInfo.systemUptime,
      windowNumber: win.windowNumber, context: nil, eventNumber: 0,
      clickCount: max(count, 1), pressure: kind == .leftMouseDown ? 1 : 0) else { return }
    switch kind {
    case .leftMouseDown: w.mouseDown(with: e)
    case .leftMouseUp: w.mouseUp(with: e)
    default: w.mouseMoved(with: e)
    }
  }

  // ---------------------------------------------------------------- kuki
  static func cookieJson(_ c: HTTPCookie) -> [String: Any] {
    var m: [String: Any] = [
      "name": c.name, "value": c.value, "domain": c.domain, "path": c.path,
      "secure": c.isSecure, "httpOnly": c.isHTTPOnly, "session": c.isSessionOnly,
      "expires": c.expiresDate?.timeIntervalSince1970 ?? -1,
    ]
    if let s = c.sameSitePolicy {
      m["sameSite"] = s == .sameSiteStrict ? "Strict" : "Lax"
    } else {
      m["sameSite"] = "None"
    }
    return m
  }

  func cookies(_ w: WKWebView, url: String, _ result: @escaping FlutterResult) {
    let host = URL(string: url)?.host?.lowercased() ?? ""
    w.configuration.websiteDataStore.httpCookieStore.getAllCookies { all in
      let out = all.filter { c in
        if host.isEmpty { return true }
        let d = c.domain.lowercased().trimmingCharacters(in: CharacterSet(charactersIn: "."))
        return host == d || host.hasSuffix("." + d)
      }.map(Self.cookieJson)
      result(out)
    }
  }

  func setCookie(_ w: WKWebView, _ a: [String: Any], _ result: @escaping FlutterResult) {
    var p: [HTTPCookiePropertyKey: Any] = [
      .name: a["name"] as? String ?? "",
      .value: a["value"] as? String ?? "",
      .domain: a["domain"] as? String ?? "",
      .path: a["path"] as? String ?? "/",
    ]
    if a["secure"] as? Bool == true { p[.secure] = "TRUE" }
    if a["httpOnly"] as? Bool == true { p[HTTPCookiePropertyKey("HttpOnly")] = "TRUE" }
    if let e = (a["expires"] as? NSNumber)?.doubleValue, e > 0 {
      p[.expires] = Date(timeIntervalSince1970: e)
    }
    switch a["sameSite"] as? String {
    case "Strict": p[.sameSitePolicy] = HTTPCookieStringPolicy.sameSiteStrict
    case "Lax": p[.sameSitePolicy] = HTTPCookieStringPolicy.sameSiteLax
    default: break
    }
    guard let c = HTTPCookie(properties: p) else {
      return result(FlutterError(code: "bad_cookie", message: "kuki tidak sah", details: nil))
    }
    w.configuration.websiteDataStore.httpCookieStore.setCookie(c) { result(true) }
  }

  func clearData(_ w: WKWebView, origin: String, _ result: @escaping FlutterResult) {
    let host = URL(string: origin)?.host?.lowercased() ?? origin.lowercased()
    // nama rekaman = domain terdaftar (mis. "edclub.com")
    let parts = host.split(separator: ".")
    let base = parts.count >= 2 ? parts.suffix(2).joined(separator: ".") : host
    let store = w.configuration.websiteDataStore
    let types: Set<String> = [
      WKWebsiteDataTypeLocalStorage, WKWebsiteDataTypeSessionStorage,
      WKWebsiteDataTypeIndexedDBDatabases, WKWebsiteDataTypeFetchCache,
      WKWebsiteDataTypeDiskCache, WKWebsiteDataTypeMemoryCache,
    ]
    store.fetchDataRecords(ofTypes: types) { recs in
      let mine = recs.filter { $0.displayName.lowercased().contains(base) }
      store.removeData(ofTypes: types, for: mine) { result(nil) }
    }
  }
}
