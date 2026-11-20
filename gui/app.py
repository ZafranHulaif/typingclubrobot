"""Jendela utama (mixin activity/launch/dev) + entry point."""

import base64
import ctypes
import hashlib
import hmac
import json
import os
import queue
import re
import socket
import sys
import threading
import time
import tkinter as tk
import uuid
import zlib
from ctypes import wintypes
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from .licensing import _machine_code, _license_valid
from . import anim
import paths
from .theme import (APP_VERSION, ACCENT, BG, BTN_FG, CARD, CARD_HOVER, DIM, EDGE, FAINT, FG, GREEN, GREEN_HOVER, PANEL, CREATOR, RED, RED_DIM, SETTINGS_FILE, YELLOW, YELLOW_DIM, _asset_path, _build_stamp)
from .widgets import (Dropdown, SpeedDial, _gelap_titlebar,
                      set_dialog_layer)
from .webview2_host import Wv2Host, tersedia as wv2_tersedia, jalankan_sta


from .activity import ActivityMixin
from .dev import DevMixin
from .launch import LaunchMixin


class App(ActivityMixin, LaunchMixin, DevMixin):
    """Jendela utama TypingBot."""

    def __init__(self, root):
        self.root = root
        self.bot = None
        self.bot_thread = None
        self.log_q = queue.Queue()
        self._ui_queue = queue.Queue()
        self.log_file = None
        self._detected = []          # [(nama, path)] browser terpasang
        self._first_run = not os.path.exists(SETTINGS_FILE)
        self._login_win = None       # popup 'login dulu' (aktif saat sesi mati)
        self._login_dismiss = False  # user menutup popup login manual
        self._login_ever = False     # popup login sudah muncul di episode ini
        self._tanya_win = None       # popup 'bot menunggu, lanjut/stop?'
        self._selesai_info = False   # popup 'rentang selesai' sudah tampil
        self._terkunci_win = None    # popup 'level start terkunci'
        self._tanya_rentang = True   # tanya rentang level saat Start berikutnya
        self._rentang_terbuka = False   # dialog rentang sedang tampil (state label)
        self._tunggu_pilih_halaman = False  # user memilih level awal di browser
        self._login_grace = 0        # jeda re-popup login setelah tombol buka login
        self._fokus_sambung = False  # app diangkat ke depan 1x setelah bot tersambung
        self._fokus_browser_at = 0.0 # FOCUS_BROWSER_AT engine terakhir yang ditanggapi
        self._fokus_setup = False    # fokus browser 1x saat perlu set-up first-run
        self._fokus_pilih = False    # fokus browser 1x saat alur pilih-level-sendiri
        self._rentang_jawab = 0.0    # waktu user selesai memilih rentang (grace state)
        self._embed_aktif = False    # browser sudah tertanam di app (v3)
        self._profile = "bot"        # 'bot' khusus | 'saya' profil browser user
        self._profile_dir = ""       # 'Default' / 'Profile 1' ... (mode saya)
        self._profile_label = ""     # nama tampilan profil (mis. 'Student')
        self._nick_q = queue.Queue()   # nickname dari dialog online -> thread net
        self._tok_cache = None         # token lisensi online terakhir (net)
        self._update_info = None       # info rilis baru (thread net)
        self._updating = False         # sedang mengunduh pembaruan
        self._online_cancel = False    # user menutup dialog aktivasi online
        self._online_dlg = None        # dialog aktivasi online aktif
        self._update_btn = None        # tombol perbarui (muncul bila ada rilis)
        self._update_ready = False     # unduhan sah menunggu dipasang saat mulai
        self.lisensi_ok = _license_valid()

        root.title("TypingBot")
        # ukuran jendela mengikuti DPI layar (dipanggil setelah
        # SetProcessDpiAwareness di __main__; skrip/uji tanpa itu = 1.0)
        try:
            k = float(root.tk.call("tk", "scaling")) / (96.0 / 72.0)
        except Exception:
            k = 1.0
        k = max(1.0, min(k, 2.0))
        # KUNCI ke layar: dulu jendela bisa lebih LEBAR dari layar
        # (resolusi berubah/di-remote) = tombol akun di kanan atas
        # JADI DI LUAR LAYAR = 'tidak bisa klik akun mana pun'
        # (misteri live 19 Nov: layar berubah 1920 -> 1280)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        lebar = max(400, min(int(780 * k), sw - 16))
        tinggi = max(300, min(int(460 * k), sh - 60))
        root.geometry(f"{lebar}x{tinggi}+0+0")
        # tinggi minimum kecil: pengguna boleh mengecilkan jendela sampai
        # kecil - footer hotkey tetap tampak, hanya log yang menyusut
        root.minsize(max(400, min(int(700 * k), sw - 16)),
                     max(280, min(int(330 * k), sh - 60)))
        root.configure(bg=BG)
        # ikon jendela: iconbitmap = jalur asli Windows (paling andal;
        # iconphoto di beberapa build Tk malah tidak tampil sama sekali)
        ico = _asset_path("logo.ico")
        if ico:
            try:
                root.iconbitmap(default=ico)
            except Exception:
                pass
        logo = _asset_path("logo.png")
        if logo:
            try:
                self._logo_img = tk.PhotoImage(file=logo)
            except Exception:
                self._logo_img = None
        # title bar gelap ala Windows 11 - harus SETELAH jendela benar2
        # wujud (120ms sempat terlalu cepat -> hwnd belum siap, bar tetap
        # putih; 300ms + ulang 1200ms = aman). DITAMBAH: aplikasi ulang
        # pelan selamanya - atribut DWM ternyata di-RESET di tengah sesi
        # (live: bar putih lagi setelah popup OAuth dibuat WebView2;
        # panggilan ulang balikin gelap dalam 1x polling, murah).
        root.after(300, lambda: _gelap_titlebar(root))
        root.after(1200, lambda: _gelap_titlebar(root))

        def _ulang_gelap():
            _gelap_titlebar(root)
            root.after(3000, _ulang_gelap)

        root.after(2500, _ulang_gelap)
        self._title_bar()

        # peluncuran senyap (build/test agent): jangan naik ke depan -
        # user tidak kena 'flash bang' tiap versi baru diuji
        if os.environ.get("TYPINGBOT_SENYAP") != "1":
            try:
                root.attributes("-topmost", True)
                root.attributes("-topmost", False)
            except Exception:
                pass
        # ---------- zona atas: header status, baris tombol (+ kartu browser
        # ---------- persegi DI samping Stop), lalu baris kecepatan ----------
        self._last_browser_path = ""   # exe terakhir yang dipakai mode Otomatis
        # browser_var wajib dibuat sebelum chip (chip membacanya saat render)
        self.browser_var = tk.StringVar(value="Otomatis")
        self.browser_dd = type(
            "_NoDD", (), {"set_values": lambda self, v: None,
                          "configure": lambda self, **kw: None})()

        head = tk.Frame(root, bg=BG)
        head.pack(fill="x", padx=18, pady=(16, 2))
        self.state_lbl = tk.Label(head, text="⏻ Siap", font=("Segoe UI", 15, "bold"),
                                  fg=FG, bg=BG)
        self.state_lbl.pack(side="left")
        self.ver_lbl = tk.Label(head,
                                text=f"v{APP_VERSION}  •  oleh {CREATOR}  •  "
                                     f"build {_build_stamp()}",
                                font=("Segoe UI", 9), fg=FAINT, bg=BG)
        self.ver_lbl.pack(side="right", pady=(6, 0))
        # Akses jendela Dev (hanya untuk pemilik): klik teks versi 5x cepat
        # atau Ctrl+Shift+D. Tidak ada tombol terlihat.
        self._dev_klik = []
        self.ver_lbl.bind("<Button-1>", self._dev_gesture)
        root.bind("<Control-Shift-D>", lambda e: self._safe(self.on_dev))

        ctrl = tk.Frame(root, bg=BG)
        ctrl.pack(fill="x", padx=18, pady=(8, 2))
        # gaya tombol ala dashboard gelap modern: SATU aksi utama terisi
        # (Start hijau), aksi sekunder ghost dgn tint semantik tipis -
        # dulu tiga tombol terisi hijau/kuning/merang menyala berdampingan
        # (keluhan user: 'looks so bad').
        # SEMUA kontrol header = tinggi seragam 56px (frame pembatas +
        # pack_propagate False) - dulu chip wpm offset ke atas & tombol
        # 🪲 lebih pendek dr tombol lain (keluhan user 19 Nov)
        self._header_h = 56

        def _kot(induk, lebar=0):
            kot = tk.Frame(induk, bg=BG, height=self._header_h,
                           highlightthickness=0)
            if lebar:
                kot.configure(width=lebar)
            kot.pack_propagate(False)
            kot.pack(side="left", padx=(0, 10))
            return kot

        # PENTING: tombol = ANAK KANDUNG kot-nya (dulu _btn(ctrl) lalu
        # pack(in_=kot): geometri pindah tapi parent tetap ctrl, kot
        # (dibuat belakangan) menutupi tombol dgn latar solid = tombol
        # 'hilang' padahal ada di bawahnya - live 21 Nov dev5)
        kot_start = _kot(ctrl, 150)
        self.btn_start = self._btn(kot_start, "▶  Start", GREEN,
                                   self.on_start, besar=True, gaya="isi")
        # padx=0 eksplisit: pack() Tk MEMPERTAHANKAN opsi lama (padx
        # (0,8) dr _btn) - tanpa ini tombol 142px = sisa gelap 8px di
        # kanan kot = kesan gap Start-Stop lebih lebar (user 21 Nov)
        self.btn_start.pack(fill="both", expand=True, padx=0, pady=0)
        kot_stop = _kot(ctrl, 150)
        self.btn_stop = self._btn(kot_stop, "⏹  Stop", RED, self.on_stop,
                                  besar=True, gaya="hantu")
        self.btn_stop["state"] = "disabled"
        self._style_btn(self.btn_stop)
        self.btn_stop.pack(fill="both", expand=True, padx=0, pady=0)

        self.kanan = tk.Frame(ctrl, bg=BG, width=560,
                              height=self._header_h)
        self.kanan.pack_propagate(False)
        self.kanan.pack(side="right")
        # 🪲 Lapor bug: chip DI SAMPING tombol akun (keluhan user 19
        # Nov: 'why is it even inside that pop up' - keluar dari popover)
        self.btn_bug = tk.Label(self.kanan, text="🪲", fg=ACCENT, bg=PANEL,
                                font=("Segoe UI", 11), padx=10, pady=10,
                                cursor="hand2", highlightthickness=1,
                                highlightbackground=EDGE)
        self.btn_bug.pack(side="left", fill="both",
                           expand=True, padx=(0, 8))
        self.btn_bug.bind("<Enter>", lambda e: self.btn_bug.configure(
            fg="#e8eaf0", bg=CARD_HOVER))
        self.btn_bug.bind("<Leave>", lambda e: self.btn_bug.configure(
            fg=ACCENT, bg=PANEL))
        self.btn_bug.bind("<Button-1>",
                          lambda e: self._safe(self._lapor_bug))
        # 👤 Akun: manajer sesi edclub - ganti/tambah/hapus akun
        # (permintaan user 11 Nov 2026). Butuh CDP webview utk tukar
        # cookie -> nonaktif sampai WebView2 siap (lihat boot).
        self.btn_akun = self._btn(self.kanan, "👤 Akun", ACCENT,
                                  self.on_akun, kecil=True, gaya="hantu")
        # LEBAR TETAP (keluhan user 15 Nov: 'the length of the button
        # keeps changing' - label berganti Akun/Login/nama = tombol
        # melar-mengecil = header & popover ikut geser). Teks dipusat.
        try:
            self.btn_akun.configure(width=16, anchor="center")
        except Exception:
            pass
        self.btn_akun.pack_configure(fill="both", expand=True)
        self.btn_akun["state"] = "disabled"
        self._akun_perlu_login = None
        # v3.2: tombol Pulihkan & ❓ DIHAPUS (permintaan user) - Pulihkan
        # warisan mode browser eksternal (supervisor + pengawas dalam-app
        # kini memulihkan otomatis), tips ❓ masih menjelaskan alur lama.
        # Fungsinya (on_recovery/on_tips) dibiarkan utk dev/tests.

        # ---------- grup kecepatan: SEBARIS dengan tombol ----------
        # (v3.2 permintaan user: makin sedikit baris kontrol = makin tinggi
        # ruang halaman web di bawah. Caption kecil + slider + readout.)
        grp = tk.Frame(ctrl, bg=BG)
        grp.pack(side="left", padx=(30, 0))   # jarak dari tombol aksi
        # Slider HALUS: drag = nilai wpm mengalir live ke engine (permintaan
        # user: snap instan terasa kasar - biar mengalir dulu, lepas baru
        # spring ke tick terdekat dengan bounce kecil). Tangga 85-300 wpm:
        # dulu di-cap 200 karena situs LAMA blank di atasnya - kini aman
        # di UI baru, recovery reload menutup kasus blank.
        self.SPEED_TIERS = (40, 85, 140, 200, 225, 250, 275, 300, 400)
        self._speed_wpm = 400   # default tercepat (permintaan user)
        _spd = ""
        try:
            _spd = str(json.load(open(SETTINGS_FILE,
                                      encoding="utf-8")).get("speed", ""))
        except Exception:
            pass
        _m = re.search(r"(\d+)", _spd)
        if _m:
            self._speed_wpm = max(40, min(400, int(_m.group(1))))
        tier_ui = [(str(w), w) for w in self.SPEED_TIERS]
        # v3.2: chip ringkas - klik membuka DIAL bulat (ref visual user:
        # 'pod' bulat dgn titik tier + arc merah muda + thumb glow). Baris
        # kontrol tetap satu baris & ramping.
        self._dial = None            # popup SpeedDial aktif (None = tutup)
        kot_wpm = tk.Frame(grp, bg=BG, width=200,
                           height=self._header_h,
                           highlightthickness=0)
        kot_wpm.pack_propagate(False)
        kot_wpm.pack(side="left")
        self.speed_chip = tk.Label(kot_wpm, text=f"⚡  {self._speed_wpm} wpm",
                                   font=("Segoe UI", 10, "bold"), fg=FG,
                                   bg=PANEL, padx=18, cursor="hand2",
                                   highlightthickness=1,
                                   highlightbackground=EDGE)
        # SATU pack saja: dulu dua pack (sisa refactor) - pack kedua
        # membawa pady=(0,16) lama = chip terpotong 16px = kekecilan
        # (keluhan user 21 Nov 'speed button a little too small')
        self.speed_chip.pack(fill="both", expand=True, side="left",
                             padx=(0, 4), pady=0)
        self.speed_chip.bind("<Button-1>",
                             lambda e: self._safe(self._toggle_dial))
        self.speed_chip.bind("<Enter>", lambda e: self.speed_chip.configure(
            bg=CARD_HOVER) if str(self.speed_chip["state"]) != "disabled"
            else None)
        self.speed_chip.bind("<Leave>",
                             lambda e: self.speed_chip.configure(bg=PANEL))

        # Rentang level tidak lagi ada di jendela utama (diminta saat Start
        # atau otomatis dari lesson yang sedang terbuka).
        self._rentang_mulai, self._rentang_akhir = self._load_range()
        self._total_level = 685
        self._rentang_btn = type("_NoBtn", (), {"configure": lambda self, **kw: None})()

        # ---------- footer: tombol cepat + saklar aktif/nonaktif ----------
        # dipasang paling awal dengan side="bottom": widget yang di-pack
        # lebih awal mendapat jatah ukuran lebih dulu - saat jendela
        # dikecilkan vertikal, kartu aktivitas-lah yang menyusut, footer
        # selalu tampak (dulu footer di-pack terakhir -> teks terpotong
        # duluan;).
        self._hotkey = True   # hotkey F9/F10/F11 tetap aktif (tanpa
        # indikator footer - footer lama DIHAPUS: kartu Siap/login/
        # ticker menembus cover profil & startup (keluhan user 19 Nov:
        # 'remove all old states'). State cukup lewat header.
        self.host = Wv2Host(
            root, paths.data_path("wv2profile"))  # sandbox ikut mode SIM
        self.host.pack(fill="both", expand=True, padx=18, pady=(0, 2))
        tengah = tk.Frame(self.host, bg=PANEL)
        # panggung animasi status: sprite per status + crossfade antar status
        self._stage_kan = tk.Canvas(tengah, width=460, height=56, bg=PANEL,
                                    highlightthickness=0)
        self._stage_kan.pack()
        self._stage = anim.StateStage(self._stage_kan).start()
        self._stage.set_state("siap")
        self.aktiv_lbl = tk.Label(tengah, text="Siap",
                                  font=("Segoe UI", 16, "bold"), fg=FG,
                                  bg=PANEL, wraplength=560, justify="center")
        self.aktiv_lbl.pack()
        self.aktiv_sub = tk.Label(tengah, text="Menyiapkan browser...",
                                  font=("Segoe UI", 10), fg=DIM, bg=PANEL,
                                  wraplength=560, justify="center")
        self.aktiv_sub.pack(pady=(6, 0))
        self.host.set_overlay(tengah)
        self.host.pack_propagate(False)

        root.protocol("WM_DELETE_WINDOW", self.on_close)

        # DEBUG GEOMETRI HEADER (sementara): dump posisi semua widget
        # header ke log 3 dtk setelah tampil - diagnosa 'tombol hilang'
        def _dump_geom():
            try:
                from .theme import LOG_FILE
                tujuan = os.path.join(os.path.dirname(LOG_FILE),
                                      "geom_debug.txt")
                with open(tujuan, "w", encoding="utf-8") as f:
                    def jalan(w, kedalaman=0):
                        try:
                            x, y = w.winfo_rootx(), w.winfo_rooty()
                            ww, hh = w.winfo_width(), w.winfo_height()
                            nm = w.winfo_name() or type(w).__name__
                            kls = type(w).__name__
                            f.write(f"{'  ' * kedalaman}{kls}/{nm}: "
                                    f"{x},{y} {ww}x{hh}" + chr(10))
                        except Exception:
                            pass
                        for c in w.winfo_children():
                            jalan(c, kedalaman + 1)
                    jalan(self.root)
                print(f"[GEOM] dump: {tujuan}")
            except Exception as e:
                print(f"[GEOM] gagal: {e}")
        self.root.after(3000, _dump_geom)

        self._log(f"TypingBot v{APP_VERSION}  •  build {_build_stamp()}")
        if self.lisensi_ok:
            self._log(f"Lisensi aktif (mesin {_machine_code()}).")
        else:
            self._log(f"Lisensi belum aktif - kode mesin: {_machine_code()}")
        threading.Thread(target=self._load_bot, daemon=True).start()
        # net worker JANGAN dulu: tunggu webview siap (flag di akhir
        # buat_webview) supaya dialog aktivasi terbuka sebagai overlay
        # DI DALAM app - dulu dia balapan & menang, dialog jadi jendela
        # OS terpisah + boot webview macet di belakangnya (keluhan user)
        self.root.after(20 * 60 * 1000, self._net_periodic)
        self.root.after(150, self._poll)


    def _title_bar(self):
        ekstra = "" if self.lisensi_ok else "  •  PERLU AKTIVASI"
        self.root.title(f"TypingBot{ekstra}")

    # ------------------------------------------------- host web v3.2
    def _browser_latar(self):
        """Siapkan WebView2 chromeless + port debug + profil dedikasi
        (thread latar; pembuatan widget tetap di thread UI via after).
        Gagal apa pun tidak boleh mematikan app - jalur browser eksternal
        lama tetap jalan saat Start."""
        # TANPA gerbang lisensi (keluhan user: popup aktivasi jadi
        # jendela terpisah karena webview tak pernah boot saat belum
        # aktivasi - ayam & telur). Browser hanya penampil edclub;
        # menjalankan BOT tetap digerbangi lisensi di on_start.
        if not wv2_tersedia():
            self._log("WebView2 tidak tersedia - pakai browser terpisah.")
            self.root.after(0, lambda: self.aktiv_sub.configure(
                text="WebView2 tidak ada - bot pakai browser terpisah."))
            return
        try:
            from engine import state as estate
            from engine.browser import (bersihkan_browser_embed,
                                        _check_debug_port, _port_bind_free)
            estate.EMBED_BROWSER = True
            # gates fokus AKTIF sejak sekarang (dulu: FOCUS_BROWSER_AT
            # di-set DI SINI padahal _embed_aktif baru True setelah webview
            # jadi - celah beberapa detik dgn gate terbuka -> poll memanggil
            # _focus_browser_window saat app baru dibuka: Helium user yang
            # fullscreen di-un-fullscreen, app 'minimize itself' - keluhan
            # user. Di mode embedded tak ada browser luar yang perlu
            # difokuskan - jangan senjatai tari-menari jendela sama sekali.)
            self._embed_aktif = True
            # browser debug eksternal sisa sesi lama (profil khusus bot)
            # ditutup supaya tidak mengganggu - WebView2 kini browsernya
            bersihkan_browser_embed()
            # pilih port bebas (WebView2 perlu port sendiri, bebas konflik)
            port = estate.DEBUG_PORT
            if not _port_bind_free(port):
                for kandidat in range(9223, 9323):
                    if _port_bind_free(kandidat):
                        port = kandidat
                        break
            estate.DEBUG_PORT = port

            def buat_webview():
                # buka LANGSUNG di halaman kursus (URL home hasil
                # migrasi). Jangan pakai sportal/program-3.game utk
                # STARTUP: URL legacy itu rapuh - sesi basi/anon pernah
                # dapat halaman error edclub "Oops! Something went
                # wrong" (keluhan live). course/3 stabil: sudah login ->
                # langsung daftar level; belum -> poll _jaga melempar ke
                # /signin (lihat _LOGIN_REDIRECT_JS).
                ok = self.host.buka(
                    port,
                    "https://www.edclub.com/student/course/3",
                    warna=PANEL)
                if ok:
                    estate.BROWSER_WV2 = True
                    # dialog dalam-app: semua popup digambar di dalam
                    # jendela (menempati area webview), bukan jendela OS
                    set_dialog_layer(self.host)
                    self.btn_akun["state"] = "normal"
                    self._style_btn(self.btn_akun)
                    # pengawas playwright: stub window.open + pengarah
                    # /signin aktif sejak app terbuka (bukan cuma saat
                    # sesi bot) - jalur .NET pythonnet terbukti sung
                    self.host.mulai_pengawas(port)
                    self._log(f"WebView2 siap di dalam app "
                              f"(port debug {port}).")
                    self.aktiv_sub.configure(
                        text="Browser aktif di dalam app.")
                else:
                    set_dialog_layer(None)      # dialog = jendela biasa
                    self._embed_aktif = False   # balik ke browser luar:
                    self.aktiv_sub.configure(   # dance fokus dibutuhkan lagi
                        text="WebView2 gagal - bot pakai browser terpisah.")
            self.root.after(0, buat_webview)
            # tunggu webview benar2 hidup sebelum lanjut (Start bisa saja
            # diklik cepat - connect() butuh port debug sudah merespons)
            for _ in range(40):
                time.sleep(0.5)
                if _check_debug_port():
                    break
            self._embed_selesai = True   # net worker boleh mulai
            threading.Thread(target=self._net_worker,
                             daemon=True).start()
        except SystemExit:
            pass
        except Exception as ex:
            self._log(f"[GUI] webview latar: {ex}")

    def _btn(self, parent, text, color, cmd, besar=False, kecil=False,
             gaya="isi"):
        if besar:
            font, padx, pady = ("Segoe UI", 11, "bold"), 26, 10
        elif kecil:
            font, padx, pady = ("Segoe UI", 12, "bold"), 14, 8
        else:
            font, padx, pady = ("Segoe UI", 10, "bold"), 16, 6
        if kecil or gaya == "hantu":
            # ghost: latar gelap + border tipis + teks berwarna semantik
            b = tk.Label(parent, text=text, font=font, fg=color if gaya == "hantu" else FG,
                         bg=PANEL, padx=padx, pady=pady, cursor="hand2",
                         highlightthickness=1, highlightbackground=EDGE)
            b._dim_bg = YELLOW_DIM if color == YELLOW else (
                RED_DIM if color == RED else CARD_HOVER)
            b._hover_border = color if gaya == "hantu" else EDGE
        else:
            # terisi: satu-satunya tombol penuh warna (aksi utama)
            b = tk.Label(parent, text=text, font=font, fg=BTN_FG, bg=color,
                         padx=padx, pady=pady, cursor="hand2")
        b.pack(side="left", padx=(0, 8) if besar or not kecil else (6, 0))
        b._gaya = gaya
        b._base_color = color

        def on_enter(_):
            if str(b["state"]) != "disabled":
                if getattr(b, "_gaya", "isi") == "hantu" or kecil:
                    b.configure(bg=b._dim_bg,
                                highlightbackground=b._hover_border)
                else:
                    b.configure(bg=GREEN_HOVER if b._base_color == GREEN
                                else self._dim(b._base_color, 1.15))

        def on_leave(_):
            if str(b["state"]) != "disabled":
                self._style_btn(b)

        b.bind("<Enter>", on_enter)
        b.bind("<Leave>", on_leave)
        b.bind("<Button-1>", lambda e: self._safe(cmd))
        return b

        # animasi TEKAN: tombol mengempis saat ditekan, kembali saat
        # dilepas - umpan balik langsung "tombol kepencet" (permintaan
        # user 19 Nov: start terasa kurang responsif)
        _padx0, _pady0 = padx, pady

        def tekan(_e=None):
            if str(b["state"]) != "disabled":
                b.configure(padx=max(6, _padx0 - 10),
                            pady=max(2, _pady0 - 4))

        def lepas(_e=None):
            if str(b["state"]) != "disabled":
                b.configure(padx=_padx0, pady=_pady0)

        b.bind("<Button-1>", tekan, add="+")
        b.bind("<ButtonRelease-1>", lepas, add="+")
        return b

    def _style_btn(self, b):
        """Warna tombol sesuai gaya + state (disabled = redup)."""
        if str(b["state"]) == "disabled":
            b.configure(bg=PANEL, fg=FAINT)
            if getattr(b, "_gaya", "isi") == "hantu":
                b.configure(highlightbackground=EDGE)
            return
        if getattr(b, "_gaya", "isi") == "hantu":
            warna = b._base_color
            b.configure(bg=PANEL,
                        fg=warna if warna != CARD else FG,
                        highlightbackground=EDGE)
        else:
            b.configure(bg=b._base_color, fg=BTN_FG)

    def _sync_btn_states(self):
        """Set state Start/Pause/Stop dr status thread + rapikan warna."""
        jalan = bool(self.bot_thread)
        self.btn_start["state"] = "disabled" if jalan else "normal"
        self.btn_stop["state"] = "normal" if jalan else "disabled"
        for b in (self.btn_start, self.btn_stop):
            self._style_btn(b)


    @staticmethod
    def _dim(hex_color, f):
        r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
        return f"#{int(r * f):02x}{int(g * f):02x}{int(b * f):02x}"


    def _set_state(self, text, color, stage=None):
        self.state_lbl.configure(text=text, fg=color)
        if stage:
            try:
                self._stage.set_state(stage)
            except Exception:
                pass


    def _set_activity(self, utama, sub):
        """Kartu aktivitas (overlay host) + ticker tipis di bawah host:
        kalimat besar bahasa awam + keterangan kecil."""
        try:
            self.aktiv_lbl.configure(text=utama)
            self.aktiv_sub.configure(text=sub)
            baris = utama + (f"  •  {sub}" if sub else "")
            if hasattr(self, "ticker_lbl"):
                self.ticker_lbl.configure(text=baris)
        except Exception:
            pass


    def _safe(self, cmd):
        try:
            cmd()
        except Exception as ex:
            import traceback
            self._log(f"[GUI] error: {ex!r}")
            try:
                self.log_file.write(traceback.format_exc() + "\n")
                self.log_file.flush()
            except Exception:
                pass


    def _log(self, line):
        self.log_q.put(line)
        try:
            if self.log_file:
                self.log_file.write(line + "\n")
                self.log_file.flush()
        except Exception:
            pass


    # ------------------------------------------------------------------ start

    def _update_hotkey_label(self):
        """Footer = indikator + saklar hotkey global (permintaan user:
        F9/F10/F11 bisa tak sengaja mengetik bot saat dipakai app lain)."""
        if not hasattr(self, "hotkey_lbl"):
            return   # footer lama dihapus - tak ada yang dikonfigurasi
        try:
            if self._hotkey:
                self.hotkey_lbl.configure(
                    text="⌨  F9 jeda   •   F10 kecepatan   •   F11 stop   •   "
                         "AKTIF  (klik untuk matikan)",
                    fg=DIM)
            else:
                self.hotkey_lbl.configure(
                    text="⌨  Hotkey F9/F10/F11 NONAKTIF  (klik untuk nyalakan)",
                    fg=FAINT)
        except Exception:
            pass
    def _lapor_kiriman(self, kategori, deskripsi, selesai):
        """Kumpulkan + kirim laporan bug (versi + akun + 400 baris log
        otomatis via server; offline/gagal = Desktop + clipboard).
        selesai(ok, pesan) boleh dari thread mana pun (after-marshal
        di sisi pemanggil)."""
        import threading as _th

        def kerja():
            try:
                from .theme import LOG_FILE
                log_tail = ""
                try:
                    with open(LOG_FILE, encoding="utf-8",
                              errors="replace") as f:
                        log_tail = chr(10).join(
                            f.read().split(chr(10))[-400:])
                except Exception as e:
                    log_tail = f"(log tak terbaca: {e})"
                akun = "?"
                try:
                    from . import webview2_host as _w2v
                    akun = _w2v._akun_aktif_nama() or "?"
                except Exception:
                    pass
                isi = (
                    "TypingBot laporan bug" + chr(10) +
                    f"versi: {APP_VERSION}  build: {_build_stamp()}"
                    + chr(10) +
                    f"akun aktif: {akun}" + chr(10) +
                    f"kategori: {kategori}" + chr(10) +
                    f"waktu: {time.strftime('%Y-%m-%d %H:%M:%S')}" + chr(10)
                    + chr(10) +
                    ("=== CERITA USER ===" + chr(10) + deskripsi
                     + chr(10) + chr(10) if deskripsi else "") +
                    "=== LOG (400 baris terakhir) ===" + chr(10)
                    + log_tail + chr(10))
                # 1) kirim otomatis via server (worker: /api/lapor)
                try:
                    from net import api as _api
                    status, _data = _api.http_json(
                        "POST", "/api/lapor",
                        {"versi": APP_VERSION, "akun": akun,
                         "isi": isi}, timeout=15)
                    if status == 200:
                        self._lapor_terakhir = time.time()
                        self._log("[LAPOR] terkirim otomatis.")
                        self._set_state(
                            "🪲 Laporan terkirim - terima kasih!",
                            ACCENT)
                        selesai(True, "Laporan terkirim — terima kasih!")
                        return
                    print(f"[LAPOR] server tolak ({status}).")
                except Exception as e:
                    print(f"[LAPOR] kirim otomatis gagal: "
                          f"{str(e)[:60]}")
                # 2) fallback: Desktop + clipboard
                desktop = os.path.join(os.path.expanduser("~"), "Desktop")
                if not os.path.isdir(desktop):
                    desktop = os.path.join(os.path.expanduser("~"),
                                           "OneDrive", "Desktop")
                os.makedirs(desktop, exist_ok=True)
                tujuan = os.path.join(desktop, "TypingBot-laporan-"
                                      + time.strftime("%Y%m%d-%H%M%S")
                                      + ".txt")
                with open(tujuan, "w", encoding="utf-8") as f:
                    f.write(isi)
                self.root.clipboard_clear()
                self.root.clipboard_append(isi)
                try:
                    os.startfile(desktop)
                except Exception:
                    pass
                self._log("[LAPOR] offline - laporan di Desktop.")
                selesai(True, "Tersimpan di Desktop + tersalin "
                        "(offline) — kirim filenya ya!")
            except Exception as e:
                try:
                    selesai(False, f"gagal: {str(e)[:70]}")
                except Exception:
                    pass
        _th.Thread(target=kerja, daemon=True).start()

    def _lapor_bug(self):
        """Buka form lapor bug (dialog tile kategori wajib + cerita
        opsional). Kirim = _lapor_kiriman (otomatis via server)."""
        import threading as _th
        if time.time() - getattr(self, "_lapor_terakhir", 0.0) < 60:
            self._log("[LAPOR] baru saja mengirim - tunggu ~1 menit "
                      "(anti-spam).")
            self._set_state("🪲 baru saja kirim - tunggu sebentar",
                            ACCENT)
            return

        def kirim(kategori, deskripsi, selesai):
            self._lapor_kiriman(kategori, deskripsi, selesai)

        try:
            from .dialogs import dialog_lapor_bug
            dialog_lapor_bug(self.root, kirim)
        except Exception as e:
            self._log(f"[LAPOR] dialog gagal: {str(e)[:90]}")








    def _apply_speed(self, wpm, save=False):
        """Terapkan wpm (halus, 85-300) ke chip, dial (bila terbuka), dan
        engine. save=True hanya di akhir interaksi (lepas drag) - jangan
        tulis disk per pixel saat drag."""
        wpm = int(wpm)
        self._speed_wpm = wpm
        self.speed_chip.configure(text=f"⚡  {wpm} wpm")
        if self._dial is not None and self._dial.winfo_exists():
            self._dial.set_wpm(wpm)
        if self.bot:
            self.bot.SPEED_WPM = wpm
        if save:
            self._save_settings()

    def _toggle_dial(self):
        """Buka/tutup popup dial kecepatan di bawah chip."""
        if self._dial is not None and self._dial.winfo_exists():
            self._dial.tutup()
            return
        self._dial = SpeedDial(self.speed_chip,
                               [(str(w), w) for w in self.SPEED_TIERS],
                               self._speed_wpm,
                               command=self._on_dial_wpm,
                               released=self._on_dial_release)

    def _on_dial_wpm(self, wpm):
        """Putar dial: nilai halus live (engine ikut, tanpa tulis disk)."""
        self._apply_speed(wpm)

    def _on_dial_release(self, wpm):
        """Lepas dial: simpan pilihan + spring ke tick terdekat."""
        self._apply_speed(wpm, save=True)

    def _toggle_hotkey(self):
        self._hotkey = not self._hotkey
        self._save_settings()
        self._update_hotkey_label()
        if self.bot:
            self.bot.HOTKEYS_ON = self._hotkey
        self._log("Hotkey global F9/F10/F11 "
                  + ("diaktifkan." if self._hotkey else "DIMATIKAN."))


    def _save_settings(self):
        """Tulis typingbot_settings.json: browser pilihan + browser terakhir
        yang dipakai Otomatis (dipertahankan antar ganti pilihan)."""
        data = {}
        try:
            data = json.load(open(SETTINGS_FILE, encoding="utf-8"))
        except Exception:
            pass
        data["browser"] = self.browser_var.get()
        data["hotkey"] = bool(self._hotkey)
        data["speed"] = self._speed_wpm
        data["profile"] = self._profile
        data["profile_dir"] = self._profile_dir
        data["profile_label"] = self._profile_label
        if self._last_browser_path:
            data["last_browser"] = self._last_browser_path
        try:
            json.dump(data, open(SETTINGS_FILE, "w", encoding="utf-8"))
        except Exception:
            pass


    def on_close(self):
        if self.bot:
            self.bot.STOP = True
            self.bot.PAUSED = False
        try:
            self.host.hentikan_pengawas()   # thread playwright berhenti
        except Exception:
            pass
        try:
            self.host.release()   # matikan WebView2 rapi sebelum destroy
        except Exception:
            pass
        try:
            # buang sisa _MEI instance lain/crash (bootloader hanya
            # bereskan milik sendiri saat exit bersih)
            from gui.meisweep import sweep_mei
            sweep_mei()
        except Exception:
            pass
        time.sleep(0.2)
        self.root.destroy()




