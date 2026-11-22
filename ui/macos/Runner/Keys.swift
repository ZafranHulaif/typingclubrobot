// Tombol asli utk WKWebView: NSEvent keyDown/keyUp/flagsChanged dikirim
// langsung ke view, jadi halaman menerimanya sebagai ketikan sungguhan
// (isTrusted = true), spt Input.dispatchKeyEvent CDP di Windows.
import Cocoa
import Carbon.HIToolbox

enum Keys {
  // KeyboardEvent.code (layout US) -> kode tombol virtual Mac
  static let codes: [String: Int] = {
    var m: [String: Int] = [
      "KeyA": kVK_ANSI_A, "KeyB": kVK_ANSI_B, "KeyC": kVK_ANSI_C, "KeyD": kVK_ANSI_D,
      "KeyE": kVK_ANSI_E, "KeyF": kVK_ANSI_F, "KeyG": kVK_ANSI_G, "KeyH": kVK_ANSI_H,
      "KeyI": kVK_ANSI_I, "KeyJ": kVK_ANSI_J, "KeyK": kVK_ANSI_K, "KeyL": kVK_ANSI_L,
      "KeyM": kVK_ANSI_M, "KeyN": kVK_ANSI_N, "KeyO": kVK_ANSI_O, "KeyP": kVK_ANSI_P,
      "KeyQ": kVK_ANSI_Q, "KeyR": kVK_ANSI_R, "KeyS": kVK_ANSI_S, "KeyT": kVK_ANSI_T,
      "KeyU": kVK_ANSI_U, "KeyV": kVK_ANSI_V, "KeyW": kVK_ANSI_W, "KeyX": kVK_ANSI_X,
      "KeyY": kVK_ANSI_Y, "KeyZ": kVK_ANSI_Z,
      "Digit0": kVK_ANSI_0, "Digit1": kVK_ANSI_1, "Digit2": kVK_ANSI_2, "Digit3": kVK_ANSI_3,
      "Digit4": kVK_ANSI_4, "Digit5": kVK_ANSI_5, "Digit6": kVK_ANSI_6, "Digit7": kVK_ANSI_7,
      "Digit8": kVK_ANSI_8, "Digit9": kVK_ANSI_9,
      "Minus": kVK_ANSI_Minus, "Equal": kVK_ANSI_Equal, "BracketLeft": kVK_ANSI_LeftBracket,
      "BracketRight": kVK_ANSI_RightBracket, "Backslash": kVK_ANSI_Backslash,
      "Semicolon": kVK_ANSI_Semicolon, "Quote": kVK_ANSI_Quote, "Comma": kVK_ANSI_Comma,
      "Period": kVK_ANSI_Period, "Slash": kVK_ANSI_Slash, "Backquote": kVK_ANSI_Grave,
      "Space": kVK_Space, "Enter": kVK_Return, "NumpadEnter": kVK_ANSI_KeypadEnter,
      "Tab": kVK_Tab, "Backspace": kVK_Delete, "Delete": kVK_ForwardDelete,
      "Escape": kVK_Escape, "ArrowLeft": kVK_LeftArrow, "ArrowRight": kVK_RightArrow,
      "ArrowUp": kVK_UpArrow, "ArrowDown": kVK_DownArrow, "Home": kVK_Home, "End": kVK_End,
      "PageUp": kVK_PageUp, "PageDown": kVK_PageDown,
      "ShiftLeft": kVK_Shift, "ShiftRight": kVK_RightShift,
      "ControlLeft": kVK_Control, "ControlRight": kVK_RightControl,
      "AltLeft": kVK_Option, "AltRight": kVK_RightOption,
      "MetaLeft": kVK_Command, "MetaRight": kVK_RightCommand, "CapsLock": kVK_CapsLock,
    ]
    for i in 1...12 {
      let f = [kVK_F1, kVK_F2, kVK_F3, kVK_F4, kVK_F5, kVK_F6, kVK_F7, kVK_F8, kVK_F9,
               kVK_F10, kVK_F11, kVK_F12][i - 1]
      m["F\(i)"] = f
    }
    return m
  }()

