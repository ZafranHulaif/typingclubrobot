# TypingBot — context for AI coding agents (canonical)

This is THE context file. T3 Code (pi) loads it automatically from the repo
root in every thread; Claude Code loads `CLAUDE.md`, which just points here.
Read it first — everything below is settled knowledge from months of live
debugging. Do not re-derive it, do not violate it.

## What this project is
TypingBot is a Windows desktop app that automates typing practice on
edclub.com (TypingClub) — types lessons/games at up to 400 WPM, farms stars,
multi-account, distributed as a single exe to a small group of users.
Licensing + updates + bug reports run through a Cloudflare Worker backend.

- Current line: `3.5.5-dev21`, branch `qol-edge` (pending merge → `main` = 3.5.5 final).
- Owner is not a professional developer. Explain decisions simply. UI text for
  end users: plain friendly Indonesian, NO em dashes, no technical jargon.

## Tech stack (and what it is NOT)
- Python 3.14, **Tkinter** UI (`gui/`), **pywebview EdgeChrome** embedding a
  WebView2 browser in-app (edclub renders inside the window).
- Automation = **CDP** (Chrome DevTools Protocol): playwright connects to the
  embedded WebView2 debug port and drives/injects JS.
- **PyInstaller is only the packager** (python → exe). There is no app
  framework; the UI is raw Tkinter — this is THE main UX limitation.
- **Windows-only** (current app): WebView2, pythonnet, Win32 calls. Cannot
  build or run on Linux. NOTE: `bot_web.py` is an existing CROSS-PLATFORM
  web edition (headless/system Chromium via playwright, web panel on
  localhost:8765, macOS/Linux/Windows/Termux) — platform-independent
  automation already exists in-repo.

## Repo map (battle-tested — do not rewrite blindly)
- `engine/` — automation core (framework-independent, KEEP): `browser.py`
  (playwright session, typing w/ per-letter delays), `jstemplates.py`,
  `lessons/` (standard/games/ocr/video), `levels.py`, `session.py`,
  `supervisor.py`, `state.py`, `typing_core.py`, `hotkeys.py`, `recovery.py`.
- `gui/` — Tkinter shell (THE REWRITE TARGET, full of accumulated patches):
  `app.py` (main window), `launch.py` (boot + account popover),
  `webview2_host.py` (WebView2 host, boot/switch cover machine, OAuth
  interception, playwright watcher), `widgets.py`, `theme.py` (APP_VERSION,
  colors), `dialogs.py`, `activity.py`, `translator.py`, `meisweep.py`.
- `net/` — licensing (Ed25519 tokens; legacy HMAC still valid) + updater
  (`parse_version` strips `-devN`).
- `server/` — Cloudflare Worker backend: `worker.js` (API + exe stored as
  <20MiB KV chunks — **exe must stay < ~95MB**), `publish.py`, `wrangler.toml`
  (`keep_vars=true`, secrets ADMIN_KEY/LAPOR_HOOK/LAPOR_HOOK_TOKEN),
  `local_server.py` (dev backend), `API.md`, `DEPLOY.md`.
- `bot_gui.py` / `autopilot_pw.py` — facade entry points (old import paths
  must keep working; tests monkeypatch through them).
- `paths.py` — frozen app stores user data in `%LOCALAPPDATA%/TypingBot`
  (license.dat, settings, profiles, bot.log), never beside the exe.
- `tests/` — `_test_net.py` (122 tests), `_test_profile_ui.py` (30),
  `_test_rentang_ui.py`, `_test_harness.py` (e2e accuracy, ~90s, must end
  with "AKURASI 100% di semua skenario.").

## Hard-won constraints (each line below = a crash/regression we already paid for)
- **NEVER add .NET→Python event callbacks** (GIL crash, PyEval_RestoreThread).
  Poll from the Tk thread or read .NET properties directly. Playwright
  evaluate is the only injection path proven to work reliably. For the
  Flutter↔Python sidecar bridge (see `docs/architecture/M0-decision.md`):
  socket messages are data, not callbacks, so the sidecar MAY push events,
  but all IPC runs on one asyncio/socket thread and anything touching
  .NET/WebView2/Tk is queued to the Tk/STA thread (drained by its own
  `after()` loop). Asks from engine to UI need a timeout + safe default.
- Google pages enforce Trusted Types CSP: `innerHTML` blocked — use
  `textContent` / `createElementNS`.
- Google OAuth is intercepted **in-app**: `window.open` must be stubbed BEFORE
  navigation (document born with the stub), real popup windows are adopted as
  children, and covers hide all transitions. Do not "simplify" this away.
- edclub `rt` refresh token is single-use — never race the rotation.
- Cloudflare WAF blocks non-browser User-Agents — admin/API scripts need
  `User-Agent: Mozilla/5.0 ... TypingBot-admin/1.0`.
- PrintWindow on hidden/offscreen WebView2 returns fake black — pixel gating
  is dead forever. DOM/title/.NET-property gates only.
- `pop.grab_set()` eats all clicks outside a popover — click-outside close is
  a global poller, never grab.
- Multi-account: per-account data jars under
  `%LOCALAPPDATA%/TypingBot/profil-akun/<name>`; a pre-warmed spare webview
  makes switching instant (cold start was slow — fixed in dev21).
