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
import os
import tkinter as tk

user32 = ctypes.windll.user32


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
            ec.load_url(url)
            return True
        except Exception as ex:
            print(f"[WEBVIEW2] gagal dibuat ({str(ex)[:100]}) - pakai "
                  "browser eksternal.")
            self._ec = None
            return False

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
