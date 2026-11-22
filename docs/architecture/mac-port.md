# macOS port (branch `mac`)

Status: early proof of concept. Not released. The owner has no Mac; testing runs on GitHub's
macOS runners (`.github/workflows/mac.yml`) and later on a friend's Mac.

## Approach
- The Flutter UI, the Dart bot engine and the license/account code are shared with Windows.
- Windows hosts the edclub page in WebView2 and drives it over CDP. WKWebView has no CDP, so:
  - `ui/macos/Runner/WebHost.swift` implements the same `typingbot/web_host` method channel as
    `ui/windows/runner/web_host.cpp`, plus Mac-only primitives: `evalFrame`, `key`,
    `insertText`, `mouse`, `cookies`, `setCookie`, `clearCookies`, `clearData`, `snapshot`,
    `history`.
  - `ui/lib/src/web/wk_cdp.dart` emulates the subset of CDP the engine uses (frame tree,
    execution contexts, Runtime.evaluate, Input.*, Network cookies, DOM.getBoxModel for iframe
    offsets) on top of those primitives. `WebView.cdp()` routes there when
    `WebHost.emulateCdp` (macOS). `page.dart` is unchanged.
  - Frames: a user script in every frame (including cross-origin iframes) reports
    hello/bye/hash with a random per-document id; Swift keeps the `WKFrameInfo` for
    `callAsyncJavaScript(in: frame, in: .page)`. All frames live in session ''.
  - Keys and clicks are real `NSEvent`s sent to the WKWebView, so the page sees
    `isTrusted = true` (verified on CI, including inside a cross-origin iframe).
  - Holes for Flutter popups: a `CAShapeLayer` mask on the webview (even-odd).
  - Per-account cookie jars: `WKWebsiteDataStore(forIdentifier:)` (macOS 14+), UUID from the
    profile folder path; older macOS falls back to the default store (one jar).
- Data folder: `~/Library/Application Support/TypingBot`. App sandbox is off (direct download,
  not App Store). Machine code uses IOPlatformUUID.
- Auto-update is disabled on Mac (the server only carries the Windows exe).

## CI checks (mac.yml)
1. analyze + all tests on macOS.
2. `flutter build macos --release`.
3. Self-test `TB_MACTEST` (`lib/src/native/mac_selftest.dart`) against `ui/tool/mactest`
   (main page on 127.0.0.1:8701 with an iframe from localhost:8702): frames visible, eval in
   the iframe, typing lands in the iframe with isTrusted keys, trusted clicks in main page and
   iframe (via frameOffset), cookies, reload. All pass since commit e0f87a1 (Shift check
   removed: Playwright-style `type('H')` sends no Shift on Windows either).
4. The real app with `TB_SELFTEST` (same steps as Windows CI), screenshots in the
   `mactest-out` artifact. No edclub login on CI (credentials are not put on GitHub).
5. Artifact `typingbot-mac` = zipped TypingBot.app (unsigned).

Known pitfall fixed: calling makeFirstResponder before every key made the page blur/refocus and
only the first letter landed (run 45014788363). `ensureFocus` now only grabs focus when the
first responder is not the webview or one of its subviews. Green again in run 45015382681.

## Not done / unknown
- Never run against real edclub while logged in (needs a friend's Mac or a CI secret the owner
  approves).
- Google login: Google may refuse sign-in inside an embedded WKWebView; email/password login
  should work. Windows has an OAuth relay path; not ported.
- `Network.responseReceived` (401/403 login sentinel) is not emulated: login loss is only
  detected by the page checks.
- Nested iframes: parent is assumed to be the main frame; offset matching is by iframe origin.
- Unsigned app: first open needs right-click > Open (or `xattr -dr com.apple.quarantine`).
- No DMG / install flow, no auto-update, no launcher equivalent.
