"""Kontrak backend: bentuk snapshot + daftar method yang dipanggil UI.

MockBackend (Linux/preview) dan EngineBackend (Windows, engine asli)
sama2 turunan Backend - UI tidak tahu bedanya.
"""
from .server import RpcError, Snapshot

SPEED_TIERS = [40, 85, 140, 200, 225, 250, 275, 300, 400]
SPEED_NAMES = {40: "Pelan", 85: "Santai", 140: "Normal", 200: "Cepat",
               225: "Kilat", 250: "Ngebut", 275: "Gila", 300: "Maksimal",
               400: "Paranormal"}

# fase bot (UI mewarnai & memilih tombol dari sini)
#   idle | starting | running | paused | stopping | done | error
DEFAULT_SNAPSHOT = {
    "app": {"version": "0.0.0", "platform": "unknown", "mode": "mock",
            "embedded_web": False},
    "bot": {"phase": "idle", "needs_login": False, "browser_closed": False,
            "waiting_setup": False, "error": ""},
    "level": {"num": 0, "label": "", "kind": "", "url": "",
              "progress": 0.0},
    "range": {"start": 1, "end": 0, "mapped": 0, "total": 0,
              "position": 0},
    "speed": {"wpm": 400, "tiers": SPEED_TIERS, "names": SPEED_NAMES},
    "hotkeys": {"on": True},
    "activity": {"headline": "Siap", "sub": "Klik Mulai untuk mulai."},
    "account": {"active": "", "list": [], "needs_relogin": False},
    "license": {"state": "ok", "nickname": "", "days_left": None,
                "message": ""},
    "update": {"available": False, "version": "", "notes": "",
               "phase": "idle", "progress": 0.0, "size": 0},
    "cover": {"visible": False, "phase": "", "text": "", "progress": None},
    "web": {"attached": False, "hwnd": 0},
    # rencana: daftar bagian level berurutan, masing2 punya target bintang.
    #   segments: [{"from": 1, "to": 10, "stars": 5, "silver": True}, ...]
    #   to = 0 -> sampai habis. active = indeks bagian yg sedang dikerjakan.
    "plan": {"segments": [], "active": None, "done_in_active": 0},
    "stats": {"levels_done": 0, "chars": 0, "started_at": None},
}

# semua method publik. Backend wajib menangani, atau RpcError("unsupported")
METHODS = [
    "bot.start", "bot.pause", "bot.resume", "bot.stop", "bot.recover",
    "speed.set", "hotkeys.set",
    "range.get", "levels.build_map", "plan.set",
    "login.open",
    "acct.list", "acct.switch", "acct.add", "acct.remove", "acct.logout",
    "license.request", "license.refresh",
    "update.check", "update.download", "update.install", "update.cancel",
    "report.send", "log.tail",
    "settings.get", "settings.set",
    "dev.info", "dev.open", "dev.reset_settings",
    "web.visible", "app.quit", "dev.simulate",
]


class Backend:
    def __init__(self):
        self.snapshot = Snapshot(DEFAULT_SNAPSHOT)
        self.server = None

    def attach(self, server):
        self.server = server

    # ---- dipanggil server
    def hello(self):
        return {"methods": METHODS}

    def handle(self, m, p):
        fn = getattr(self, "m_" + m.replace(".", "_"), None)
        if fn is None:
            raise RpcError("unsupported", m)
        return fn(**p)

    # ---- util utk turunan
    def emit(self, ev, data=None):
        if self.server:
            self.server.emit(ev, data)

    def ask(self, m, p=None, timeout=60.0, default=None):
        if not self.server:
            return default
        return self.server.ask(m, p, timeout, default)

    def log(self, raw, friendly=None, level="info"):
        import time
        self.emit("log", {"t": time.time(), "raw": raw,
                          "friendly": friendly, "level": level})
