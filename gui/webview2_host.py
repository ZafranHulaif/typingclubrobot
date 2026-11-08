"""Host WebView2 chromeless di dalam jendela app (v3.2).

Ganti total dari trik SetParent-jendela-browser (v3.0/3.1): sekarang
browser engine-nya sendiri (WebView2, bawaan Windows 10/11) ditanam
sebagai permukaan TANPA UI apa pun - seperti preview browser di app
agent modern. Yang tampak hanya halaman webnya.

Alur:
  - tersedia(): cek pythonnet + pywebview + runtime WebView2 ada.
  - Entry point menjalankan seluruh Tk di CLR thread STA (syarat
    WebView2 - pola yang sama dipakai tkwebview2).
  - buka(port, url): membuat EdgeChrome (pywebview) dengan folder
    profil dedikasi TypingBot, menempel (SetParent) ke frame Tk, dan
    menyalakan remote debugging di port itu.
  - Engine Playwright connect_over_cdp ke port yang sama - engine
    tidak berubah; BROWSER_WV2 membuat ensure_browser melewati semua
    peluncuran browser eksternal.
"""

import ctypes
import ctypes.wintypes as wintypes
import os
import tkinter as tk

user32 = ctypes.windll.user32
GWL_STYLE = -16
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020


def tersedia():
    """Runtime lengkap ada? Import berat dilakukan di sini (lambat),
    BUKAN saat modul dimuat - supaya test suite & mesin tanpa WebView2
    tetap aman memakai jalur browser eksternal lama."""
    try:
        import clr
        try:
            from System.Threading import Thread as _T
            print(f"[WEBVIEW2] thread UI: "
                  f"{_T.CurrentThread.GetApartmentState()}")
        except Exception:
            pass
        try:
            # build beku (PyInstaller): probing GAC tidak sama seperti dev -
            # muat eksplisit per strong name supaya namespace terlihat
            from System.Reflection import Assembly
            for _nm in ("System.Windows.Forms, Version=4.0.0.0, "
                        "Culture=neutral, PublicKeyToken=b77a5c561934e089",
                        "System.Drawing, Version=4.0.0.0, "
                        "Culture=neutral, PublicKeyToken=b03f5f7f11d50a3a"):
                try:
                    Assembly.Load(_nm)
                except Exception:
                    pass
            clr.AddReference("System.Windows.Forms")
            clr.AddReference("System.Drawing")
        except Exception:
            pass
        from System.Windows.Forms import Control  # noqa: F401
        from webview.platforms.edgechromium import EdgeChrome  # noqa: F401
        return True
    except Exception as ex:
        print(f"[WEBVIEW2] tidak tersedia ({str(ex)[:80]}) - pakai "
              "browser eksternal.")
        return False


def jalankan_sta(main_fn):
    """Jalankan main_fn (seluruh app Tk) di CLR thread STA.

    Dipanggil dari entry point. Kalau pythonnet tidak ada (build lama /
    lingkungan tanpa dependensi), main_fn jalan di thread utama seperti
    biasa - jalur WebView2 memang dinonaktifkan."""
    try:
        from System.Threading import Thread, ThreadStart, ApartmentState
    except Exception as ex:
        try:
            from .theme import LOG_FILE
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[WEBVIEW2] STA tidak tersedia: {str(ex)[:120]}\n")
        except Exception:
            pass
        main_fn()
        return
    t = Thread(ThreadStart(main_fn))
    t.ApartmentState = ApartmentState.STA
    t.Start()
    t.Join()


