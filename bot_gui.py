"""Fasade kompatibilitas: seluruh isi pindah ke paket gui/.
Impor lama (import bot_gui) tetap bekerja tanpa perubahan."""

from gui.theme import (  # noqa: F401
    ACCENT,
    APP_VERSION,
    BASE_DIR,
    BG,
    BROWSER_COLORS,
    BTN_FG,
    CARD,
    CARD_HOVER,
    DIM,
    EDGE,
    FAINT,
    FG,
    GREEN,
    LICENSE_FILE,
    LOG_FILE,
    ORANGE,
    PANEL,
    CREATOR,
    PROGRAM_PATH,
    RED,
    SETTINGS_FILE,
    ScrolledText,
    YELLOW,
    _build_stamp,
    base64,
    ctypes,
    hashlib,
    hmac,
    json,
    os,
    queue,
    re,
    socket,
    sys,
    threading,
    time,
    tk,
    ttk,
    uuid,
    wintypes,
    zlib,
)
from gui.licensing import (  # noqa: F401
    LICENSE_SECRET,
    _make_key,
    _machine_data,
    _machine_code,
    _saved_license,
    _license_valid,
    _norm,
    _save_license,
)
from gui.icons import (  # noqa: F401
    _BITMAP,
    _BMIH,
    _ICONINFO,
    _bilinear_rgb,
    _draw_vector_icon,
    _icon_png,
    _icon_widget,
    _png_rgb,
    _scale_tkimg,
    gdi32,
    shell32,
    user32,
)
from gui.widgets import (  # noqa: F401
    Dropdown,
    _Dialog,
)
from gui.translator import (  # noqa: F401
    _ACTIVITY_MAP,
    _NICE_NAMES,
    _display_name,
    _friendly_text,
)
from gui.dialogs import (  # noqa: F401
    _focus_browser_window,
    dialog_online_activation,
    dialog_open_browser,
    dialog_pick_browser,
    dialog_pick_profile,
    dialog_range,
    dialog_done,
    dialog_tips,
    dialog_force_close,
)
from gui.app import (  # noqa: F401
    ActivityMixin,
    App,
    DevMixin,
    LaunchMixin,
)


if __name__ == "__main__":
    # DPI awareness wajib sebelum Tk dibuat (layar 125%/150%).
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    # pembaruan yang user tunda kemarin: tukar exe SEBELUM GUI muncul
    # (script menunggu aplikasi keluar lalu menjalankan versi baru)
    import sys as _sys
    if getattr(_sys, "frozen", False):
        from net import updater as _netupd
        if _netupd.pop_pending(_sys.executable):
            raise SystemExit(0)
    import tkinter as tk
    from gui import app as gui_app
    root = tk.Tk()

    # error callback Tk & crash tak tertangani -> bot.log. Dulu error
    # di callback hanya memunculkan popup yang hilang begitu ditutup;
    # mustahil didiagnosis dari log.
    import traceback as _tb
    from gui.theme import LOG_FILE as _LOG_FILE

    def _catat_error(_jns, nilai, tb):
        try:
            with open(_LOG_FILE, "a", encoding="utf-8") as f:
                f.write("[GUI] error tak tertangani: %r\n%s\n" % (
                    nilai, "".join(_tb.format_exception(type(nilai),
                                                        nilai, tb))))
        except Exception:
            pass

    root.report_callback_exception = _catat_error
    _sys.excepthook = _catat_error

    gui_app.App(root)

    def _angkat():
        # angkat jendela ke depan + fokus - penting saat aplikasi
        # diluncurkan ulang otomatis usai pembaruan (instance baru
        # tadinya muncul di belakang, tidak aktif)
        try:
            root.attributes("-topmost", True)
            root.lift()
            root.focus_force()
            root.after(150, lambda: root.attributes("-topmost", False))
        except Exception:
            pass

    root.after(400, _angkat)
    root.mainloop()