  // karakter NSEvent utk tombol tanpa teks
  static func specialChars(_ key: String) -> String? {
    func u(_ c: Int) -> String { String(Character(UnicodeScalar(c)!)) }
    switch key {
    case "Enter": return "\r"
    case "Tab": return "\t"
    case "Backspace": return u(0x7f)
    case "Escape": return u(0x1b)
    case "Delete": return u(NSDeleteFunctionKey)
    case "ArrowLeft": return u(NSLeftArrowFunctionKey)
    case "ArrowRight": return u(NSRightArrowFunctionKey)
    case "ArrowUp": return u(NSUpArrowFunctionKey)
    case "ArrowDown": return u(NSDownArrowFunctionKey)
    case "Home": return u(NSHomeFunctionKey)
    case "End": return u(NSEndFunctionKey)
    case "PageUp": return u(NSPageUpFunctionKey)
    case "PageDown": return u(NSPageDownFunctionKey)
    default: return nil
    }
  }

  static let modifierKeys: Set<String> = ["Shift", "Control", "Alt", "Meta", "CapsLock"]

  /// Bit modifier CDP (1 Alt, 2 Ctrl, 4 Meta, 8 Shift) -> flag Cocoa.
  static func flags(_ mods: Int) -> NSEvent.ModifierFlags {
    var f: NSEvent.ModifierFlags = []
    if mods & 1 != 0 { f.insert(.option) }
    if mods & 2 != 0 { f.insert(.control) }
    if mods & 4 != 0 { f.insert(.command) }
    if mods & 8 != 0 { f.insert(.shift) }
    return f
  }

  static func send(to w: NSView, down: Bool, key: String, code: String, text: String,
                   mods: Int, repeat rep: Bool) {
    guard let win = w.window else { return }
    let kc = UInt16(codes[code] ?? 0)
    let fl = flags(mods)
    let ts = ProcessInfo.processInfo.systemUptime
    if modifierKeys.contains(key) {
      // modifier = flagsChanged (bit modifier sudah termasuk/terlepas)
      guard let cg = CGEvent(keyboardEventSource: nil, virtualKey: CGKeyCode(kc), keyDown: down)
      else { return }
      cg.type = .flagsChanged
      var cf: CGEventFlags = []
      if fl.contains(.shift) { cf.insert(.maskShift) }
      if fl.contains(.control) { cf.insert(.maskControl) }
      if fl.contains(.option) { cf.insert(.maskAlternate) }
      if fl.contains(.command) { cf.insert(.maskCommand) }
      cg.flags = cf
      if let e = NSEvent(cgEvent: cg) { w.flagsChanged(with: e) }
      return
    }
    var chars = text
    if chars.isEmpty { chars = specialChars(key) ?? (key.count == 1 ? key : "") }
    // teks tanpa modifier: huruf kecil utk Shift+huruf (spt keyboard asli)
    let plain = fl.contains(.shift) && chars.count == 1 ? chars.lowercased() : chars
    guard let e = NSEvent.keyEvent(
      with: down ? .keyDown : .keyUp, location: .zero, modifierFlags: fl, timestamp: ts,
      windowNumber: win.windowNumber, context: nil, characters: chars,
      charactersIgnoringModifiers: plain, isARepeat: rep, keyCode: kc) else { return }
    if down { w.keyDown(with: e) } else { w.keyUp(with: e) }
  }

  /// Teks di luar layout US: satu keyDown+keyUp dgn karakter itu.
  static func insert(to w: NSView, text: String) {
    guard let win = w.window, !text.isEmpty else { return }
    let ts = ProcessInfo.processInfo.systemUptime
    for t in [NSEvent.EventType.keyDown, .keyUp] {
      guard let e = NSEvent.keyEvent(
        with: t, location: .zero, modifierFlags: [], timestamp: ts,
        windowNumber: win.windowNumber, context: nil, characters: text,
        charactersIgnoringModifiers: text, isARepeat: false, keyCode: 0) else { continue }
      if t == .keyDown { w.keyDown(with: e) } else { w.keyUp(with: e) }
    }
  }
}
