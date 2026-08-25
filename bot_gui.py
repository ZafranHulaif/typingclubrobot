"""Fasade kompatibilitas: seluruh isi pindah ke paket gui/.
Impor lama (import bot_gui) tetap bekerja tanpa perubahan."""

from gui.theme import (  # noqa: F401
    ACCENT,
    APP_VERSION,
    BASE_DIR,
    BG,
    BROWSER_WARNA,
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
    PEMBUAT,
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
    _buat_kunci,
    _data_mesin,
    _kode_mesin,
    _lisensi_tersimpan,
    _lisensi_valid,
    _norm,
    _simpan_lisensi,
)
from gui.icons import (  # noqa: F401
    _BITMAP,
    _BMIH,
    _ICONINFO,
    _bilinear_rgb,
    _gambar_vektor_ikon,
    _ikon_png,
    _ikon_widget,
    _png_rgb,
    _skala_tkimg,
    gdi32,
    shell32,
    user32,
)
from gui.widgets import (  # noqa: F401
    Dropdown,
    _Dialog,
)
from gui.translator import (  # noqa: F401
    _AKTIV_MAP,
    _NAMA_BAIK,
    _nama_tampil,
    _teks_ramah,
)
from gui.dialogs import (  # noqa: F401
    _fokus_jendela_browser,
    dialog_aktivasi,
    dialog_buka_browser,
    dialog_pilih_browser,
    dialog_pilih_profil,
    dialog_rentang,
    dialog_selesai,
    dialog_tips,
    dialog_tutup_paksa,
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