- Lesson-list skips must be STRICTLY in order (skip locked rows only).
- Release notes on GitHub are ENGLISH ("## Fixes in X.Y.Z", bold bullet
  leads) even though code comments/UI are Indonesian.

## Conventions
- Identifiers English; comments casual short Indonesian; user-facing strings
  plain friendly Indonesian.
- Commits: Indonesian summary, NO AI attribution trailer (owner decision 2026-11-21).
- Dev workflow: bump `APP_VERSION` (`"3.5.5-devN"`) in `gui/theme.py` per
  build on `qol-edge`; on merge → `main`, version becomes clean `3.5.5`,
  GitHub release + `server/publish.py` to the worker.
- Never push without explicit user ask; never commit gitignored `_*.py`.
- Facades `bot_gui.py` / `autopilot_pw.py` keep old import paths working.

## Toolchain & verify chain (Windows machine only)
The `python` on PATH inside the shell is msys (no pip, no PyInstaller).
The real interpreter is the manager shim:
`C:/Users/ACER/AppData/Local/Python/bin/python.exe` (3.14.4 + PyInstaller
+ cryptography). Pin it as PY for tests, harness and builds.

1. `"$PY" -W error::SyntaxWarning -m py_compile bot_gui.py autopilot_pw.py gui/*.py engine/*.py engine/lessons/*.py net/*.py server/local_server.py server/publish.py server/gen_keys.py`
2. Suites (each writes `_uitest.txt` in "w" mode — snapshot after EACH):
   `"$PY" -X utf8 tests/_test_<name>.py > _st.txt 2>&1` then copy
   `_uitest.txt` to `_out_<name>.txt`. Suites: ui_polish profile_ui
   rentang_ui rentang_validasi resume_list login_patrol port_luwes net.
3. `"$PY" -X utf8 tests/_test_harness.py` (~90s) must end with
   "AKURASI 100% di semua skenario."
4. Build: taskkill TypingBot.exe first (a running app LOCKS the exe and
   PyInstaller can report success while the file stays stale!), then
   `"$PY" -m PyInstaller --onefile --windowed --name TypingBot --icon docs/logo.ico --add-data "docs/logo.png;assets" --add-data "docs/logo.ico;assets" --version-file version_info.txt --exclude-module cv2 --collect-all webview --collect-all pythonnet --collect-all clr_loader --clean --noconfirm bot_gui.py`
   (logo.ico MUST be bundled: `gui/theme.py` `_asset_path("logo.ico")` only
   finds it under _MEIPASS/assets.)
5. PYZ check via CArchiveReader + open_embedded_archive('PYZ.pyz').
6. Smoke: run exe 25s, require "Modul bot dimuat" line in
   `%LOCALAPPDATA%/TypingBot/bot.log` (frozen app writes its log there,
   NOT next to the exe; empty log = false pass).

## Online features / backend ops
- `net/` client + `server/` backend, contract in `server/API.md`.
- Local dev backend: `"$PY" -X utf8 server/local_server.py` (auto-generates
  `server/_signing.json` Ed25519 keypair; pub key picked up by `net.license`
  when TYPINGBOT_SERVER_PUBKEY unset and not frozen).
- Production deploy guide: `server/DEPLOY.md` (Cloudflare Worker + KV only;
  exe stored as 20 MiB KV chunks in META; Worker free plan body limit means
  exe must stay under ~95 MB).
- Release flow: build exe → `"$PY" server/publish.py dist/TypingBot.exe
  --version X.Y --notes "..."` (url/admin key from `server/_admin.json`).
- If publish 503s repeatedly while /api/latest still reads fine: capture the
  error body — `error code: 1102` = worker exceeded resources on the ~70 MB
  upload at YOUR nearest POP. Fix: route through a VPN/other region and
  re-run publish. CF-RAY footer in the error shows the POP.
- Old manual HMAC keys stay valid; token files are one-line JSON in
  license.dat (sniffed by leading "{").
- Bug-report webhook → realtime developer thread (worker LAPOR_HOOK).

## Feature status (works today — don't regress)
Boot cover → logged-in dashboard with no flash; multi-account switching
(pre-warmed spare webview, per-account jars); in-app Google OAuth with
full-cover transitions; bug-report button → realtime developer thread
(worker webhook); update pill for old versions; Ed25519 licensing;
level-range plans; games / OCR / video lessons; Indonesian UI strings via
translator layer.

## Roadmap (owner's current mission) - v4, branch `v4`
**Read `docs/architecture/v4-native-plan.md` first.** v4 = one native Flutter
Windows app: Dart UI (done, approved), Dart engine ported from `engine/*.py`
(JS payloads reused verbatim), Dart net port, C++ runner hosting WebView2
(env per account jar, CDP via CallDevToolsProtocolMethod). The Python
sidecar route in `M0-decision.md` §2-§5 is SUPERSEDED (owner, 2026-11-21).
Python code stays as the spec + 3.5.x hotfix line until parity.
UI rules the owner approved: minimal tool (no bloat), status shown once in
a control capsule, single Mulai/Stop toggle (no pause), no hotkeys, small
corners, Emil Kowalski motion rules, plan = tiles of level ranges with star
targets (perak = top grade), active segment + next 2 levels locked while
running. Preview on the VPS: `ui/tool/preview.sh` (memory-capped build!).
