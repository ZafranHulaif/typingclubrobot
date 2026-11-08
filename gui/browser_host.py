"""Host browser debug DI DALAM jendela aplikasi (v3).

Ide: jendela browser yang biasanya melayang sendiri disematkan (embed)
ke frame Tk via SetParent Win32 - persis konsep "preview browser" di
aplikasi agent modern. Engine CDP tidak berubah sama sekali; yang
berubah hanya TEMPAT jendelanya digambar.

Alur:
  1. GUI menjalankan ensure_browser() di thread latar (sudah ada).
  2. embed_async() menunggu port debug hidup, lalu mencari HWND jendela
     browser (class Chrome_WidgetWin_1 milik proses pemegang port).
  3. Gaya jendela dibedah: titlebar + bingkai dilepas, WS_CHILD dipasang,
     SetParent ke frame Tk, lalu diresize mengikuti frame.
  4. Watcher tipis menjaga ukuran (resize jendela utama) & memulihkan
     gaya bila Chromium mengubahnya sendiri.

Saat aplikasi ditutup jendela dipisahkan lagi (SetParent NULL) supaya
browser tetap hidup mandiri seperti perilaku lama.
"""

import ctypes
import ctypes.wintypes as wintypes
import threading
import time
import tkinter as tk

GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_CLIPSIBLINGS = 0x04000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_SYSMENU = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
GA_ROOT = 2

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


def _long(hwnd, idx):
    if hasattr(user32, "GetWindowLongPtrW"):
        return user32.GetWindowLongPtrW(hwnd, idx)
    return user32.GetWindowLongW(hwnd, idx)


def _set_long(hwnd, idx, val):
    if hasattr(user32, "SetWindowLongPtrW"):
        return user32.SetWindowLongPtrW(hwnd, idx, val)
    return user32.SetWindowLongW(hwnd, idx, val)