class Wv2Host(tk.Frame):
    """Frame Tk yang menjadi permukaan halaman web (WebView2)."""

    def __init__(self, master, profil_dir, bg="#101116", edge="#2a2c33",
                 **kw):
        super().__init__(master, bg=bg, highlightthickness=1,
                         highlightbackground=edge, **kw)
        self._profil = profil_dir
        self._ec = None          # EdgeChrome (pywebview)
        self._chwnd = None       # hwnd kontrol WinForms
        self._on_ready = None
        self._jaga_job = None
        self._popup_unsub = False
        self._blank_ct = {}     # popup about:blank -> hitung siklus utk WM_CLOSE
        # overlay placeholder (tampil sebelum halaman siap)
        self._overlay = tk.Frame(self, bg=bg)
        self._overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.bind("<Configure>", self._on_resize)

    # ------------------------------------------------------------- API
    def set_overlay(self, widget):
        widget.place(in_=self._overlay, relx=0.5, rely=0.5, anchor="center")

    def set_on_ready(self, cb):
        self._on_ready = cb

    def buka(self, port, url, warna="#141519"):
        """Buat WebView2 dengan port debug + navigasi ke url.
        HARUS dipanggil di thread UI (CLR STA) setelah jendela tampil."""
        try:
            import webview
            # popup/target=_blank (OAuth Google dkk): jangan buka di browser
            # OS - navigasi halaman utama saja (tetap di dalam app, tanpa
            # jendela melayang; alur redirect OAuth tetap selesai di sini)
            try:
                webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = False
            except Exception:
                pass
            from webview.platforms.edgechromium import EdgeChrome
            from webview.window import Window
            from System.Windows.Forms import Control
            webview.settings["REMOTE_DEBUGGING_PORT"] = port
            control = Control()
            window = Window(
                "typingbot", "1", url=None, html=None, js_api=None,
                width=max(self.winfo_width(), 400),
                height=max(self.winfo_height(), 300), x=None, y=None,
                resizable=True, fullscreen=False, min_size=(200, 100),
                hidden=False, frameless=False, easy_drag=True,
                minimized=False, on_top=False, confirm_close=False,
                background_color=warna, transparent=False,
                text_select=True, localization=None, zoomable=True,
                draggable=True, vibrancy=False)
            os.makedirs(self._profil, exist_ok=True)
            ec = EdgeChrome(control, window, self._profil)
            self._ec = ec
            self._chwnd = int(str(control.Handle))
            user32.SetParent(self._chwnd, self.winfo_id())
            self._pas_ukuran()
            self._overlay.place_forget()
            # PENTING (stabilitas): lepas SEMUA handler event pywebview.
            # Handler itu callback Python dari thread .NET - kombinasi dgn
            # mainloop Tk memicu crash GIL (PyEval_RestoreThread) saat init
            # webview selesai. Interaksi .NET hanya lewat polling dari
            # thread Tk (lihat _jaga) - tanpa callback balik sama sekali.
            wv = ec.webview
            for ev_name, fn in (("CoreWebView2InitializationCompleted",
                                 "on_webview_ready"),
                                ("NavigationStarting", "on_navigation_start"),
                                ("NavigationCompleted",
                                 "on_navigation_completed"),
                                ("WebMessageReceived", "on_script_notify")):
                try:
                    getattr(wv, ev_name).__isub__(getattr(ec, fn))
                except Exception:
                    pass
            # popup (Google/Clever OAuth): handler popup pywebview akan
            # dicabut di _jaga begitu CoreWebView2 siap - popup WebView2
            # asli lalu kita adopsi ke dalam app
            ec.load_url(url)
            self._jaga()
            return True
        except Exception as ex:
            print(f"[WEBVIEW2] gagal dibuat ({str(ex)[:100]}) - pakai "
                  "browser eksternal.")
            self._ec = None
            return False

    def _core_ready(self, sender, _args):
        """TIDAK DIPAKAI: callback .NET -> Python dari thread asing
        memicu crash GIL. Penanganan init dilakukan lewat polling _jaga."""

    def _jaga(self):
        """Polling dari thread Tk (tanpa callback .NET -> Python):
        1. begitu CoreWebView2 ada: cabut handler popup pywebview (yang
           membuka link di browser OS / menimpa halaman utama - penyebab
           dialog 'Get an app to open this link' saat login Google).
        2. adopsi jendela popup WebView2 (OAuth dll): jendela milik proses
           webview kita yang ber-owner ke kontrol utama -> jadi CHILD
           frame ini, penuh memenuhi area. Popup menutup dirinya sendiri
           saat OAuth selesai (relasi opener tetap utuh)."""
        GW_OWNER = 4
        if self._ec and not self._popup_unsub:
            try:
                core = self._ec.webview.CoreWebView2
                if core is not None:
                    core.NewWindowRequested -= self._ec.on_new_window_request
                    self._popup_unsub = True
            except Exception:
                pass
        temuan = []
        chwnd = self._chwnd

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum_cb(hwnd, _l):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                if user32.GetWindow(hwnd, GW_OWNER) != chwnd:
                    return True
                buf = ctypes.create_unicode_buffer(64)
                user32.GetClassNameW(hwnd, buf, 64)
                if buf.value != "Chrome_WidgetWin_1":
                    return True
                temuan.append(hwnd)
            except Exception:
                pass
            return True

        user32.EnumWindows(enum_cb, 0)
        for hwnd in temuan:
            try:
                judul = ctypes.create_unicode_buffer(128)
                user32.GetWindowTextW(hwnd, judul, 128)
                if judul.value.strip().lower() in ("about:blank", ""):
                    # popup kosong sisa alur lama -> tutup, jangan numpuk
                    self._blank_ct[hwnd] = self._blank_ct.get(hwnd, 0) + 1
                    if self._blank_ct[hwnd] >= 4:
                        user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
                        self._blank_ct.pop(hwnd, None)
                    continue
                self._blank_ct.pop(hwnd, None)
                style = user32.GetWindowLongW(hwnd, GWL_STYLE)
                style &= ~(WS_CAPTION | WS_THICKFRAME)
                style |= WS_CHILD | WS_VISIBLE
                user32.SetWindowLongW(hwnd, GWL_STYLE, style)
                user32.SetParent(hwnd, self.winfo_id())
                user32.SetWindowPos(hwnd, 0, 0, 0,
                                    max(self.winfo_width(), 50),
                                    max(self.winfo_height(), 50),
                                    SWP_NOZORDER | SWP_NOACTIVATE |
                                    SWP_FRAMECHANGED)
            except Exception:
                pass
        if self._ec:
            self._jaga_job = self.after(400, self._jaga)

    def release(self):
        """Lepas WebView2 saat app ditutup (browser process ikut mati -
        profil dedikasi tetap tersimpan utk login berikutnya)."""
        ec, self._ec = self._ec, None
        if ec is None:
            return
        try:
            wv = getattr(ec, "webview", None)
            if wv is not None:
                wv.Dispose()
        except Exception:
            pass

    # ---------------------------------------------------------- internal
    def _pas_ukuran(self):
        if not self._chwnd:
            return
        try:
            user32.MoveWindow(self._chwnd, 0, 0,
                              max(self.winfo_width(), 50),
                              max(self.winfo_height(), 50), True)
        except Exception:
            pass

    def _on_resize(self, _ev=None):
        self.after_idle(self._pas_ukuran)
