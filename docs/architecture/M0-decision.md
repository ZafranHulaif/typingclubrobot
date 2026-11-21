# M0: Flutter rebuild, architecture decision

Status: APPROVED by owner 2026-11-21 (v2, after the Fable advisor review). Pause button: yes. Written 2026-11-21 against `qol-edge` @ a86d3f4 (3.5.5-dev21).

## TL;DR

1. **Flutter draws everything you see except the edclub page.** The Python sidecar is the
   existing engine, licensing, updater, account jars and the WebView2 host. Flutter draws
   no web content. Python draws no UI.
2. **The WebView2 stays in Python.** The sidecar owns ONE container window. It is
   reparented into the Flutter window once, across processes. Webview, spare and popups
   all live inside that container, exactly as they live inside the Tk frame today. The
   Flutter runner (C++) keeps the container sized and positioned, in sync with Flutter frames.
3. **IPC = newline-delimited JSON over local TCP (stdlib only).** Flutter sends requests
   and the sidecar replies. The sidecar also pushes events (state, logs, covers). This does
   NOT break the GIL rule (see §4).
4. **Python stays the entry point (`TypingBot.exe`).** It unpacks and launches the Flutter
   UI. Licensing, the updater and the "old users auto-update" path keep working unchanged.
   The 95 MB exe cap can also be removed (§5).
5. **First refactor `Wv2Host` in place (shipped in 3.5.x), then spike, then build.**
   Cross-process embedding has real risks (focus, DPI, hangs) that only Windows can show
   us, so a hard go/no-go spike comes before any Flutter feature work.

## 1. What I found in `gui/` (the audit)

`gui/` is 9.4k lines. The engine reaches it through four channels, none of them an API:

| Channel | How it works today | Problem |
|---|---|---|
| Shared flags | GUI reads and writes ~37 globals in `engine/state.py` (`STOP`, `PAUSED`, `AWAIT_RANGE`, `LEVEL_START`...) | No locks, no change notification. The GUI polls them every 150 ms (`activity.py:46`). |
| stdout as event bus | Engine `print()`s. `launch.py:33` captures stdout. `translator.py` regexes turn lines into status text | Changing a print breaks the UI. Not structured (no wpm or stars as data). |
| `_ui_queue` of callables | Worker threads push Tk closures | Fine inside one process. Can't cross a process boundary. |
| Engine to GUI callback | `browser.set_confirmer(_confirm_kill)` plus `threading.Event` | The only real callback. It becomes an IPC "ask" (`ui.confirm`). |

Worst areas, ranked:
1. **`webview2_host.py` (3068 lines)** mixes five jobs: Win32 window tricks, cover
   *visuals* (Tk frames, spinners, % bars), cover *logic* (when to hide or reveal), OAuth
   popup adoption, and account jars. It also runs a Playwright watcher thread. 25
   `self.after()` timers drive the logic. **Logic is gold, visuals are disposable.**
2. **`dialogs.py` (1729)**: hand-built modals. `dialog_lapor_bug` is defined twice; the
   second copy silently wins (`:1452` vs `:1591`).
3. **`anim.py` (675) + `widgets.py` (1244)**: a hand-rolled animation and widget kit.
   Flutter gives us all of this for free. Delete.
4. **Settings writes race**: `typingbot_settings.json` is read-modify-written from three
   places with no lock (`app.py:922`, `activity.py:756`, `launch.py:124`).
5. Dead code: `on_recovery`, `on_tips`, the first `dialog_lapor_bug`. There is no Pause
   button (F9 only).

Engine side: clean enough. Typing goes through Playwright over CDP (`typing_core.py:189`),
so **the bot never needs OS keyboard focus**. That makes cross-process embedding much safer.

## 2. Responsibility split

| Flutter UI (`ui/`, Dart) | Python sidecar (`sidecar/` + existing `engine/`, `net/`) |
|---|---|
| Window, toolbar, panels, sheets, dialogs, settings, plan editor, toasts | Engine thread (`connect` / `main_loop` / `disconnect`, unchanged) |
| Cover *visuals* (boot, account switch, OAuth), with real animation | Cover *logic* (`_jaga`, watcher). Hides or shows the WebView2 window and tells Flutter what to draw |
| Rect of the "web area" widget, sent to the C++ runner | WebView2 creation, OAuth interception, popup adoption, account jars, spare pre-warm |
| Pure display of license and update state | Licensing (`net/license`), updater, bug report POST, settings file (single writer = no race) |
| Localised strings (Indonesian) | `translator.py` stays for M1, then is replaced by structured events in M2/M3 |

