import Cocoa
import FlutterMacOS

@main
class AppDelegate: FlutterAppDelegate {
  override func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
    return true
  }

  override func applicationSupportsSecureRestorableState(_ app: NSApplication) -> Bool {
    return true
  }
}

// Pindah ke folder Applications saat app dibuka dari tempat sementara.
//
// Dari .dmg (read-only) atau dari Downloads (app belum ditandatangani =
// macOS menjalankannya dari salinan tersembunyi read-only, 'App
// Translocation'), pembaruan otomatis tidak bisa menukar app. Jadi sekali
// di awal: tanya, salin ke /Applications (atau ~/Applications kalau bukan
// admin), buang tanda karantina salinannya, hapus yang di Downloads / lepas
// .dmg-nya, lalu buka lagi dari tempat baru. Pola sama dgn pustaka LetsMove.
//
// TB_NO_MOVE=1: lewati (uji). TB_MOVE_AUTO=1: tanpa dialog (uji CI).

enum MoveToApps {
  /// Dipanggil paling awal (applicationWillFinishLaunching). Kalau app
  /// dipindah, proses ini keluar dan app dibuka ulang dari tempat baru.
  static func checkAtLaunch() {
    let env = ProcessInfo.processInfo.environment
    if env["TB_NO_MOVE"] == "1" || env["TB_SELFTEST"] != nil { return }
    let here = Bundle.main.bundleURL.resolvingSymlinksInPath()
    let asal = originalURL(of: here)
    guard needsMove(here: here.path, original: asal.path) else { return }
    if env["TB_MOVE_AUTO"] != "1" && !ask() { return }
    do {
      try move(from: here, original: asal)
    } catch {
      let a = NSAlert()
      a.messageText = "TypingBot gagal dipindah"
      a.informativeText = "Seret TypingBot ke folder Applications sendiri ya, lalu buka dari sana.\n\n\(error.localizedDescription)"
      a.runModal()
    }
  }

  static func needsMove(here: String, original: String) -> Bool {
    if here.hasPrefix("/Applications/") { return false }
    let home = FileManager.default.homeDirectoryForCurrentUser.path
    if here.hasPrefix(home + "/Applications/") { return false }
    return here.hasPrefix("/Volumes/") || here.contains("/AppTranslocation/") ||
      original.hasPrefix(home + "/Downloads/") || original.hasPrefix(home + "/Desktop/")
  }

  static func ask() -> Bool {
    let a = NSAlert()
    a.messageText = "Pindahkan TypingBot ke folder Applications?"
    a.informativeText = "Dari sini pembaruan otomatis tidak bisa dipasang. TypingBot akan dipindah ke Applications lalu dibuka lagi."
    a.addButton(withTitle: "Pindahkan")
    a.addButton(withTitle: "Nanti")
    NSApp.activate(ignoringOtherApps: true)
    return a.runModal() == .alertFirstButtonReturn
  }

  static func move(from here: URL, original: URL) throws {
    let fm = FileManager.default
    let sys = URL(fileURLWithPath: "/Applications")
    let dir = fm.isWritableFile(atPath: sys.path)
      ? sys
      : fm.homeDirectoryForCurrentUser.appendingPathComponent("Applications")
    try fm.createDirectory(at: dir, withIntermediateDirectories: true)
    let dest = dir.appendingPathComponent("TypingBot.app")
    if fm.fileExists(atPath: dest.path) {
      // versi lama di Applications: ke Tempat Sampah (bisa dipulihkan)
      do { try fm.trashItem(at: dest, resultingItemURL: nil) } catch { try fm.removeItem(at: dest) }
    }
    try fm.copyItem(at: here, to: dest)
    // tanda karantina ikut tersalin = macOS menyembunyikan lagi salinannya
    run("/usr/bin/xattr", ["-dr", "com.apple.quarantine", dest.path])

    var lepas = ""
    if original.path.hasPrefix("/Volumes/") {
      // /Volumes/<nama>/TypingBot.app -> lepas /Volumes/<nama> sesudah keluar
      let parts = original.path.split(separator: "/")
      if parts.count >= 2 { lepas = "/Volumes/\(parts[1])" }
    } else {
      try? fm.trashItem(at: original, resultingItemURL: nil)
    }
    // buka lagi dari tempat baru begitu proses ini selesai
    let pid = ProcessInfo.processInfo.processIdentifier
    var sh = "while kill -0 \(pid) 2>/dev/null; do sleep 0.2; done; /usr/bin/open -n \(q(dest.path))"
    if !lepas.isEmpty { sh += "; /usr/bin/hdiutil detach \(q(lepas)) -quiet || true" }
    let p = Process()
    p.executableURL = URL(fileURLWithPath: "/bin/sh")
    p.arguments = ["-c", sh]
    try p.run()
    exit(0)
  }

  /// Jalur asli app yang dijalankan lewat App Translocation (fungsi
  /// Security.framework yang juga dipakai LetsMove; tak ada = jalur ini).
  static func originalURL(of url: URL) -> URL {
    guard url.path.contains("/AppTranslocation/"),
          let h = dlopen("/System/Library/Frameworks/Security.framework/Security", RTLD_LAZY),
          let f = dlsym(h, "SecTranslocateCreateOriginalPathForURL") else { return url }
    typealias Fn = @convention(c) (CFURL, UnsafeMutablePointer<Unmanaged<CFError>?>?) -> Unmanaged<CFURL>?
    let fn = unsafeBitCast(f, to: Fn.self)
    guard let r = fn(url as CFURL, nil) else { return url }
    return r.takeRetainedValue() as URL
  }

  static func q(_ s: String) -> String { "'" + s.replacingOccurrences(of: "'", with: "'\\''") + "'" }

  @discardableResult
  static func run(_ exe: String, _ args: [String]) -> Int32 {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: exe)
    p.arguments = args
    do { try p.run() } catch { return -1 }
    p.waitUntilExit()
    return p.terminationStatus
  }
}