if __name__ == "__main__":
    def _main():
        # DPI awareness wajib sebelum Tk dibuat: tanpa ini Windows merender app
        # di 96dpi lalu meregangnya bitmap-style -> GUI terlihat buram/low-res
        # di layar dengan scaling 125%/150% (laptop modern).
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PER_MONITOR_AWARE
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
        root = tk.Tk()
        try:
            from tkinter import font as tkfont
            default_font = tkfont.nametofont("TkDefaultFont")
            default_font.configure(family="Segoe UI", size=10)
        except Exception:
            pass
        App(root)
        # buka langsung maksimal (permintaan user) - di entrypoint, bukan di
        # App: test UI bikin App dengan geometri kecil sendiri
        try:
            root.state("zoomed")
        except Exception:
            pass
        if os.environ.get("TYPINGBOT_SENYAP") == "1":
            def _turun(i=[0]):
                try:
                    root.lower()
                except Exception:
                    pass
                i[0] += 1
                if i[0] < 5:
                    root.after(1200, _turun)
            root.after(400, _turun)
        root.mainloop()
    # v3.2: seluruh app jalan di CLR thread STA - syarat WebView2 (tanpa
    # itu CoreWebView2 gagal RPC_E_CHANGED_MODE). Tanpa pythonnet, jalan
    # di thread utama seperti biasa (jalur WebView2 otomatis nonaktif).
    jalankan_sta(_main)