**The sidecar keeps a hidden Tk root.** It is used only as the Win32 message pump and the
`after()` scheduler. Why: all of `webview2_host.py`'s timing logic is written against
`after()`, Tk ships with Python, and Tk pumping the STA thread is what *already works* today.
The alternative (WinForms `Application.Run` + Timer) means .NET calling Python every tick,
which is exactly the GIL-crash pattern. Tk frames used as covers become "cover events" to
Flutter. `Wv2Host` stops being a `tk.Frame` with visible children and becomes a host object
that owns an invisible anchor window.

Note: the handoff said the cover machinery "survives untouched". The *logic* survives. The
~15 `.place()` overlay calls and the spinner/percent widgets must be rewired. That is
contained, but it is real work.

## 3. Embedding the WebView2 region

Chosen: **Option A, cross-process reparent.**

```
Flutter runner window (TypingBot UI, Dart + C++ runner)
├── FlutterView child HWND (all M3 chrome)
└── adopted HWND  <- WinForms control from the sidecar, holding WebView2
       position/size set IN-PROCESS by the runner from the Dart widget rect
```

Flow: at start the sidecar creates one **container** window (WinForms Panel, invisible
when empty) and sends `web.attach {hwnd}` once. Dart forwards it to the runner over a
platform channel. The runner calls `SetParent(container, runnerHwnd)` and keeps it in step
with the web-area widget's rect using `SetWindowPos(..., SWP_ASYNCWINDOWPOS)`. Today's four
`SetParent(..., self.winfo_id())` sites (`webview2_host.py:1200, 1280, 2650, 3029`: spare
swap, spare pre-warm, `buka`, popup adoption) retarget to the container. They stay
**in-process**, and children fill it via WinForms `Dock=Fill` (no Python callback). Covers
use `ShowWindowAsync`. Rule: the runner never makes a synchronous call into the sidecar's
window, so a hung sidecar can't freeze the UI.

Known costs and how we handle them:
- **Airspace**: Flutter cannot paint *over* the web area (true today in Tk as well).
  Sheets and dialogs that overlap it use today's approach (hide the page while the dialog
  is up). M2 upgrade: freeze a CDP `Page.captureScreenshot` of the page under a blurred
  scrim, so the page doesn't blink away. CDP screenshots are real pixels, unlike the dead
  PrintWindow path.
- **Focus and keyboard** (the user typing their login): cross-process child windows share
  an input queue. This needs testing. It is the #1 spike question.
- **Hangs**: a frozen sidecar UI thread can stall input to the Flutter window, because the
  input queues are attached. Mitigation: async-only Win32 calls (above). The sidecar's Tk
  thread never blocks (already a rule). The watchdog **kills** the sidecar if it stops
  answering, because detaching would itself block. On `WM_CLOSE` the runner detaches the
  container first, so closing the UI doesn't destroy the sidecar's control mid-flight.
- **Focus**: on `WM_ACTIVATE` the runner gives focus back to the web child if it had it
  (otherwise alt-tab in the middle of a password loses focus). The runner window uses
  `WS_CLIPCHILDREN` and the container sits above the FlutterView in z-order.
- **DPI**: today `bot_gui.py:192` sets per-monitor **v1** and only in `__main__`. The sidecar
  must set per-monitor **v2** before creating any window. Rects go in physical pixels.

Fallback if the spike fails: **Option C, owned (not child) window.** The sidecar keeps a
borderless top-level window *owned by* the Flutter window and tracking its rect. No input
queue coupling, a bit more z-order and move-lag fiddliness. Same container design, so the
switch is cheap.

Rejected for now: **Option B, Flutter hosts WebView2 itself** (`webview_windows` plugin,
texture mode) with Python attached over CDP. Its big upside is no airspace: Flutter could
animate over the page. But it rewrites the 3k lines of cover/OAuth logic in Dart, and the
plugin uses one global WebView2 environment, which breaks per-account data jars and the
pre-warmed spare. A better long-term variant to record: a custom C++ runner hosting WebView2
through `CompositionController` with one environment per data folder. That keeps the jars,
removes airspace, and Python attaches over CDP only. It is a post-3.6 experiment, not now.

## 4. IPC protocol

**Transport**: newline-delimited JSON over plain TCP on `127.0.0.1:<random port>`. Stdlib
only, so there's no new PyInstaller dependency. The sidecar picks the port and a random
token. The token goes to the UI via an environment variable (not argv, which other
processes can see). The UI sends it once at connect. On (re)connect the sidecar sends a
full snapshot. Why not stdio: the engine uses stdout as its log channel (prints
everywhere). The same protocol can also drive `bot_web.py` later, on Mac, Linux or Termux.

