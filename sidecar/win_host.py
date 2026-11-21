"""Host WebView2 di proses sidecar (Windows saja).

Trik utamanya: gui/webview2_host.Wv2Host dipakai APA ADANYA, di dalam
jendela Tk tanpa bingkai (Toplevel overrideredirect). HWND jendela itu
= "wadah" (container, lihat M0 §3). UI Flutter menerima HWND-nya lewat
snapshot web.hwnd lalu runner C++ meng-SetParent wadah itu ke jendela
Flutter dan mengatur posisi/ukurannya. Semua mesin cover/OAuth/akun di
Wv2Host tetap berjalan tanpa diubah - dia tidak tahu dirinya dipindah.

Aturan GIL: semua kerja Tk/.NET di thread STA milik Tk. Thread lain
(IPC, engine) cuma menaruh fungsi di antrean; Tk mengurasnya tiap 40 ms.
"""
import ctypes
import os
import queue
import threading
import time

COURSE_URL = "https://www.edclub.com/student/course/3"
SIGNIN_URL = "https://www.edclub.com/signin"
SW_HIDE, SW_SHOW = 0, 5


def set_dpi_aware():
    """Per-monitor v2 SEBELUM jendela apa pun dibuat (M0 §3)."""
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass


class WinHost:
    def __init__(self, on_hwnd=None, log=print):
        self._q = queue.Queue()
        self._on_hwnd = on_hwnd          # dipanggil (hwnd) saat wadah siap
        self._log = log
        self._root = None
        self._top = None
        self.host = None                 # Wv2Host
        self.hwnd = 0
        self.ready = threading.Event()

    # ------------------------------------------------------------ API
    # (dipanggil dari thread mana pun - semuanya cuma mengantre)
    def start(self):
        threading.Thread(target=self._sta_main, daemon=True,
                         name="wv2-sta").start()

    def navigate(self, url):
        self._q.put(lambda: self.host and self.host.ke_url(url))

    def set_visible(self, on):
        def kerja():
            if self.hwnd:
                ctypes.windll.user32.ShowWindowAsync(
                    self.hwnd, SW_SHOW if on else SW_HIDE)
        self._q.put(kerja)

    def switch_account(self, name, selesai=None):
        def hasil(ok, pesan, folder=None, url=None):
            # callback ini datang dari thread lain -> balik ke antrean Tk
            def lanjut():
                if ok:
                    u = url or COURSE_URL
                    if folder:
                        self.host.ganti_profil(folder, u, name)
                    else:
                        self.host.ke_url(COURSE_URL)
                else:
                    self._log(f"[AKUN] gagal memuat {name}: {pesan}")
                if selesai:
                    selesai()
            self._q.put(lanjut)
        self._q.put(lambda: self.host.akun_ganti(name, hasil))

    def add_account(self, selesai=None):
        self.logout(selesai)

    def logout(self, selesai=None):
        def hasil(ok, pesan):
            def lanjut():
                self.host.ke_url(SIGNIN_URL)
                if selesai:
                    selesai()
            self._q.put(lanjut)
        self._q.put(lambda: self.host.akun_keluar(hasil))

    def shutdown(self):
        def kerja():
            try:
                if self.host:
                    self.host.release()
            finally:
                self._root.quit()
        self._q.put(kerja)

    # ------------------------------------------------------------ STA
    def _sta_main(self):
        from gui.webview2_host import jalankan_sta
        jalankan_sta(self._tk_main)

    def _tk_main(self):
        import tkinter as tk
        import paths
        from engine import state as estate
        from engine.browser import (bersihkan_browser_embed,
                                    _port_bind_free)
        from gui.webview2_host import Wv2Host, tersedia

        if not tersedia():
            self._log("[WEBVIEW2] tidak tersedia di PC ini.")
            return
        root = tk.Tk()
        root.withdraw()                      # akar tak terlihat: pompa saja
        self._root = root
        top = tk.Toplevel(root, bg="#0B0C10")
        top.overrideredirect(True)           # tanpa bingkai = WS_POPUP
        # lahir di luar layar sampai runner Flutter mengadopsinya
        top.geometry("1100x760+-32000+-32000")
        self._top = top
        host = Wv2Host(top, paths.data_path("wv2profile"),
                       bg="#0B0C10", edge="#0B0C10")
        host.pack(fill="both", expand=True)
        self.host = host

        estate.EMBED_BROWSER = True
        bersihkan_browser_embed()
        port = estate.DEBUG_PORT
        if not _port_bind_free(port):
            for k in range(9223, 9323):
                if _port_bind_free(k):
                    port = k
                    break
        estate.DEBUG_PORT = port

        def buat():
            top.update_idletasks()
            # HWND luar Toplevel (bukan frame dalam winfo_id)
            self.hwnd = int(top.wm_frame(), 16)
            ok = host.buka(port, COURSE_URL, warna="#0B0C10")
            if ok:
                estate.BROWSER_WV2 = True
                host.mulai_pengawas(port)
                self._log(f"WebView2 siap di wadah (port debug {port}).")
            else:
                self._log("[WEBVIEW2] gagal dibuat.")
            self.ready.set()
            if self._on_hwnd:
                try:
                    self._on_hwnd(self.hwnd)
                except Exception:
                    pass

        def kuras():
            for _ in range(50):
                try:
                    fn = self._q.get_nowait()
                except queue.Empty:
                    break
                try:
                    fn()
                except Exception as e:
                    self._log(f"[WINHOST] {str(e)[:150]}")
            root.after(40, kuras)

        root.after(50, buat)
        root.after(40, kuras)
        root.mainloop()
