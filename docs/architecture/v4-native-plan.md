# v4 native plan (replaces the Python sidecar route)

Decided 2026-11-21 by the owner: "whatever makes it feel more responsive; native it is."
Supersedes §2-§5 of `M0-decision.md` (the sidecar, IPC and cross-process embedding).
The UI work (Flutter, brand, layout, plan tiles) is unchanged and reused as-is.

## Why
The old app felt slow because one Tk thread did UI + polling + webview + timers, not because
of Python's speed (typing is bound by the browser, not the language). The sidecar route kept
all of Python's baggage: two processes, pythonnet/.NET with the GIL "no callbacks" rule, a hidden
Tk pump, cross-process window reparenting (the riskiest part), and an 80 MB self-extracting exe.
One native program removes all of that.

## Shape
```
TypingBot (one Flutter Windows app)
├── Dart UI            ui/lib/src/ui/**       (done: approved design)
├── Dart engine        ui/lib/src/engine/**   (port of engine/*.py, module by module)
│     └── JS payloads  reused VERBATIM from engine/jstemplates.py + jsutil.py (~1.3k lines)
├── Dart net           ui/lib/src/net/**      (port of net/: license Ed25519, api, updater, report)
└── C++ runner plugin  ui/windows/runner/**   WebView2 host:
      - one CoreWebView2Environment per account data folder (same jars as 3.5.x)
      - windowed child HWND, in-process (first). Composition/texture hosting later
        to allow Flutter UI over the page.
      - CDP via CallDevToolsProtocolMethod + DevToolsProtocolEventReceiver,
        exposed to Dart over a MethodChannel/EventChannel (no debug port, no websocket)
      - AddScriptToExecuteOnDocumentCreated (window.open stub born with the document)
      - NewWindowRequested handled natively (OAuth popups stay in-app)
      - Windows OCR (Windows.Media.Ocr) for OCR lessons
```
Playwright surface the engine actually uses (grep, 2026-11-21): evaluate, keyboard
type/press/down/up, mouse.click, goto, reload, go_back, wait_for_selector, add_init_script,
url, frames/main_frame, locator (8 uses). All map to plain CDP calls.

## Porting order (each step = verified before the next)
| Step | What | Verified by |
|---|---|---|
| N1 | C++ WebView2 host: env per account folder, resize from Dart rect, show/hide, navigate, CDP bridge, init scripts, new-window handling | CI build + owner: page shows, Google login works in-app, account switch |
| N2 | Dart CDP "page" API over the bridge (subset above) | Unit tests with a fake bridge here; owner smoke on Windows |
| N3 | Engine port: state, typing_core (timing), levels, supervisor loop, session/login patrol, recovery, lessons (standard, games, video, intro/tutorial/holdkey/screenkey, ocr) | Port of `_test_harness.py` accuracy scenarios to Dart (must stay 100%) |
| N4 | Net port: license (Ed25519 verify + legacy HMAC key), api (browser UA), updater, bug report | Port of `_test_net.py` cases |
| N5 | Data compatibility: same `%LOCALAPPDATA%/TypingBot` files (license.dat, settings, profil-akun jars, level_map.json, posisi_level.json) so 3.5.x users keep license and logins | Owner upgrades a real 3.5.x install |
| N6 | Packaging + update path from 3.5.x (see open question) | CI artifact + owner install |
| N7 | Star targets (research thresholds, speed/typo control per plan segment) | Live edclub runs |

## Open questions
- **Update path from 3.5.x.** The old updater replaces one `TypingBot.exe`. v4 is a folder
  (exe + DLLs + data). Likely answer: v4's `TypingBot.exe` download is a self-extracting
  installer (e.g. Inno Setup) that installs to `%LOCALAPPDATA%/TypingBot/app` and fixes
  shortcuts. Decide in N6.
- Composition hosting (Flutter over the page) vs windowed child: start windowed (simple,
  robust), switch once the engine works.

## Python's role now
`engine/`, `net/`, `gui/` stay in the repo as the **specification** and for 3.5.x hotfixes.
`sidecar/` is parked (its mock stays useful for UI work on Linux). Nothing in Python is deleted
until v4 reaches feature parity.