**The GIL rule, clarified**: the ban is on *.NET invoking Python on a foreign thread*.
Socket messages between two processes share no runtime; they are data. So the sidecar
pushing events is safe, provided it follows two rules:
1. All IPC runs on one asyncio thread in the sidecar.
2. Anything that touches WebView2/.NET or Tk is put on a queue that the Tk thread drains
   from its own `after()` loop. The IPC thread never calls `after()` itself.
3. Every `ask` has a timeout and a safe default (for example "cancel" or "no") for when the
   UI is gone, because the engine thread blocks on asks.

AGENTS.md currently says "request/response only, never callbacks across the boundary". If
this doc is approved, that line is amended to say what's above (owner sign-off = approval).

**Message shape**
```json
// Flutter -> sidecar (request)        // sidecar -> Flutter (reply)
{"id": 7, "m": "bot.start", "p": {...}}  {"id": 7, "ok": true, "r": {...}}  // or "err": {"code","msg"}
// sidecar -> Flutter (event, no id)   // sidecar -> Flutter (ask) + Flutter answer
{"ev": "state", "d": {...}}             {"ask": 3, "m": "ui.confirm", "p": {...}}  -> {"ans": 3, "r": {...}}
```

**State model**: the sidecar keeps one `snapshot` dict, built from `engine/state.py` plus
host and net status. It pushes diffs at most every 100 ms (`ev: state`). Flutter renders
only from the snapshot. That replaces the 150 ms Tk poll with the same data.

**Messages for full parity** (M1):

