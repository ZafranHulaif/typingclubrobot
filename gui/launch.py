"""Jendela utama - bagian launch."""

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

from .dialogs import (dialog_online_activation, dialog_open_browser, dialog_pick_browser, dialog_pick_profile, dialog_tips, dialog_force_close)
from .icons import _icon_widget
from .licensing import _machine_code
from .theme import (ACCENT, APP_VERSION, BROWSER_COLORS, CARD, CARD_HOVER, DIM, EDGE, FG, GREEN, LOG_FILE, PANEL, PROGRAM_PATH, RED, SETTINGS_FILE)
from .widgets import _Dialog


class LaunchMixin:
    """Mixin: dipadukan di gui/app.py."""


    class _Writer:
        def __init__(self, app):
            self.app = app

        def write(self, s):
            if s and s.strip():
                self.app.log_q.put(s.rstrip("\n"))
            f = self.app.log_file
            if f:
                try:
                    f.write(s)
                    f.flush()
                except Exception:
                    pass
            return len(s)

        def flush(self):
            pass


    # ------------------------------------------------------------------ bot

    def _load_bot(self):
        try:
            self.log_file = open(LOG_FILE, "w", encoding="utf-8", buffering=1)
        except Exception:
            self.log_file = None
        sys.stdout = self._Writer(self)
        sys.stderr = self._Writer(self)
        try:
            import autopilot_pw as bot
            self.bot = bot
            bot.set_confirmer(self._confirm_kill)
            self._ui_queue.put(self._detect_browsers)
            self._log("Modul bot dimuat. Klik Start untuk mulai.")
        except Exception as ex:
            self._log(f"GAGAL memuat bot: {ex}")


    def _confirm_kill(self, nama, pid, exe=""):
        """Dialog 'port 9222 dipakai aplikasi lain, tutup paksa?'.
        Tkinter hanya boleh dari thread utama -> jadwalkan via root.after."""
        hasil = {"ok": False}
        done = threading.Event()

        def tanya():
            try:
                hasil["ok"] = dialog_force_close(self.root, nama, pid, exe)
            except Exception:
                hasil["ok"] = False
            finally:
                done.set()

        try:
            self.root.after(0, tanya)
        except Exception:
            return False
        done.wait(timeout=180)
        return hasil["ok"]


    def on_tips(self):
        det = ", ".join(n for n, _ in self._detected) or "tidak terdeteksi"
        dialog_tips(self.root, det)

    # -------------------------------------------------------------- jaringan

    def _load_nickname(self):
        try:
            return json.load(open(SETTINGS_FILE, encoding="utf-8")).get("nickname", "")
        except Exception:
            return ""

    def _save_nickname(self, nick):
        try:
            data = {}
            try:
                data = json.load(open(SETTINGS_FILE, encoding="utf-8"))
            except Exception:
                pass
            data["nickname"] = nick
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass

    def _net_worker(self):
        """Satu-satunya pintu internet aplikasi: dipanggil sekali saat
        mulai (lisensi + cek versi), setelah itu sepenuhnya offline."""
        from net import api
        if not api.BASE_URL:
            self._log("[net] server tidak dikonfigurasi - mode offline")
            if not self.lisensi_ok:
                self._log("[net] aktivasi butuh server - jalur kunci manual "
                          "sudah dihapus")
            return
        try:
            self._net_license_flow()
        except Exception as ex:
            self._log(f"[net] lisensi online gagal: {ex}")
            if not self.lisensi_ok:
                self._ui_queue.put(self._ask_online)
        try:
            self._net_update_check()
        except Exception as ex:
            self._log(f"[net] cek pembaruan gagal: {ex}")

    def _net_license_flow(self):
        from net import license as netlic
        from .licensing import _load_online_token, _save_online_token
        mc = _machine_code()
        tok = _load_online_token()
        if tok and netlic.verify_token(tok):
            data = netlic.fetch_status(mc)
            st = data.get("status")
            if st == "approved" and data.get("token"):
                _save_online_token(data["token"])
                self._tok_cache = data["token"]
                self._log("[net] lisensi online diperpanjang "
                          f"({netlic.days_left(data['token'])} hari lagi)")
            elif st == "approved":
                # server setuju tapi tanpa token (jawaban aneh) - jangan
                # kunci mesin karena glitch sesaat
                self._tok_cache = tok
            else:
                # revoked/denied/pending/unknown: server TIDAK lagi menjamin
                # mesin ini - token offline tidak boleh dipercaya (dulu:
                # mesin 'pending' tetap bisa dipakai dengan token lama)
                self._ui_queue.put(lambda: self._on_license_revoked(st))
            return
        if self.lisensi_ok:
            # kunci lama tetap valid; daftar diam-diam supaya bisa ikut
            # pembaruan (token unduhan hanya untuk mesin yang disetujui)
            nick = self._load_nickname() or "pemilik-lama"
            data = netlic.request_approval(mc, nick, APP_VERSION)
            if data.get("status") == "approved" and data.get("token"):
                _save_online_token(data["token"])
                self._tok_cache = data["token"]
                self._log("[net] mesin ini sudah disetujui server")
            else:
                self._log("[net] menunggu persetujuan server untuk "
                          "fitur pembaruan")
            return
        self._net_request_flow(mc)

    def _net_request_flow(self, mc):
        """Dialog nickname + polling sampai disetujui / ditolak / bosan."""
        from net import api
        from net import license as netlic
        from .licensing import _save_online_token
        # pintu pulih: token lokal bisa hilang (dicabut lalu disetujui
        # lagi di admin, dihapus saat uji) padahal server SUDAH menyetujui
        # mesin ini - tanya status dulu; approved berarti token keluar
        # langsung TANPA dialog nickname (dulu: mesin yang sudah
        # disetujui tetap ditanya nama lagi setiap kali tokennya hilang)
        try:
            awal = netlic.fetch_status(mc)
            if awal.get("status") == "approved" and awal.get("token"):
                _save_online_token(awal["token"])
                self._tok_cache = awal["token"]

                def aktif():
                    self.lisensi_ok = True
                    self._title_bar()
                    self._log("Lisensi AKTIF (disetujui pemilik). "
                              "Terima kasih!")
                    self._set_state("⏻ Siap", FG)

                self._ui_queue.put(aktif)
                return
        except Exception as ex:
            self._log(f"[net] cek status awal gagal: {ex}")
        self._online_cancel = False
        self._online_dlg = None

        def kirim_nick(nick):
            self._save_nickname(nick)
            self._nick_q.put(nick)

        def siap(dlg):
            # WAJIB sebelum show(): show() memblokir thread utama sampai
            # dialog ditutup - tanpa ini referensi _online_dlg masih None
            # saat thread net mau memanggil set_status/finish (popup lama
            # tidak pernah menutup sendiri karena ini).
            self._online_dlg = dlg

        def buka():
            dialog_online_activation(
                self.root, self._load_nickname(),
                on_send=kirim_nick,
                on_cancel=lambda: setattr(self, "_online_cancel", True),
                on_ready=siap)

        self._ui_queue.put(buka)
        try:
            self._nick_q.get(timeout=600)
        except queue.Empty:
            return
        nick = self._load_nickname() or "Tanpa-nama"
        try:
            data = netlic.request_approval(mc, nick, APP_VERSION)
        except api.Unreachable as ex:
            self._log(f"[net] server tidak terjangkau: {ex}")
            self._ui_queue.put(
                lambda: self._online_dlg
                and (self._online_dlg.set_status(
                    "🌐 Tidak dapat menjangkau server.",
                    "Periksa koneksi internet, lalu buka aplikasi lagi."),
                     self._online_dlg.finish(False)))
            return
        except Exception as ex:
            self._log(f"[net] permintaan gagal: {ex}")
            data = {}
        for i in range(36):
            if self._online_cancel:
                return
            st = data.get("status")
            if st == "approved" and data.get("token"):
                _save_online_token(data["token"])
                self._tok_cache = data["token"]

                def sukses():
                    self.lisensi_ok = True
                    self._title_bar()
                    self._log("Lisensi AKTIF (disetujui pemilik). Terima kasih!")
                    self._set_state("⏻ Siap", FG)
                    try:
                        self._online_dlg.finish(True)
                    except Exception:
                        pass

                self._ui_queue.put(sukses)
                return
            if st in ("denied", "revoked"):
                self._ui_queue.put(
                    lambda: self._online_dlg
                    and self._online_dlg.set_status("❌ Permintaan ditolak pemilik."))
                return
            info = f"⏳ Menunggu persetujuan pemilik... ({(i + 1) * 5}s)"

            def status(t=info):
                try:
                    self._online_dlg.set_status(t,
                                                "Pemilik menyetujui lewat "
                                                "halaman admin-nya.")
                except Exception:
                    pass

            self._ui_queue.put(status)
            time.sleep(5)
            try:
                data = netlic.fetch_status(mc)
            except Exception:
                pass
        self._ui_queue.put(
            lambda: self._online_dlg
            and self._online_dlg.set_status("⌛ Waktu tunggu habis.",
                                            "Coba buka aplikasi lagi nanti."))

    def _on_license_revoked(self, st):
        from .licensing import _delete_online_token
        _delete_online_token()
        self._tok_cache = None
        self.lisensi_ok = False
        self._title_bar()
        pesan = ("Server meminta persetujuan ulang untuk komputer ini."
                 if st == "pending" else
                 f"Pemilik aplikasi mencabut/menolak akses komputer ini "
                 f"({st}).")
        self._log(f"[net] {pesan} Token lokal dihapus.")
        try:
            if self.bot_thread and self.bot_thread.is_alive():
                self._log("[net] sesi bot dihentikan karena akses dicabut")
                if self.bot:
                    self.bot.STOP = True
                self.on_stop()
        except Exception:
            pass
        d = _Dialog(self.root, "Lisensi tidak aktif", pesan,
                    ikon="⛔", warna=RED)
        tk.Label(d.body, text="Kirim permintaan baru untuk minta persetujuan.",
                 font=("Segoe UI", 10), fg=FG, bg=PANEL,
                 wraplength=420, justify="left").pack(anchor="w", pady=(4, 0))
        d.button("Minta persetujuan", None,
                 cmd=lambda: (d.done(None), self._ask_online()))
        d.show()

    def _net_license_recheck(self):
        """Cek ulang status lisensi ke server (saat Start + berkala)
        supaya pencabutan akses mendarat TANPA perlu restart aplikasi
        (dulu: token offline 30 hari membuat revoke hanya efektif
        setelah aplikasi dibuka ulang)."""
        from net import license as netlic
        from .licensing import _load_online_token, _save_online_token
        if not self.lisensi_ok:
            return
        try:
            data = netlic.fetch_status(_machine_code())
        except Exception:
            return
        st = data.get("status")
        if st == "approved" and data.get("token"):
            _save_online_token(data["token"])
            self._tok_cache = data["token"]
        elif st == "approved":
            pass
        else:
            self._ui_queue.put(lambda: self._on_license_revoked(st))

    def _net_periodic(self):
        threading.Thread(target=self._net_license_recheck, daemon=True).start()
        try:
            self.root.after(20 * 60 * 1000, self._net_periodic)
        except Exception:
            pass

    def _net_update_check(self):
        from net import license as netlic
        from net import updater as netupd
        ver = getattr(self, "_ver_override", None) or APP_VERSION
        info = netupd.check(ver)
        if not info:
            self._log("[net] versi sudah yang terbaru")
            return
        tok = getattr(self, "_tok_cache", None)
        if not (tok and netlic.verify_token(tok)):
            self._log("[net] pembaruan tersedia tapi mesin belum "
                      "disetujui server")
            return
        self._update_info = info
        self._ui_queue.put(lambda: self._show_update_button(info))

    def _show_update_button(self, info):
        try:
            ver = info.get("version", "?")
            teks = ("\u21bb v{ver} siap"
                    if getattr(self, "_update_ready", False)
                    else "\u2b07 v{ver}").format(ver=ver)
            if self._update_btn is None:
                self._update_btn = self._btn(self.kanan, teks,
                                             GREEN, self.on_update, kecil=True)
            else:
                self._update_btn.configure(text=teks)
            self._log(f"[net] pembaruan tersedia: v{ver} "
                      f"({info.get('notes') or '-'})")
        except Exception:
            pass

    def on_update(self):
        if getattr(self, "_updating", False):
            return
        info = getattr(self, "_update_info", None)
        tok = getattr(self, "_tok_cache", None)
        if not info or not tok:
            return
        from .dialogs import dialog_update
        ver = getattr(self, "_ver_override", None) or APP_VERSION

        def siap(d):
            d.on_start = lambda: self._update_mulai(d, info, tok)

        tahap = "siap" if getattr(self, "_update_ready", False) else "awal"
        hasil = dialog_update(self.root, info, ver, tahap=tahap, on_ready=siap)
        if hasil == "restart":
            self._update_apply_now(info)
        elif hasil == "later":
            self._update_nanti(info)

    def _update_mulai(self, d, info, tok):
        """Dipanggil dialog saat user menyetujui unduh (thread utama)."""
        if getattr(self, "_updating", False):
            return
        self._updating = True
        self._set_state("\u2b07 Mengunduh pembaruan...", ACCENT)

        def prog(got, total):
            self._ui_queue.put(
                lambda g=got, t=total: d.set_progress(g, t))
            return not getattr(d, "batal", False)

        def kerja():
            from net import updater as netupd
            try:
                netupd.download(info, tok,
                                PROGRAM_PATH + netupd.NEW_SUFFIX, prog)
                # user boleh menolak mulai ulang: tandai siap, saat
                # aplikasi dibuka lagi exe ditukar sebelum GUI muncul
                netupd.stage_pending(PROGRAM_PATH, info)
                self._update_ready = True
                self._ui_queue.put(
                    lambda: (self._show_update_button(info),
                             d.stage_ready()))
            except netupd.UpdateCancelled:
                self._log("[net] unduhan dibatalkan pengguna.")
                self._ui_queue.put(lambda: d.done("cancelled"))
            except Exception as ex:
                self._log(f"[net] pembaruan gagal: {ex}")
                self._ui_queue.put(lambda: d.stage_error(str(ex)))
            finally:
                self._updating = False

        threading.Thread(target=kerja, daemon=True).start()

    def _update_apply_now(self, info):
        from net import updater as netupd
        self._log(f"Pembaruan v{info.get('version')} dipasang - "
                  "aplikasi dimulai ulang...")
        self._set_state("\u2713 Memasang pembaruan...", ACCENT)
        if not netupd.apply_update_and_restart(PROGRAM_PATH):
            self._set_state("\u23fb Siap", FG)
            self._log("[net] mode skrip: ganti exe manual "
                      "(TypingBot.exe.new.exe)")
            return
        try:
            self.root.after(700, self.on_close)
        except Exception:
            self.on_close()

    def _update_nanti(self, info):
        self._set_state("\u23fb Siap", FG)
        self._log(f"[net] v{info.get('version')} terpasang otomatis saat "
                  "aplikasi dibuka lagi (unduhan selesai & terverifikasi).")


    # ------------------------------------------------------ lisensi & browser

    def _ask_online(self):
        """Satu-satunya jalur aktivasi: minta persetujuan lewat server."""
        if self.lisensi_ok:
            # dari alat dev: terasa 'tidak melakukan apa-apa' tanpa log
            self._log("[net] lisensi sudah aktif - tidak perlu meminta "
                      "persetujuan lagi. (Hapus lisensi dulu untuk uji "
                      "alur penuh.)")
            return
        if getattr(self, "_online_running", False):
            self._log("[net] permintaan persetujuan sudah berjalan.")
            return
        self._online_running = True

        def kerja():
            try:
                self._net_request_flow(_machine_code())
            finally:
                self._online_running = False

        threading.Thread(target=kerja, daemon=True).start()


    def _detect_browsers(self):
        """Isi ulang dropdown browser. Dipanggil di thread utama setelah
        modul bot termuat (daftar kandidat browser ada di modul itu)."""
        det = []
        try:
            for cand in self.bot.BROWSER_CANDIDATES:
                for p in cand["paths"]:
                    if os.path.isfile(p):
                        det.append((cand["name"], p))
                        break
        except Exception as ex:
            self._log(f"[GUI] deteksi browser gagal: {ex}")
        self._detected = det
        pilihan = ["Otomatis"] + [n for n, _ in det]
        # browser dropdown sudah dihapus dari jendela utama; stub menelan
        # set_values dari kode lama
        self.browser_dd.set_values(pilihan)
        try:
            simpan = json.load(open(SETTINGS_FILE, encoding="utf-8"))
            if simpan.get("browser") in pilihan:
                self.browser_var.set(simpan["browser"])
            if simpan.get("last_browser") and os.path.isfile(simpan["last_browser"]):
                self._last_browser_path = simpan["last_browser"]
            if "hotkey" in simpan:
                self._hotkey = bool(simpan["hotkey"])
                if self.bot:
                    self.bot.HOTKEYS_ON = self._hotkey
                self.root.after(0, self._update_hotkey_label)
            if simpan.get("profile") in ("bot", "saya"):
                self._profile = simpan["profile"]
            self._profile_dir = simpan.get("profile_dir", "") or ""
            self._profile_label = simpan.get("profile_label", "") or ""
        except Exception:
            pass
        try:
            self.root.after(0, self._update_browser_chip)
        except Exception:
            pass
        self._first_run = not os.path.exists(SETTINGS_FILE)
        self._log("Browser terdeteksi: "
                  + (", ".join(n for n, _ in det) or "tidak ada"))


    def _update_browser_chip(self):
        """Gambar ulang kartu browser persegi (kanan atas): logo besar +
        nama pilihan (Otomatis menampilkan browser aktual yang dipakai).
        Semua widget anak ikut di-bind klik (label/canvas menelan klik
        kalau hanya frame yang di-bind - dulu chip tak bisa diklik)."""
        try:
            for w in self.chip.winfo_children():
                w.destroy()
        except Exception:
            return
        pilih = self.browser_var.get()
        det = dict(self._detected)
        path, label, sub = "", pilih, "klik untuk ganti"
        if pilih == "Otomatis":
            aktif = ""
            try:
                if self.bot_thread and self.bot and self.bot.BROWSER:
                    aktif = self.bot.BROWSER.get("name", "")
            except Exception:
                aktif = ""
            if aktif:
                label, sub = aktif, "Otomatis • aktif"
                path = det.get(aktif, "")
            elif self._last_browser_path:
                for n, p in self._detected:
                    if p == self._last_browser_path:
                        label, sub = n, "Otomatis • terakhir"
                        path = p
                        break
            else:
                label, sub = "Otomatis", "belum ada riwayat"
        else:
            path = det.get(pilih, "")
        # keterangan profil: singkat supaya muat di kartu
        if self._profile == "saya":
            sub = (f"profilmu: {self._profile_label}"
                   if self._profile_label else "pakai profilmu")
        isi = tk.Frame(self.chip, bg=CARD)
        isi.pack(expand=True, fill="both")
        # ukuran ikon & wrap disesuaikan kartu 132x96 (teks tidak boleh
        # terpotong -; label pendek + wraplength)
        ikon = _icon_widget(isi, path, pilih, BROWSER_COLORS.get(pilih, "#7c5cff"),
                            42, char="⚡" if pilih == "Otomatis" else None)
        ikon.pack(pady=(5, 0))
        tk.Label(isi, text=label, font=("Segoe UI", 10, "bold"),
                 fg=FG, bg=CARD, wraplength=118).pack()
        tk.Label(isi, text=sub, font=("Segoe UI", 8), fg=DIM,
                 bg=CARD, wraplength=118).pack(pady=(0, 3))
        # ukuran kartu dari isi -> persegi (auto, tahan DPI). Ukuran fix px
        # + font 125-150% = teks terpotong .
        try:
            isi.update_idletasks()
            wj = max(isi.winfo_reqwidth(), ikon.winfo_reqwidth()) + 18
            hj = isi.winfo_reqheight() + 14
            sisi = max(wj, hj, 96)
            self.chip.configure(width=sisi, height=sisi)
        except Exception:
            pass
        # bind klik + hover ke frame dan semua anak (anak menelan event kalau
        # tidak di-bind sendiri; canvas ikon termasuk)
        semua = [self.chip, isi, ikon] + self.chip.winfo_children() \
            + isi.winfo_children()

        def klik(_e=None):
            self._safe(self._switch_browser)

        def hover(_e):
            for w2 in semua:
                try:
                    w2.configure(bg=CARD_HOVER)
                except Exception:
                    pass
            self.chip.configure(highlightbackground=ACCENT)

        def leave(_e):
            for w2 in semua:
                try:
                    w2.configure(bg=CARD)
                except Exception:
                    pass
            self.chip.configure(highlightbackground=EDGE)

        for w2 in semua:
            try:
                w2.bind("<Button-1>", klik)
                w2.bind("<Enter>", hover)
                w2.bind("<Leave>", leave)
            except Exception:
                pass


    def _browser_profile_name(self):
        """Nama browser yang profilenya ditampilkan/dipakai mode 'saya'.
        Otomatis -> ikuti preferensi engine (browser terakhir/deteksi)."""
        pilih = self.browser_var.get()
        if pilih != "Otomatis":
            return pilih
        if self._last_browser_path:
            for n, p in self._detected:
                if p == self._last_browser_path:
                    return n
        if self.bot:
            try:
                return (self.bot._find_browser() or {}).get("name", "Brave")
            except Exception:
                pass
        return "Brave"


    def _pick_profile_for(self, nama_browser):
        """Buka dialog pilih profil milik browser. Return dict profil atau
        None (batal/tidak terbaca -> pemanggil memakai profil khusus)."""
        daftar = []
        if self.bot:
            try:
                daftar = self.bot._list_profiles(nama_browser)
            except Exception as ex:
                self._log(f"[GUI] baca profil gagal: {ex}")
        return dialog_pick_profile(self.root, nama_browser, daftar,
                                   self._profile_dir)


    def _switch_browser(self):
        """Klik chip browser: buka popup kartu logo untuk mengganti."""
        hasil = dialog_pick_browser(self.root, self._detected,
                                     self.browser_var.get(), self._profile)
        if not (isinstance(hasil, tuple) and len(hasil) == 2):
            return
        nama, profil = hasil
        self.browser_var.set(nama)
        self._profile = profil
        if profil == "saya":
            p = self._pick_profile_for(self._browser_profile_name())
            if p:
                self._profile_dir = p["dir"]
                self._profile_label = p["nama"]
                self._log(f"Profil dipilih: {p['nama']} "
                          f"({p.get('email') or 'tanpa email'}).")
            else:
                self._profile = "bot"
                self._profile_dir = self._profile_label = ""
        else:
            self._profile_dir = self._profile_label = ""
        self._save_settings()
        self._first_run = False
        self._update_browser_chip()
        if self.bot_thread:
            self._log(f"Browser diganti ke {nama} - berlaku saat Start "
                      "berikutnya.")


    def on_start(self):
        bot = self.bot
        if not bot:
            return
        if self.bot_thread:
            if self.bot_thread.is_alive():
                self._log("Bot masih menyiapkan sesi sebelumnya. "
                          "Klik Stop, tunggu beberapa detik, lalu Start lagi.")
            return
        if not self.lisensi_ok:
            self._ask_online()
            return
        # gerbang Start: tunggu putusan server SEBENTAR sebelum lanjut
        # (dulu: dialog browser terbuka duluan, verdict revoke menyusul ->
        # dua popup bertumpuk)
        kotak = {"tolak": False}

        def cek_gerbang():
            from net import api
            from net import license as netlic
            try:
                st, data = api.http_json(
                    "GET", "/api/license/status?mc=" + _machine_code(),
                    timeout=3)
            except Exception:
                return
            if data.get("status") not in ("approved", None):
                kotak["tolak"] = True
                stn = data.get("status") or "unknown"
                self._ui_queue.put(lambda: self._on_license_revoked(stn))

        self._set_state("🔎 Cek lisensi...", ACCENT)
        t_cek = threading.Thread(target=cek_gerbang, daemon=True)
        t_cek.start()
        t_cek.join(timeout=3.4)
        if kotak["tolak"]:
            return
        # Rentang level ditanyakan setelah tersambung & login diketahui
        # (bukan sebelum Start) - lihat _poll.
        self._tanya_rentang = True
        # Popup pilih browser hanya pertama kali (belum ada pengaturan).
        # Setelah itu pilihan tersimpan; ganti lewat chip di tengah atas.
        if self._first_run:
            hasil = dialog_pick_browser(self.root, self._detected,
                                         self.browser_var.get(), self._profile)
            if not (isinstance(hasil, tuple) and len(hasil) == 2):
                return
            self.browser_var.set(hasil[0])
            self._profile = hasil[1]
            if self._profile == "saya":
                p = self._pick_profile_for(self._browser_profile_name())
                if p:
                    self._profile_dir = p["dir"]
                    self._profile_label = p["nama"]
                else:
                    self._profile = "bot"
                    self._profile_dir = self._profile_label = ""
            self._first_run = False
        pilih = self.browser_var.get()
        # mode profil: berlaku ke engine sebelum koneksi dibuat
        if hasattr(bot, "PROFILE_MODE"):
            bot.PROFILE_MODE = self._profile
            bot.PROFILE_DIR = self._profile_dir
            bot.PROFILE_LABEL = self._profile_label
        deteksi = bot._find_browser() or {}
        # Otomatis: beri tahu engine browser terakhir yang dipakai
        bot.LAST_BROWSER = self._last_browser_path if pilih == "Otomatis" else ""
        bot.FORCE_BROWSER = next((p for n, p in self._detected if n == pilih), "")
        self._save_settings()
        self._update_browser_chip()
        # Konfirmasi 'buka browser?' tepat saat bot akan meluncurkan jendela
        # browser: port mati (bot membuka baru), atau port dipegang browser/
        # aplikasi lain (ditutup dulu, lalu bot membuka pilihan user - dulu
        # kasus ini tidak dikonfirmasi,). Kalau port sudah
        # dipegang browser pilihan sendiri (atau Otomatis menempel browser
        # yang sudah jalan), jendela dipakai ulang -> popup tidak perlu.
        proc = deteksi.get("proc", "").lower()
        port_hidup = bool(bot._check_debug_port())
        pemegang = bot._port_holders() if port_hidup else []
        nama_pemegang = " ".join(n.lower() for _, n in pemegang)
        akan_buka = (not port_hidup) or (not pemegang) \
            or (proc != "" and proc not in nama_pemegang \
                and pilih != "Otomatis")
        if akan_buka:
            det = {n: p for n, p in self._detected}
            nm = pilih if pilih in det else deteksi.get("name", "browser")
            if not dialog_open_browser(self.root, nm, det.get(nm),
                                       self._profile, self._profile_label):
                return
        bot.STOP = False
        bot.PAUSED = False
        bot.RANGE_DONE = False
        self._selesai_info = False
        self._aktiv_sub_teks = ""
        bot.LEVEL_START = self._rentang_mulai
        bot.LEVEL_END = self._rentang_akhir
        if self._rentang_mulai > 1 or self._rentang_akhir:
            self._log(f"Rentang level aktif: {self._rentang_mulai} - "
                      f"{self._rentang_akhir or 'akhir kursus'}.")
        self.bot_thread = threading.Thread(target=self._run_bot, daemon=True)
        self.bot_thread.start()


    def _run_bot(self):
        try:
            self.bot.connect()
            # Otomatis: ingat browser yang BENAR2 dipakai (menempel ke yang
            # sudah jalan / preferensi terakhir) untuk sesi berikutnya.
            try:
                if self.browser_var.get() == "Otomatis" and self.bot.BROWSER:
                    exe = self.bot.BROWSER.get("exe", "")
                    if exe and exe != self._last_browser_path:
                        self._last_browser_path = exe
                        self._save_settings()
                    self.root.after(0, self._update_browser_chip)
            except Exception:
                pass
            self.bot.main_loop()
        except SystemExit:
            if self.bot and self.bot.STOP:
                self._log("Bot dihentikan.")
            else:
                self._log("Gagal menyambung ke browser.")
                self._log("Tutup semua jendela browser, lalu klik Start lagi.")
        except BaseException as ex:
            self._log(f"[GUI] bot berhenti: {ex}")
        finally:
            # Putuskan Playwright supaya Start berikutnya koneksi bersih
            # dari thread baru (objek Playwright tidak boleh lintas thread).
            try:
                self.bot.disconnect()
                self._log("Bot berhenti. Klik Start untuk mulai lagi.")
            except Exception:
                pass
        self.bot_thread = None


    def on_pause(self):
        if self.bot:
            self.bot.PAUSED = not self.bot.PAUSED


    def on_stop(self):
        if self.bot:
            self.bot.STOP = True
            self.bot.PAUSED = False
            self._tunggu_pilih_halaman = False
            self.bot.AWAIT_RANGE = False
            self._log("Bot sedang berhenti... kalau masih menyambung, "
              "tunggu beberapa detik.")


    def on_speed(self, _=None):
        if not self.bot:
            return
        idx = {"Normal (140)": 0, "Cepat (200)": 1, "Santai (85)": 2}.get(self.speed_var.get(), 0)
        self.bot.SPEED_IDX = idx
