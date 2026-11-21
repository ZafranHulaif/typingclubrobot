"""Protokol sidecar <-> UI (lihat docs/architecture/M0-decision.md §4).

UI  -> sidecar : {"id": n, "m": "bot.start", "p": {...}}
sidecar -> UI  : {"id": n, "ok": true, "r": {...}} / {"id": n, "ok": false, "err": {...}}
sidecar -> UI  : {"ev": "state", "d": {...patch...}}   (dorongan, tanpa id)
sidecar -> UI  : {"ask": n, "m": "range.pick", "p": {...}}  -> UI {"ans": n, "r": {...}}

Aturan GIL: semua IPC di thread socket sendiri. Backend yang menyentuh
.NET/WebView2/Tk WAJIB mengantrekan kerjanya ke thread Tk, bukan langsung.
"""
import copy
import hmac
import itertools
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import ws

PROTO = 1


class RpcError(Exception):
    def __init__(self, code, msg=""):
        super().__init__(msg or code)
        self.code = code
        self.msg = msg or code


class Snapshot:
    """State tunggal yang dirender UI. update() menandai key berubah,
    pusher mengirim patch maks tiap 100 ms."""

    def __init__(self, awal):
        self._d = copy.deepcopy(awal)
        self._kotor = set()
        self._lock = threading.Lock()

    def update(self, key, **kw):
        """Gabung field ke dict level-1 `key` (atau ganti nilai biasa
        via update(key, value=...))."""
        with self._lock:
            lama = self._d.get(key)
            if isinstance(lama, dict) and "value" not in kw:
                baru = dict(lama)
                baru.update(kw)
            else:
                baru = kw.get("value")
            if baru != lama:
                self._d[key] = baru
                self._kotor.add(key)

    def get(self, key):
        with self._lock:
            return copy.deepcopy(self._d.get(key))

    def full(self):
        with self._lock:
            return copy.deepcopy(self._d)

    def take_patch(self):
        with self._lock:
            if not self._kotor:
                return None
            p = {k: copy.deepcopy(self._d[k]) for k in self._kotor}
            self._kotor.clear()
            return p


class Server:
    def __init__(self, backend, token="", host="127.0.0.1", port=0):
        self.backend = backend
        self.token = token
        self.host, self.port = host, port
        self._clients = []
        self._clock = threading.Lock()
        self._asks = {}             # id -> [Event, jawaban]
        self._ask_id = itertools.count(1)
        self._pool = ThreadPoolExecutor(max_workers=4,
                                        thread_name_prefix="rpc")
        self._stop = threading.Event()
        self.last_seen = time.time()
        backend.attach(self)

    # ------------------------------------------------------------ hidup
    def start(self):
        self._srv, self.port = ws.serve(self.host, self.port, self._klien)
        threading.Thread(target=self._pusher, daemon=True,
                         name="snapshot-push").start()
        return self.port

    def stop(self):
        self._stop.set()
        try:
            self._srv.close()
        except Exception:
            pass
        for c in list(self._clients):
            c.close()

    @property
    def connected(self):
        return bool(self._clients)

    # ------------------------------------------------------------ kirim
    def _kirim(self, c, obj):
        try:
            c.send(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
        except ws.WsClosed:
            self._buang(c)

    def emit(self, ev, data=None):
        """Dorong event ke semua UI. Aman dari thread mana pun."""
        for c in list(self._clients):
            self._kirim(c, {"ev": ev, "d": data})

    def ask(self, m, p=None, timeout=60.0, default=None):
        """Tanya UI & tunggu jawaban. Tanpa UI / timeout -> default
        (engine nunggu di sini, jadi JANGAN pernah tanpa batas)."""
        if not self._clients:
            return default
        n = next(self._ask_id)
        ev = threading.Event()
        self._asks[n] = [ev, default]
        self.emit_raw({"ask": n, "m": m, "p": p or {}})
        ev.wait(timeout)
        return self._asks.pop(n, [None, default])[1]

    def emit_raw(self, obj):
        for c in list(self._clients):
            self._kirim(c, obj)

    def _pusher(self):
        snap = self.backend.snapshot
        while not self._stop.wait(0.1):
            p = snap.take_patch()
            if p:
                self.emit("state", p)

    # ------------------------------------------------------------ terima
    def _buang(self, c):
        with self._clock:
            if c in self._clients:
                self._clients.remove(c)
        c.close()
        if not self._clients:
            # UI hilang: lepas semua ask yg nunggu (pakai default)
            for n, slot in list(self._asks.items()):
                slot[0].set()

    def _klien(self, c):
        # pesan pertama WAJIB hello + token
        try:
            first = json.loads(c.recv())
        except (ws.WsClosed, ValueError):
            c.close()
            return
        tok = str((first.get("p") or {}).get("token", ""))
        if first.get("m") != "hello" or (
                self.token and not hmac.compare_digest(tok, self.token)):
            self._kirim(c, {"id": first.get("id"), "ok": False,
                            "err": {"code": "auth", "msg": "token salah"}})
            c.close()
            return
        with self._clock:
            self._clients.append(c)
        self.last_seen = time.time()
        self._kirim(c, {"id": first.get("id"), "ok": True,
                        "r": {"proto": PROTO, **self.backend.hello()}})
        self._kirim(c, {"ev": "snapshot", "d": self.backend.snapshot.full()})
        while True:
            try:
                raw = c.recv()
            except ws.WsClosed:
                self._buang(c)
                return
            self.last_seen = time.time()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if "ans" in msg:
                slot = self._asks.get(msg["ans"])
                if slot:
                    slot[1] = msg.get("r")
                    slot[0].set()
                continue
            if "m" in msg:
                self._pool.submit(self._jalan, c, msg)

    def _jalan(self, c, msg):
        mid, m, p = msg.get("id"), msg["m"], msg.get("p") or {}
        try:
            if m == "ping":
                r = {"t": time.time()}
            else:
                r = self.backend.handle(m, p)
            out = {"id": mid, "ok": True, "r": r}
        except RpcError as e:
            out = {"id": mid, "ok": False,
                   "err": {"code": e.code, "msg": e.msg}}
        except Exception as e:      # jangan biarkan sidecar mati
            out = {"id": mid, "ok": False,
                   "err": {"code": "internal", "msg": str(e)[:300]}}
        if mid is not None:
            self._kirim(c, out)