| Area | Requests (Flutter -> sidecar) | Events / asks (sidecar -> Flutter) |
|---|---|---|
| Session | `hello {ui_version}`, `app.quit` | `hello {app_version, platform, features}` |
| Window | `web.rect {x,y,w,h,dpi}` (only if the runner can't do it alone), `web.visible {bool}` | `web.attach {hwnd}`, `web.detach` |
| Bot | `bot.start {range?, plan?}`, `bot.pause`, `bot.resume`, `bot.stop`, `bot.recover` | `state` (running/paused/stopped/needs_login/await_range/range_done/browser_closed, level, label, url) |
| Speed | `speed.set {wpm, save}` | (in `state`) |
| Hotkeys | `hotkeys.set {on}` | `hotkey {key}` (F9/F10/F11 pressed: UI feedback) |
| Range | `range.get`, `range.answer {mode: lanjut, custom, halaman, cancel, start, end}`, `levels.build_map`, `levels.progress` | `ask range.pick {start, end, mapped, total}`, `ask level.next` ("still waiting?") |
| Login | `login.open {kind: individu, sekolah}` | `ask login.needed`, `ask level.locked` |
| Accounts | `acct.list`, `acct.switch {name}`, `acct.add`, `acct.remove {name}`, `acct.logout` | `acct.changed`, `cover {phase, progress, text}` (boot, switch, OAuth) |
| Browser (external mode) | `browser.list`, `browser.pick {exe, profile}` | `ask browser.force_close {name, pid}` (was `set_confirmer`) |
| License | `license.status`, `license.request {nickname}` | `license {state, days_left, nickname}` (pending/approved/revoked) |
| Update | `update.check`, `update.download`, `update.install`, `update.cancel` | `update {available, version, notes, progress}` |
| Bug report | `report.send {category, text}` | reply ok/err |
| Logs | `log.tail {n}` | `log {raw, friendly}` (friendly = `translator.py` output) |
| Dev | `dev.info`, `dev.open {log, data}`, `dev.reset_settings`, `dev.fake_version` | |
| Settings | `settings.get`, `settings.set {k: v}` | |
| M3 (later) | `plan.get/set/run`, `stars.target {level, stars}` | `level.result {level, wpm, acc, stars}` |

## 5. Packaging and updates (my change to the handoff)

The handoff had Flutter launch the sidecar. I propose the reverse: **`TypingBot.exe` stays
the PyInstaller exe and is the only thing users launch.** It starts the Flutter UI as a
child, with the IPC port, and the token in env. Why:
- Old 3.5.x users auto-update by replacing one exe. That path keeps working.
- `net/license` and `net/updater` stay where they are and are tested by the 122 net tests.

**The size limit can go away.** Users already download the exe from the GitHub release
asset (`worker.js:330`, a 302 redirect). The ~95 MB cap comes only from `publish.py` still
uploading the full exe to the worker so it can record sha256/size. Change `publish.py` to
send only `{version, sha256, size, notes}`. Then the only limit is GitHub's 2 GB, so the
75-85 MB exe plus the ~10 MB compressed UI bundle is fine.

So: **embed the UI bundle in the exe** (one file, one asset, one sha256 check, works
offline). On launch, unpack it to `%LOCALAPPDATA%/TypingBot/ui/<version>/`, atomically
(unpack to a temp folder, then rename) and only once per version. Old version folders are
deleted.

Gaps to close in M1d:
- `net/updater.py:146-148`: the swap batch only kills `TypingBot.exe`. It must also kill the
  UI exe.
- Taskbar pins: give both processes the same AppUserModelID so a pin relaunches
  `TypingBot.exe`. The UI exe started alone (no IPC env) just relaunches the launcher and exits.
- Antivirus: an unsigned exe that drops and runs another unsigned exe is a classic false
  positive trigger. Test with Windows Defender on the spike. Fallback: ship a zip/installer
  folder instead (bigger updater change).
- Measure the real exe + bundle size during the spike, not conditionally.

## 6. Cross-platform (managing the dream)

The Flutter UI runs on any OS from day one. On non-Windows, the sidecar runs in
"external browser" mode (`bot_web.py`'s POSIX patches: system Chrome/Chromium with a debug
port). The web area then shows a card saying "edclub is open in its own window". That is a
working Mac/Linux edition with the same UI. **Not in M1 scope.** M1 keeps the protocol
OS-neutral so it is cheap later. Embedded-page UX stays Windows-only.

## 7. Repo layout

```
ui/               Flutter app (lib/, windows/ runner with the HWND adoption code)
sidecar/          main.py (entry), ipc.py (TCP JSON + snapshot), host.py (Wv2Host minus Tk visuals),
                  bridge.py (state <-> snapshot, commands -> flag writes)
engine/ net/      unchanged in M1
gui/              kept until M1 parity is verified on Windows, then deleted (M2)
bot_gui.py, autopilot_pw.py   facades stay (tests patch through them)
```

## 8. Development environment (correction)

This VPS has no Flutter SDK, no `sudo`, no GTK/cmake/ninja and 3 GB RAM, so the
`flutter run -d linux` path in the handoff does not work as-is. Plan:
- Install the Flutter SDK in `~` (no sudo needed).
- Develop the UI against a **mock sidecar** (a Python script replaying realistic states).
- Preview and screenshot via `flutter build web` + headless Chromium. If the owner can run
  `sudo apt install clang cmake ninja-build libgtk-3-dev xvfb`, Linux desktop works too.
- Everything Windows (runner HWND code, WebView2, packaging) is verified on the owner's
  PC through the existing verify chain.

## 9. Phase plan for M1 (split into four chunks)

| Step | What | Where verified | Exit |
|---|---|---|---|
| **M1a0 refactor in place** | Split `Wv2Host` *inside today's app*: logic talks to a `CoverSink` (show/hide/progress/text) and a `Surface` (container hwnd, size via `GetClientRect`) interface. Tk implements both for now. All four `SetParent` sites retarget to one container. Ship as a 3.5.x dev build, so the fixes still landing in `gui/` aren't forked | Owner's PC: verify chain + a real day of use (boot, switch, OAuth) | No behaviour change, users notice nothing |
| **M1a spike** | Minimal Flutter runner + the sidecar container. Must pass: resize/maximize, typing in a **real Google OAuth popup**, spare-swap account switch, `sleep(30)` on the sidecar Tk thread (UI must stay alive), killing the UI, killing the sidecar, alt-tab mid-typing, mixed-DPI monitors (100% + 150%), Defender scan, size measure | Owner's PC (I ship a zip + a checklist) | GO with A, or switch to C |
| **M1b sidecar** | `sidecar/` with IPC, snapshot, all commands mapped to today's flag writes, hidden Tk pump, a `CoverSink` that emits events. Mock mode for Linux | Protocol tests here + new sidecar tests + existing suites on Windows | Every parity message works against the mock and the real engine |
| **M1c Flutter chrome** | Every control from the parity table, M3 seeded dark theme, two fonts. Ugly OK | Web build screenshots here | Every feature reachable |
| **M1d integrate + package** | Bundle the UI in the exe, launcher, updater kill list, AppUserModelID, `publish.py` hash-only, verify chain + smoke | Owner's PC | 3.6.0-dev1 runs a full lesson range |

**Biggest risk to the whole plan** (advisor's and mine): regressing OAuth and cover
behaviour while rewiring it, with every Windows check going through the owner's PC. M1a0
is the mitigation: the risky refactor ships inside the app that already works, where the
owner can tell us right away if anything feels different.

Then M2 (design system), M3 (stars + plans; note: no star or accuracy data is exposed to
the UI today, only parsed in `levels.py:418,491`), M4 polish, M5 release CI, as in the handoff.
