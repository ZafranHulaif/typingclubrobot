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
    dialog_activation,
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
    import tkinter as tk
    from gui import app as gui_app
    root = tk.Tk()
    gui_app.App(root)
    root.mainloop()
