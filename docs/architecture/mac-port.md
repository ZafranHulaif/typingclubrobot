# macOS port (branch `mac`)

Status (2026-11-22): works end to end on a real Mac (GitHub runner, macOS 26) with the real edclub
test account: login from a saved session, license check, plan/free mode, star targets (2-5,
platinum), standard lessons, tutorials, hold-key levels, video levels, premium skip, Balloon and
Monster games on target, Google sign-in reaches the password step (not blocked). Not released.
The owner has no Mac; the next real-world check is a friend's Mac.

## Status 2026-11-25 (4.0.8, merged with v4)
- All v4 fixes 4.0.1-4.0.8 merged. Mute via private `_setPageMuted:`; `memInfo` returns [] (log skipped).
- Background: `keepAwake` = beginActivity(userInitiated+latencyCritical) while the bot runs (no App Nap);
  `_setHiddenPageDOMTimerThrottlingEnabled:`/`_setPageVisibilityBasedProcessSuppressionEnabled:` off,
  `_setWindowOcclusionDetectionEnabled:` off (all checked with respondsTo). `hiddenRunJs` keeps Phaser
  games running when the app is hidden.
- Live runs with the app hidden (Cmd+H): 16 min lessons + videos at normal pace; Monster game played to
  target. Ads blocked with WKContentRuleList.
- `ui/tool/mactest/live.env` on the mac-live branch sets DETIK/LEVEL/AKHIR/BINTANG/SEMBUNYI.
- Hidden/minimised: webviews are parked in an invisible window (alpha 0, canHide=false) so WebKit never
  freezes CSS animations (post-game Pro modal / results screen used to hang). Live run fully hidden:
  2 Monster games, modal + Move on in seconds, no stalls.
- .dmg (TypingBot + Applications link) built next to the zip; MoveToApps (AppDelegate.swift) offers to
  move from /Volumes, AppTranslocation, Downloads or Desktop to /Applications (~/Applications if not
  admin), strips quarantine, trashes the original / detaches the DMG, relaunches. CI "Uji pindah dari .dmg"
  checks it. The updater refuses with a clear message from /Volumes or AppTranslocation.
- Login sentinel: netWatchJs (edclub/typingclub frames only) reports 401/403 fetch/XHR via `tbnet`;
  wk_cdp turns it into Network.responseReceived.
- macOS 12-13: one nonPersistent store per account; the edclub session comes back from tb_sesi.json
  (live-tested with TB_LEGACY_STORE=1). Google/Cloudflare cookies are lost when the app quits there.

## Approach
- The Flutter UI, the Dart bot engine and the license/account code are shared with Windows.
- Windows hosts the edclub page in WebView2 and drives it over CDP. WKWebView has no CDP, so:
  - `ui/macos/Runner/WebHost.swift` implements the same `typingbot/web_host` method channel as
    `ui/windows/runner/web_host.cpp`, plus Mac-only primitives: `evalFrame`, `key`,
    `insertText`, `mouse`, `cookies`, `setCookie`, `clearCookies`, `clearData`, `snapshot`,
    `history`. `Keys.swift` maps DOM codes to Mac key codes.
  - `ui/lib/src/web/wk_cdp.dart` emulates the CDP subset the engine uses (frame tree, execution
    contexts, Runtime.evaluate, Input.*, Network cookies, DOM.getBoxModel for iframe offsets).
    `WebView.cdp()` routes there when `WebHost.emulateCdp` (macOS). `page.dart` is unchanged.
  - Frames: a user script in every frame (including cross-origin iframes) reports
    hello/bye/hash with a random per-document id; Swift keeps the `WKFrameInfo` for
    `callAsyncJavaScript(in: frame, in: .page)`. All frames live in session ''.
  - Keys and clicks are real `NSEvent`s sent to the WKWebView, so the page sees
    `isTrusted = true`.
  - **Key ack**: WebKit queues key events per web process; an evaluate can overtake queued
    keys, so the engine read stale text and retyped (duplicates like "youngn", run 3). Every
    frame acks each keydown/keyup via `webkit.messageHandlers.tbkey`; the `key` call returns
    only after the ack (0.4 s timeout).
  - **Focus**: only grab first responder when it is not the webview or a subview (grabbing per
    key blurred the page; only the first letter landed).
  - Holes for Flutter popups: `CAShapeLayer` mask on the webview (even-odd).
  - Per-account cookie jars: `WKWebsiteDataStore(forIdentifier:)` (macOS 14+), UUID from the
    profile folder path (CI checks isolation); older macOS falls back to the default store.
  - Safari user agent (`WebHost.safariUA`), otherwise Google refuses embedded sign-in.
  - `ApplePressAndHoldEnabled = false` for the app (hold-key levels).
