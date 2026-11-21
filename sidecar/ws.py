"""WebSocket server mini (RFC 6455) - stdlib saja, tanpa dependensi baru.

Cukup buat kebutuhan kita: teks JSON kecil, satu-dua klien lokal.
Browser (preview web) & Flutter desktop sama2 bisa konek ke sini.
"""
import base64
import hashlib
import socket
import struct
import threading

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class WsClosed(Exception):
    pass


class WsConn:
    """Satu koneksi WebSocket. send() aman dipanggil dari thread mana pun."""

    def __init__(self, sock, path=""):
        self.sock = sock
        self.path = path
        self._wlock = threading.Lock()
        self.closed = False

    # ---- kirim
    def send(self, text):
        data = text.encode("utf-8")
        n = len(data)
        if n < 126:
            head = struct.pack("!BB", 0x81, n)
        elif n < 65536:
            head = struct.pack("!BBH", 0x81, 126, n)
        else:
            head = struct.pack("!BBQ", 0x81, 127, n)
        self._raw(head + data)

    def _raw(self, buf):
        if self.closed:
            raise WsClosed()
        try:
            with self._wlock:
                self.sock.sendall(buf)
        except OSError:
            self.closed = True
            raise WsClosed()

    def close(self):
        if self.closed:
            return
        try:
            self._raw(b"\x88\x00")
        except WsClosed:
            pass
        self.closed = True
        try:
            self.sock.close()
        except OSError:
            pass

    # ---- terima
    def _read(self, n):
        buf = b""
        while len(buf) < n:
            try:
                part = self.sock.recv(n - len(buf))
            except OSError:
                part = b""
            if not part:
                self.closed = True
                raise WsClosed()
            buf += part
        return buf

    def recv(self):
        """Blokir sampai satu pesan teks utuh datang. WsClosed kalau putus."""
        pesan = b""
        while True:
            b1, b2 = self._read(2)
            fin, op = b1 & 0x80, b1 & 0x0F
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._read(8))[0]
            mask = self._read(4) if b2 & 0x80 else None
            data = self._read(n) if n else b""
            if mask:
                data = bytes(c ^ mask[i % 4] for i, c in enumerate(data))
            if op == 0x8:                       # close
                self.close()
                raise WsClosed()
            if op == 0x9:                       # ping -> pong
                self._raw(struct.pack("!BB", 0x8A, len(data)) + data)
                continue
            if op == 0xA:                       # pong
                continue
            pesan += data
            if fin:
                return pesan.decode("utf-8", "replace")


def handshake(sock):
    """Baca request HTTP upgrade, balas 101. Return WsConn atau None."""
    sock.settimeout(5)
    req = b""
    while b"\r\n\r\n" not in req:
        part = sock.recv(4096)
        if not part or len(req) > 16384:
            return None
        req += part
    sock.settimeout(None)
    baris = req.decode("latin-1").split("\r\n")
    path = baris[0].split(" ")[1] if len(baris[0].split(" ")) > 1 else "/"
    hdr = {}
    for b in baris[1:]:
        if ":" in b:
            k, v = b.split(":", 1)
            hdr[k.strip().lower()] = v.strip()
    key = hdr.get("sec-websocket-key")
    if not key or "websocket" not in hdr.get("upgrade", "").lower():
        sock.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
        return None
    acc = base64.b64encode(
        hashlib.sha1((key + _GUID).encode()).digest()).decode()
    sock.sendall(("HTTP/1.1 101 Switching Protocols\r\n"
                  "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                  "Sec-WebSocket-Accept: " + acc + "\r\n\r\n").encode())
    return WsConn(sock, path)


def serve(host, port, on_conn):
    """Mulai listen. on_conn(WsConn) dipanggil di thread baru per klien.
    Return (socket_server, port_asli)."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(4)

    def loop():
        while True:
            try:
                s, _ = srv.accept()
            except OSError:
                return

            def satu(s=s):
                try:
                    c = handshake(s)
                except OSError:
                    c = None
                if c is None:
                    try:
                        s.close()
                    except OSError:
                        pass
                    return
                on_conn(c)
            threading.Thread(target=satu, daemon=True).start()

    threading.Thread(target=loop, daemon=True, name="ws-accept").start()
    return srv, srv.getsockname()[1]
