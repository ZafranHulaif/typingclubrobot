"""Tes protokol sidecar (stdlib saja): python -m sidecar.test_protocol"""
import base64
import json
import os
import socket
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sidecar.mock import MockBackend  # noqa: E402
from sidecar.server import Server     # noqa: E402


class Klien:
    def __init__(self, port):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET / HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\n"
                        f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                        "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.s.recv(1024)
        assert b" 101 " in buf.split(b"\r\n")[0], buf
        self.sisa = buf.split(b"\r\n\r\n", 1)[1]
        self.n = 0
        self.antre = []

    def kirim(self, obj):
        d = json.dumps(obj).encode()
        mask = os.urandom(4)
        n = len(d)
        head = (struct.pack("!BB", 0x81, 0x80 | n) if n < 126 else
                struct.pack("!BBH", 0x81, 0x80 | 126, n))
        self.s.sendall(head + mask + bytes(c ^ mask[i % 4]
                                           for i, c in enumerate(d)))

    def _baca(self, n):
        while len(self.sisa) < n:
            p = self.s.recv(65536)
            if not p:
                raise EOFError
            self.sisa += p
        out, self.sisa = self.sisa[:n], self.sisa[n:]
        return out

    def terima(self):
        b1, b2 = self._baca(2)
        n = b2 & 0x7F
        if n == 126:
            n = struct.unpack("!H", self._baca(2))[0]
        elif n == 127:
            n = struct.unpack("!Q", self._baca(8))[0]
        data = self._baca(n)
        if b1 & 0x0F == 0x8:
            raise EOFError
        return json.loads(data)

    def req(self, m, **p):
        self.n += 1
        self.kirim({"id": self.n, "m": m, "p": p})
        while True:
            msg = self.terima()
            if msg.get("id") == self.n:
                return msg
            self.antre.append(msg)

    def tunggu(self, cocok, batas=10):
        t0 = time.time()
        for i, m in enumerate(self.antre):
            if cocok(m):
                return self.antre.pop(i)
        while time.time() - t0 < batas:
            m = self.terima()
            if cocok(m):
                return m
            self.antre.append(m)
        raise TimeoutError


def main():
    be = MockBackend()
    srv = Server(be, token="rahasia")
    port = srv.start()
    hasil = []

    def cek(nama, ok):
        hasil.append(ok)
        print(("OK   " if ok else "GAGAL ") + nama)

    # token salah ditolak
    k = Klien(port)
    r = k.req("hello", token="salah")
    cek("token salah ditolak", r.get("ok") is False
        and r["err"]["code"] == "auth")

    k = Klien(port)
    r = k.req("hello", token="rahasia")
    cek("hello ok + daftar method", r["ok"] and "bot.start" in r["r"]["methods"])
    snap = k.tunggu(lambda m: m.get("ev") == "snapshot")
    cek("snapshot penuh dikirim", snap["d"]["account"]["active"] == "zafran")

    r = k.req("speed.set", wpm=999)
    cek("speed dijepit ke 400", r["r"]["wpm"] == 400)
    patch = k.tunggu(lambda m: m.get("ev") == "state" and "speed" in m["d"]
                     or False, 3) if False else None
    r = k.req("speed.set", wpm=140)
    patch = k.tunggu(lambda m: m.get("ev") == "state"
                     and m["d"].get("speed", {}).get("wpm") == 140, 3)
    cek("patch state speed terkirim", patch is not None)

    r = k.req("nope.nope")
    cek("method tak dikenal -> unsupported",
        not r["ok"] and r["err"]["code"] == "unsupported")

    # rencana: tumpang tindih ditolak, valid diterima & dipakai saat mulai
    r = k.req("plan.set", segments=[{"from": 1, "to": 10, "stars": 5},
                                    {"from": 5, "to": 20, "stars": 4}])
    cek("rencana tumpang tindih ditolak", not r["ok"])
    r = k.req("plan.set", segments=[
        {"from": 10, "to": 10, "stars": 5, "silver": True},
        {"from": 11, "to": 11, "stars": 3}])
    cek("rencana valid diterima", r["ok"] and r["r"]["segments"][0]["silver"])
    k.req("speed.set", wpm=400)
    r = k.req("bot.start")
    cek("mulai pakai rencana (tanpa ask)", r["ok"] and r["r"]["started"])
    k.tunggu(lambda m: m.get("ev") == "state"
             and m["d"].get("bot", {}).get("phase") == "done", 30)
    res = [m["d"]["stars"] for m in k.antre if m.get("ev") == "level.result"]
    cek("bintang ikut target tiap bagian", res == [5, 3])
    k.antre.clear()
    k.req("plan.set", segments=[])

    # tanpa rencana -> ask range.pick; UI jawab custom
    k.n += 1
    sid = k.n
    k.kirim({"id": sid, "m": "bot.start", "p": {}})
    ask = k.tunggu(lambda m: m.get("ask") and m["m"] == "range.pick", 5)
    cek("ask range.pick muncul", ask["p"]["total"] == 685)
    k.kirim({"ans": ask["ask"], "r": {"mode": "custom", "start": 10,
                                       "end": 11}})
    r = k.tunggu(lambda m: m.get("id") == sid, 5)
    cek("bot mulai setelah jawab", r["ok"] and r["r"]["started"])
    k.tunggu(lambda m: m.get("ev") == "state"
             and m["d"].get("bot", {}).get("phase") == "running", 5)
    cek("fase running", True)
    k.req("speed.set", wpm=400)
    done = k.tunggu(lambda m: m.get("ev") == "state"
                    and m["d"].get("bot", {}).get("phase") == "done", 30)
    cek("rentang 10-11 selesai -> done", done is not None)
    res = [m for m in k.antre if m.get("ev") == "level.result"]
    cek("2 level.result", len(res) == 2)

    # ask tanpa jawaban -> default saat UI putus
    k.n += 1
    k.kirim({"id": k.n, "m": "dev.simulate", "p": {"what": "next"}})
    k.tunggu(lambda m: m.get("ask"), 5)
    k.s.close()
    time.sleep(0.5)
    cek("UI putus -> klien dibuang", not srv.connected)

    srv.stop()
    print(f"\n{sum(hasil)}/{len(hasil)} lulus")
    return 0 if all(hasil) else 1


if __name__ == "__main__":
    sys.exit(main())