- Shared engine changes made for Mac (also active on Windows, Windows CI runs on this branch):
  - hold-key levels focus the lesson input before pressing the held key (on WebKit the first
    keydown landed on BODY and counted as a wrong 'j');
  - decorative `<video>` (loop, tiny/0x0, hidden) is no longer treated as a video level (on
    WebKit the balloon page has one; the skipper interrupted the game, 2 stars instead of 4).
- Data folder: `~/Library/Application Support/TypingBot`. App sandbox off (direct download).
  Machine code uses IOPlatformUUID.
- Auto-update: GitHub releases. `Api.latestMacRelease` picks the highest non-prerelease release
  with a `TypingBot-mac.zip` asset (sha256 from the asset digest). Install = bash script
  (`macInstallScript`): wait for the app pid, unzip, move old bundle to `.lama`, swap, roll back
  on failure, strip quarantine, reopen. CI tests a real swap.

## CI (`.github/workflows/mac.yml`)
- Push to `mac`: gen_js check, analyze, tests, `flutter build macos`, self-test against
  `ui/tool/mactest` (cross-origin iframe: eval, trusted typing incl. fast typing read back
  immediately, trusted clicks, cookies, per-account jar isolation, reload), real app
  screenshots, update-swap test, artifact `typingbot-mac` (zipped TypingBot.app, unsigned).
- Push to `mac-live`: live run with the edclub test account. The session (rt cookie) never
  appears readable in the repo or logs: the job makes a one-time RSA key and uploads the
  public half; the owner side (`~/.config/typingbot/mac_live.sh kirim <run>` on the VPS)
  encrypts the session (+ test email for the Google check) to it and pushes it to branch
  `mac-live-sesi`; at the end the rotated session is encrypted to
  `ui/tool/mactest/kunci_penerima.pem` (private key only on the VPS) and fetched with
  `mac_live.sh terima <run>`. Always run `terima` after a live run: the cookie rotates.
  Env knobs: `TB_SELFTEST_LEVEL`, `TB_SELFTEST_STARS`, `TB_SELFTEST_RUN`, `TB_KEYLOG=1`
  (logs page key events at problem points).
- The GitHub token here cannot set secrets or dispatch workflows, hence the branch triggers.

## Releasing a Mac build (owner decision)
Attach the `typingbot-mac` artifact's `TypingBot-mac.zip` to the GitHub release (same tag as
Windows). The Mac app finds it by asset name. Unsigned: first open needs right-click > Open
(or `xattr -dr com.apple.quarantine TypingBot.app`). Updates installed by the app itself are
not quarantined.

## Not done / unknown
- Never run on a physical Mac by a real user; Intel Macs untested (runner is Apple Silicon;
  Flutter builds universal by default).
- Google sign-in verified only up to the password page (no password on CI).
- `Network.responseReceived` (401/403 login sentinel) not emulated.
- Nested iframes: parent assumed to be the main frame; iframe offset matched by origin.
- Some top-frame videos still get the "skip to end" treatment during games (harmless now).
- macOS < 14 shares one cookie jar for all accounts.
