# Notes for AI agents working in this repo

## Toolchain (IMPORTANT)
The `python` on PATH inside the shell is msys (no pip, no PyInstaller).
The real interpreter is the manager shim:
`C:/Users/ACER/AppData/Local/Python/bin/python.exe` (3.14.4 + PyInstaller
+ cryptography). Pin it as PY for tests, harness and builds.

## Verify chain (run before declaring victory)
1. `"$PY" -W error::SyntaxWarning -m py_compile bot_gui.py autopilot_pw.py gui/*.py engine/*.py engine/lessons/*.py net/*.py server/local_server.py server/publish.py server/gen_keys.py`
2. Suites (each writes `_uitest.txt` in "w" mode - snapshot after EACH):
   `"$PY" -X utf8 tests/_test_<name>.py > _st.txt 2>&1` then copy
   `_uitest.txt` to `_out_<name>.txt`. Suites: ui_polish profile_ui
   rentang_ui rentang_validasi resume_list login_patrol port_luwes net.
3. `"$PY" -X utf8 tests/_test_harness.py` (~90s) must end with
   "AKURASI 100% di semua skenario."
4. Build: taskkill TypingBot.exe first, then
   `"$PY" -m PyInstaller --onefile --windowed --name TypingBot --version-file version_info.txt --clean --noconfirm bot_gui.py`
5. PYZ check via CArchiveReader + open_embedded_archive('PYZ.pyz').
6. Smoke: run exe 25s, require "Modul bot dimuat" line in dist/bot.log
   (empty log = false pass, that hid a startup crash once).

## Conventions
- Identifiers English; comments casual short Indonesian; user-facing
  strings plain friendly Indonesian (translator layer converts engine log).
- Facades autopilot_pw.py / bot_gui.py must keep old import paths working
  (test suites + monkeypatching depend on owner-routing shim).
- Commit trailer: `Assisted-by: Crush (AI agents)` (neutral, no model).
- Never push without explicit user ask; never commit gitignored `_*.py`.

## Online features (v2.7)
- net/ client + server/ backend, contract in server/API.md.
- Local dev backend: `"$PY" -X utf8 server/local_server.py` (auto-generates
  server/_signing.json Ed25519 keypair; pub key picked up by net.license
  when TYPINGBOT_SERVER_PUBKEY unset and not frozen).
- Production deploy guide: server/DEPLOY.md (Cloudflare Worker + KV only,
  no R2 and no credit card: the exe is stored as 20 MiB KV chunks in
  META; Worker free plan body limit means exe must stay under ~95 MB).
- Release flow: build exe -> `"$PY" server/publish.py dist/TypingBot.exe
  --version X.Y --notes "..."` (url/admin key from server/_admin.json).
- Old manual HMAC keys stay valid; token files are one-line JSON in
  license.dat (sniffed by leading "{").