class BrowserHost(tk.Frame):
    """Frame Tk yang menjadi 'wadah' jendela browser."""

    def __init__(self, master, on_embed=None, **kw):
        super().__init__(master, bg=kw.pop("bg", "#101116"),
                         highlightthickness=1,
                         highlightbackground=kw.pop("edge", "#2a2c33"), **kw)
        self._hwnd = None            # hwnd browser yang tertanam
        self._want = False           # masih ingin tertanam (batal saat tutup)
        self._on_embed = on_embed
        self._status_cb = None       # callback teks status thread -> GUI
        # overlay placeholder (tampil sebelum browser tertanam)
        self._overlay = tk.Frame(self, bg="#101116")
        self._overlay.pack(fill="both", expand=True)
        self.bind("<Configure>", self._on_resize)

    # ------------------------------------------------------------- API
    def set_overlay(self, widget):
        """Pasang isi placeholder (ikon status + teks)."""
        widget.pack(in_=self._overlay, expand=True)

    def set_status_cb(self, cb):
        self._status_cb = cb

    def _status(self, teks):
        if self._status_cb:
            try:
                self._status_cb(teks)
            except Exception:
                pass

    def embed_async(self, jendela, launch_fn, is_port_live):
        """Mulai urutan tanam di thread latar.

        jendela    : fungsi laporan status -> root.after (thread-safe)
        launch_fn  : fungsi pembuka browser (ensure_browser engine) - sudah
                     berjalan di thread lain bila sudah dipanggil; di sini
                     boleh None (port sudah hidup).
        is_port_live: fungsi -> bool, port debug sudah siap.
        """
        self._want = True
        threading.Thread(target=self._embed_thread,
                         args=(jendela, is_port_live),
                         daemon=True).start()

    def release(self):
        """Lepas browser kembali jadi jendela mandiri (saat aplikasi tutup)."""
        self._want = False
        hwnd, self._hwnd = self._hwnd, None
        if not hwnd or not user32.IsWindow(hwnd):
            return
        try:
            style = _long(hwnd, GWL_STYLE)
            style &= ~WS_CHILD
            style |= WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | \
                WS_MAXIMIZEBOX | WS_SYSMENU
            _set_long(hwnd, GWL_STYLE, style)
            ex = _long(hwnd, GWL_EXSTYLE)
            ex &= ~WS_EX_TOOLWINDOW
            _set_long(hwnd, GWL_EXSTYLE, ex)
            user32.SetParent(hwnd, None)
            user32.SetWindowPos(hwnd, 0, 60, 60, 1100, 760,
                                SWP_NOZORDER | SWP_FRAMECHANGED)
            user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE - perilaku lama
        except Exception:
            pass

    # ---------------------------------------------------------- thread
    def _embed_thread(self, lapor, is_port_live):
        # tunggu port debug (maks 60 dtk - launch browser lambat kadang 30+)
        for _ in range(120):
            if not self._want:
                return
            if is_port_live():
                break
            time.sleep(0.5)
        else:
            lapor("Browser tidak kunjung siap - jendela tetap terpisah.")
            return
        hwnd = self._cari_hwnd()
        for _ in range(20):
            if hwnd or not self._want:
                break
            time.sleep(0.5)
            hwnd = self._cari_hwnd()
        if not self._want:
            return
        if not hwnd:
            lapor("Jendela browser tidak ditemukan - tetap terpisah.")
            return
        self._hwnd = hwnd
        lapor("__embed__")
        self._jaga()

    def _cari_hwnd(self):
        """HWND jendela utama browser: class Chrome_WidgetWin_1, top-level,
        terlihat, milik proses yang memegang port debug."""
        try:
            from engine.browser import _port_holders
            pids = {p for p, _n in _port_holders()}
        except Exception:
            pids = set()
        if not pids:
            return None
        temuan = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum_cb(hwnd, _l):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value not in pids:
                    return True
                buf = ctypes.create_unicode_buffer(64)
                user32.GetClassNameW(hwnd, buf, 64)
                if buf.value != "Chrome_WidgetWin_1":
                    return True
                if user32.GetAncestor(hwnd, GA_ROOT) != hwnd:
                    return True
                # utamakan jendela berjudul edclub/typingclub; kumpulkan semua
                judul = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(hwnd, judul, 256)
                temuan.append((hwnd, judul.value.lower()))
            except Exception:
                pass
            return True

        user32.EnumWindows(enum_cb, 0)
        if not temuan:
            return None
        for h, j in temuan:
            if "edclub" in j or "typingclub" in j:
                return h
        return temuan[0][0]

    def plant(self):
        """Bedah gaya + SetParent + pas ukuran. Dipanggil di thread UI."""
        """Bedah gaya + SetParent + pas ukuran. Dipanggil di thread UI."""
        hwnd = self._hwnd
        if not hwnd or not self._want or not user32.IsWindow(hwnd):
            return
        try:
            style = _long(hwnd, GWL_STYLE)
            style &= ~(WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX |
                       WS_MAXIMIZEBOX | WS_SYSMENU)
            style |= WS_CHILD | WS_VISIBLE | WS_CLIPSIBLINGS
            _set_long(hwnd, GWL_STYLE, style)
            ex = _long(hwnd, GWL_EXSTYLE)
            ex |= WS_EX_TOOLWINDOW   # hilang dari taskbar (jendela utama yg wakili)
            _set_long(hwnd, GWL_EXSTYLE, ex)
            user32.SetParent(hwnd, self.winfo_id())
            self._pas_ukuran()
            self._overlay.pack_forget()
            if self._on_embed:
                self._on_embed()
        except Exception:
            self._hwnd = None

    def _pas_ukuran(self):
        hwnd = self._hwnd
        if not hwnd or not user32.IsWindow(hwnd):
            return
        try:
            user32.SetWindowPos(hwnd, 0, 0, 0, max(self.winfo_width(), 50),
                                max(self.winfo_height(), 50),
                                SWP_NOZORDER | SWP_NOACTIVATE)
        except Exception:
            pass

    def _on_resize(self, _ev=None):
        if self._hwnd:
            self.after_idle(self._pas_ukuran)

    def _jaga(self):
        """Loop penjaga: 4x/dtk cek gaya & ukuran masih benar (Chromium
        kadang menata ulang dirinya; balikin senyap-senyap)."""
        target = self.winfo_id()

        def jaga():
            if not self._want or not self._hwnd:
                return
            hwnd = self._hwnd
            if not user32.IsWindow(hwnd):
                return
            try:
                if user32.GetParent(hwnd) != target:
                    # lepas-lepas sendiri? tanam ulang
                    user32.SetParent(hwnd, target)
                    self.plant()
                style = _long(hwnd, GWL_STYLE)
                if not style & WS_CHILD:
                    style |= WS_CHILD | WS_VISIBLE | WS_CLIPSIBLINGS
                    style &= ~(WS_CAPTION | WS_THICKFRAME)
                    _set_long(hwnd, GWL_STYLE, style)
                    user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                                        SWP_NOZORDER | SWP_NOACTIVATE |
                                        SWP_FRAMECHANGED)
                w = self.winfo_width()
                h = self.winfo_height()
                if w > 1 and (user32.IsZoomed(hwnd) or user32.IsIconic(hwnd)):
                    user32.ShowWindow(hwnd, 8)  # SW_SHOWNA
                    self._pas_ukuran()
            except Exception:
                pass
            self.after(250, jaga)

        self.after(250, jaga)
