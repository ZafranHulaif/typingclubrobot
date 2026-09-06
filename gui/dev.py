"""Jendela utama - bagian dev."""

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

from .dialogs import dialog_open_browser, dialog_pick_browser
from .licensing import _machine_code, _load_online_token
from net import api as netapi
from net import license as netlic
from .theme import (ACCENT, APP_VERSION, BASE_DIR, BG, CARD, CARD_HOVER, DIM, EDGE, FAINT, FG, GREEN, LICENSE_FILE, LOG_FILE, PANEL, CREATOR, PROGRAM_PATH, SETTINGS_FILE, _build_stamp)


class DevMixin:
    """Mixin: dipadukan di gui/app.py."""


    # ------------------------------------------------------------- dev window

    # ------------------------------------------------------ dev (tersembunyi)

    def _dev_gesture(self, _e=None):
        """Klik teks versi 5x dalam 3 detik -> buka jendela Dev."""
        now = time.time()
        self._dev_klik = [t for t in self._dev_klik if now - t < 3]
        self._dev_klik.append(now)
        if len(self._dev_klik) >= 5:
            self._dev_klik = []
            self.on_dev()


    def on_dev(self):
        """Gerbang kode dulu (nama pembuat aplikasi), baru jendela
        developer - user yang tak sengaja klik 5x tidak melihat hal
        teknis apa pun."""
        if not self._dev_gate():
            return
        self._dev_buka_jendela()

    def _dev_gate(self):
        if getattr(self, "_dev_unlocked", False):
            return True
        from .dialogs import dialog_dev_code
        try:
            ok = bool(dialog_dev_code(self.root))
        except Exception:
            ok = False
        if ok:
            self._dev_unlocked = True
            self._log("[Dev] kode diterima - area developer terbuka.")
        return ok

    def _dev_uji_anim(self):
        """Pratinjau animasi UI: orb melayang (menunggu persetujuan)
        dan centang yang menggambar sendiri (saat disetujui)."""
        from . import anim
        from .widgets import gelap_titlebar_berulang
        win = tk.Toplevel(self.root)
        win.title("Pratinjau animasi")
        win.withdraw()
        win.configure(bg=PANEL)
        kan = tk.Canvas(win, bg=PANEL, highlightthickness=0,
                        width=430, height=300)
        kan.pack(fill="both", expand=True)
        kaki = tk.Frame(win, bg=PANEL)
        kaki.pack(fill="x", padx=18, pady=(10, 16))
        stan = {"orbs": None, "cek": None}

        def _tombol(teks, cmd, warna, primer=True):
            b = tk.Label(kaki, text=teks, font=("Segoe UI", 10, "bold"),
                         fg="#101116" if primer else FG,
                         bg=warna if primer else CARD, padx=18, pady=7,
                         cursor="hand2", highlightthickness=1,
                         highlightbackground=EDGE if not primer else 0)
            b.pack(side="left", padx=(0, 8))
            b.bind("<Button-1>", lambda e: self._safe(cmd))
            return b

        def _orbs_mulai():
            try:
                kan.delete("all")
            except Exception:
                pass
            stan["orbs"] = anim.attach_orbs(kan, tinggi=None)

        def _cek_mulai():
            if stan["orbs"]:
                try:
                    stan["orbs"].stop()
                except Exception:
                    pass
            try:
                kan.delete("all")
            except Exception:
                pass
            stan["cek"] = anim.PlayCheck(kan, durasi=1.1)
            stan["cek"].start()

        _tombol("✓  Disetujui", _cek_mulai, GREEN)
        _tombol("↻  Orb menunggu", _orbs_mulai, ACCENT, primer=False)

        _orbs_mulai()
        gelap_titlebar_berulang(win)
        win.update_idletasks()
        try:
            sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
            win.geometry(f"+{max((sw - 430) // 2, 8)}"
                         f"+{max((sh - 380) // 3, 40)}")
        except Exception:
            pass
        win.deiconify()
        try:
            win.attributes("-topmost", True)
            win.lift()
        except Exception:
            pass

    def _dev_buka_jendela(self):
        win = tk.Toplevel(self.root)
        win.title(f"TypingBot {APP_VERSION} - Developer")
        win.geometry("620x680")
        win.minsize(480, 460)
        win.configure(bg=PANEL)
        try:
            win.attributes("-topmost", True)
        except Exception:
            pass
        from .widgets import ScrollbarGelap, gelap_titlebar_berulang
        gelap_titlebar_berulang(win)
        info = self._dev_info()

        kepala = tk.Frame(win, bg=PANEL)
        kepala.pack(fill="x", padx=18, pady=(16, 0))
        tk.Label(kepala, text="Developer",
                 font=("Segoe UI", 15, "bold"), fg=FG, bg=PANEL).pack(
                     side="left")
        tk.Label(kepala, text=f"oleh {CREATOR}   •   {_build_stamp()}",
                 font=("Segoe UI", 9), fg=DIM, bg=PANEL).pack(
                     side="left", padx=(10, 0), pady=(8, 0))

        # "Hasil aksi": cermin log aplikasi yang SELALU terlihat di
        # jendela dev (log utama sering tertutup jendela dev yang
        # topmost - dulu tombol terasa tidak melakukan apa-apa)
        kaki = tk.Frame(win, bg=PANEL)
        kaki.pack(side="bottom", fill="x")
        tk.Frame(kaki, bg=EDGE, height=1).pack(fill="x", padx=18)

        # "Hasil aksi": cermin log aplikasi yang bisa dilipat -
        # tertutup secara default, dibuka hanya saat ingin memeriksa
        # (log utama sering tertutup jendela dev yang topmost - dulu
        # tombol terasa tidak melakukan apa-apa)
        badan_hasil = tk.Frame(kaki, bg=PANEL)
        kotak_txt = tk.Frame(badan_hasil, bg=BG)
        hasil_txt = tk.Text(kotak_txt, bg=BG, fg="#c7cbd4", relief="flat",
                            font=("Consolas", 9), height=8,
                            state="disabled", wrap="word",
                            borderwidth=0, highlightthickness=0)
        hasil_txt.pack(side="left", fill="both", expand=True)
        gulir_hasil = ScrollbarGelap(kotak_txt, hasil_txt.yview)
        hasil_txt.configure(yscrollcommand=gulir_hasil.set)
        gulir_hasil.pack(side="right", fill="y")
        kotak_txt.pack(fill="x", padx=18, pady=(0, 10))
        hasil_buka = {"ok": False}

        def _toggle_hasil(_e=None):
            hasil_buka["ok"] = not hasil_buka["ok"]
            if hasil_buka["ok"]:
                badan_hasil.pack(fill="x")
                hasil_kepala.configure(text="▾ Hasil aksi (log aplikasi)")
                hasil_txt.see("end")
            else:
                badan_hasil.pack_forget()
                hasil_kepala.configure(text="▸ Hasil aksi (log aplikasi)")

        hasil_kepala = tk.Label(kaki, text="▸ Hasil aksi (log aplikasi)",
                                font=("Segoe UI", 9, "bold"), fg=DIM,
                                bg=PANEL, cursor="hand2", padx=4, pady=4)
        hasil_kepala.pack(anchor="w", padx=18)
        hasil_kepala.bind("<Button-1>", _toggle_hasil)
        log_q_dev = queue.Queue()
        asli_log = self._log
        mirror_terpasang = getattr(self, "_dev_log_pasang", False)

        def _log_mirror(line):
            asli_log(line)
            log_q_dev.put(line)

        if not mirror_terpasang:
            self._log = _log_mirror
            self._dev_log_pasang = True

        def _kuras():
            try:
                while True:
                    ln = log_q_dev.get_nowait()
                    hasil_txt.configure(state="normal")
                    hasil_txt.insert("end", ln + "\n")
                    if int(hasil_txt.index("end-1c").split(".")[0]) > 120:
                        hasil_txt.delete("1.0", "40.0")
                    hasil_txt.see("end")
                    hasil_txt.configure(state="disabled")
            except queue.Empty:
                pass
            except Exception:
                pass
            try:
                win.after(250, _kuras)
            except Exception:
                pass

        win.after(250, _kuras)

        def _tutup_dev():
            self._log = asli_log
            self._dev_log_pasang = False
            try:
                win.destroy()
            except Exception:
                pass

        win.protocol("WM_DELETE_WINDOW", _tutup_dev)

        # panel gulir: tombol tidak pernah terpotong saat jendela
        # dikecilkan (dulu: baris tombol fixed terpotong di sisi kanan)
        kanvas = tk.Canvas(win, bg=PANEL, highlightthickness=0)
        gulir = ScrollbarGelap(win, kanvas.yview)
        kanvas.configure(yscrollcommand=gulir.set)
        gulir.pack(side="right", fill="y")
        kanvas.pack(side="left", fill="both", expand=True)
        dalam = tk.Frame(kanvas, bg=PANEL)
        id_dalam = kanvas.create_window((0, 0), window=dalam, anchor="nw")
        dalam.bind("<Configure>", lambda e: kanvas.configure(
            scrollregion=kanvas.bbox("all")))
        kanvas.bind("<Configure>", lambda e: kanvas.itemconfigure(
            id_dalam, width=e.width))

        def _roda(e):
            kanvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        kanvas.bind("<Enter>",
                    lambda e: kanvas.bind_all("<MouseWheel>", _roda))
        kanvas.bind("<Leave>",
                    lambda e: kanvas.unbind_all("<MouseWheel>"))

        def seksi(judul):
            tk.Label(dalam, text=judul.upper(),
                     font=("Segoe UI", 9, "bold"), fg=ACCENT,
                     bg=PANEL).pack(anchor="w", padx=18, pady=(14, 4))

        def baris(ikon, judul, desk, cmd):
            w = tk.Frame(dalam, bg=CARD, highlightthickness=1,
                         highlightbackground=EDGE, cursor="hand2")
            w.pack(fill="x", padx=18, pady=3)
            ic = tk.Label(w, text=ikon, font=("Segoe UI Emoji", 14),
                          bg=CARD, width=3, cursor="hand2")
            ic.pack(side="left", padx=(8, 0), pady=8)
            kotak = tk.Frame(w, bg=CARD)
            kotak.pack(side="left", fill="x", expand=True, pady=7)
            judul_lbl = tk.Label(kotak, text=judul,
                                 font=("Segoe UI", 10, "bold"), fg=FG,
                                 bg=CARD, cursor="hand2")
            judul_lbl.pack(anchor="w")
            desk_lbl = tk.Label(kotak, text=desk, font=("Segoe UI", 9),
                                fg=DIM, bg=CARD, wraplength=440,
                                justify="left", cursor="hand2")
            desk_lbl.pack(anchor="w")
            semua = (w, ic, kotak, judul_lbl, desk_lbl)

            def masuk(_e):
                for x in semua:
                    x.configure(bg=CARD_HOVER)
                w.configure(highlightbackground=ACCENT)

            def keluar(_e):
                for x in semua:
                    x.configure(bg=CARD)
                w.configure(highlightbackground=EDGE)

            def klik(_e=None):
                # umpan balik kilat: log utama sering tertutup jendela
                # dev yang topmost, tanpa ini klik terasa tidak bekerja
                for x in semua:
                    x.configure(bg=ACCENT)
                w.after(140, keluar, None)
                self._safe(cmd)

            for x in semua:
                x.bind("<Button-1>", klik)
                x.bind("<Enter>", masuk)
                x.bind("<Leave>", keluar)

        seksi("Diagnosis")
        baris("📋", "Salin info",
              "Seluruh diagnosis build ini (versi, lisensi, browser) ke clipboard.",
              lambda: self._dev_salin(info))
        baris("📝", "Buka bot.log",
              "Catatan jalannya aplikasi - tempat pertama mencari masalah.",
              lambda: self._dev_buka(LOG_FILE))
        baris("📂", "Buka folder data",
              "Folder pengaturan, lisensi, dan log aplikasi.",
              lambda: self._dev_buka(BASE_DIR))
        baris("♻", "Reset pengaturan",
              "Hapus pengaturan tersimpan; popup pilih browser aktif lagi "
              "(lisensi tidak ikut terhapus). Hasilnya lihat di 'Hasil aksi'.",
              self._dev_reset)

        seksi("Uji dialog")
        baris("🧪", "Dialog pilih browser",
              "Buka kartu pilihan browser + profil seperti saat Start.",
              self._dev_uji_pilih)
        baris("🚀", "Dialog buka browser",
              "Uji konfirmasi membuka browser untuk bot.",
              self._dev_uji_buka)

        seksi("Animasi")
        baris("✨", "Pratinjau animasi",
              "Orb melayang halus saat menunggu persetujuan + centang "
              "menggambar sendiri saat disetujui. Gerak berbasis jam "
              "(bukan hitungan frame) - mulus di refresh rate apa pun.",
              self._dev_uji_anim)

        seksi("Lisensi & pembaruan")
        baris("📨", "Minta persetujuan",
              "Uji alur aktivasi penuh: nickname -> menunggu pemilik "
              "menyetujui di halaman admin-nya. Persetujuan yang sama "
              "juga membuka fitur pembaruan.",
              self._ask_online)
        baris("🗑", "Hapus lisensi (uji fresh)",
              "Hapus token LOKAL saja - status di server TIDAK ikut "
              "berubah; kalau mesin masih disetujui, lisensi pulih "
              "sendiri di cek berikutnya.",
              self._dev_hapus_lisensi)
        baris("🔄", "Cek lisensi + pembaruan",
              "Ulangi start-up net: perpanjang token + cek versi baru "
              "(hasilnya di 'Hasil aksi' di bawah).",
              self._dev_net_check)
        baris("⬇", "Cek pembaruan",
              "Hanya cek /api/latest: bila versi sama, memang tidak ada "
              "apa-apa; tombol ⬇ muncul bila ada rilis baru.",
              self._dev_cek_update)
        baris("#️⃣", "Versi 0.0.1 ON/OFF",
              "Tipu versi lokal supaya alur pembaruan bisa diuji.",
              self._dev_toggle_fake_version)

        seksi("Info lengkap")
        teks_info = tk.Text(dalam, bg=BG, fg="#c7cbd4", relief="flat",
                            font=("Consolas", 9), state="normal",
                            wrap="word", borderwidth=0,
                            highlightthickness=0, height=16)
        teks_info.insert("1.0", info)
        teks_info.configure(state="disabled")

        def _toggle_info():
            if teks_info.winfo_ismapped():
                teks_info.pack_forget()
                togg.configure(text="▸ Tampilkan info lengkap")
            else:
                teks_info.pack(fill="x", padx=18, pady=(0, 8))
                teks_info.see("1.0")
                # gulir sampai terlihat - dulu teks terpasang DI BAWAH
                # posisi gulir sehingga seolah tombol tidak melakukan apa-apa
                kanvas.update_idletasks()
                kanvas.yview_moveto(1.0)
                togg.configure(text="▾ Sembunyikan info lengkap")

        togg = tk.Label(dalam, text="▸ Tampilkan info lengkap",
                        font=("Segoe UI", 9, "bold"), fg=FG, bg=CARD,
                        padx=10, pady=6, cursor="hand2", highlightthickness=1,
                        highlightbackground=EDGE)
        togg.pack(fill="x", padx=18, pady=(2, 4))
        togg.bind("<Button-1>", lambda e: self._safe(_toggle_info))


    def _dev_info(self):
        try:
            isi = open(SETTINGS_FILE, encoding="utf-8").read().strip()
        except Exception:
            isi = None
        baris = [
            f"Versi         : TypingBot {APP_VERSION}",
            f"Build         : {_build_stamp()}  (waktu file program dibuat)",
            f"Pembuat       : {CREATOR}  (github.com/{CREATOR})",
            f"Mode          : "
            + ("EXE (PyInstaller)" if getattr(sys, "frozen", False)
               else "skrip Python"),
            f"Lokasi program: {PROGRAM_PATH}",
            f"Folder data   : {BASE_DIR}",
            "",
            f"Lisensi       : "
            + ("AKTIF" if self.lisensi_ok else "BELUM AKTIF")
            + f"  (kode mesin {_machine_code()})",
            f"Lisensi online: {self._dev_lic_info()}",
            f"Server        : {netapi.BASE_URL or '(tidak dikonfigurasi)'}",
            f"Nickname      : {self._load_nickname() or '-'}"
            + (f"  | versi lokal dikira {self._ver_override}"
               if getattr(self, "_ver_override", None) else ""),
            f"Pengaturan    : {SETTINGS_FILE}",
            f"               file ada={os.path.exists(SETTINGS_FILE)}"
            f", isi={isi if isi else '(kosong)'}",
            f"Popup tips    : "
            + ("BELUM pernah - akan muncul saat Start"
               if self._first_run else "sudah pernah tampil"),
            "",
        ]
        if self._detected:
            baris.append("Browser terdeteksi:")
            for n, p in self._detected:
                baris.append(f"  - {n}: {p}")
        else:
            baris.append("Browser terdeteksi: (kosong - modul bot belum termuat?)")
        bot = self.bot
        if bot:
            profil = getattr(bot, "DEDICATED_PROFILE", "")
            baris.append(f"Profil khusus : {profil}  (ada={os.path.isdir(profil)})")
            try:
                peta = json.load(open(bot._LEVEL_MAP_FILE, encoding="utf-8"))
                npeta = len(peta)
            except Exception:
                npeta = 0
            baris.append(f"Peta level    : {bot._LEVEL_MAP_FILE} ({npeta} level tercatat)")
            port_dbg = getattr(bot, "DEBUG_PORT", 9222)
            baris.append(f"Port debug({port_dbg}) : "
                         + ("TERBUKA - browser debug sedang jalan"
                            if bot._check_debug_port() else "kosong"))
            baris.append(f"Patroli login : NEEDS_LOGIN={getattr(bot, 'NEEDS_LOGIN', False)} "
                         f"sentinel_ok={getattr(bot, '_login_sentinel', {}).get('ok', '?')} "
                         f"alasan={getattr(bot, '_login_sentinel', {}).get('alasan', '') or '-'}")
        else:
            baris.append("Modul bot     : BELUM termuat")
        baris.append(f"ENV           : TYPINGBOT_BROWSER="
                     f"{os.environ.get('TYPINGBOT_BROWSER', '(tidak di-set)')}")
        return "\n".join(baris)


    def _dev_salin(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._log("Info developer disalin ke clipboard.")


    def _dev_uji_pilih(self):
        hasil = dialog_pick_browser(self.root, self._detected,
                                     self.browser_var.get(), self._profile)
        self._log(f"[Dev] uji pilih browser: {hasil!r}")


    def _dev_uji_buka(self):
        det = dict(self._detected)
        pilih = self.browser_var.get()
        nm = pilih if pilih in det else (
            (self.bot._find_browser() or {}).get("name", "browser") if self.bot
            else "browser")
        ok = dialog_open_browser(self.root, nm, det.get(nm), "bot")
        self._log(f"[Dev] uji buka browser ({nm}): dijawab "
                  f"{'Ya (buka)' if ok else 'Tidak'}")


    def _dev_reset(self):
        try:
            if os.path.exists(SETTINGS_FILE):
                os.remove(SETTINGS_FILE)
            self._first_run = True
            self.browser_var.set("Otomatis")
            # segarkan kartu browser di GUI utama saat itu juga (dulu:
            # chip masih menampilkan pilihan lama sampai ada aksi lain)
            try:
                self._update_browser_chip()
            except Exception:
                pass
            self._log("Pengaturan dihapus - popup pilih browser aktif lagi. "
                      "(Lisensi tidak ikut terhapus.)")
        except Exception as ex:
            self._log(f"[Dev] gagal reset pengaturan: {ex}")


    def _dev_buka(self, path):
        try:
            os.startfile(path)   # file -> aplikasi default, folder -> explorer
        except Exception as ex:
            self._log(f"[Dev] gagal membuka {path}: {ex}")


    # --------------------------------------------- uji fitur online (v2.7)

    def _dev_lic_info(self):
        tok = _load_online_token()
        if tok and netlic.verify_token(tok):
            return (f"token valid, sisa {netlic.days_left(tok)} hari "
                    f"(exp {time.strftime('%Y-%m-%d', time.localtime(int(tok['exp'])))})")
        if tok:
            return "token ADA tapi kedaluwarsa/tidak valid"
        if self.lisensi_ok:
            return "memakai kunci lama (HMAC manual)"
        return "tidak ada"

    def _dev_net_check(self):
        threading.Thread(target=self._net_worker, daemon=True).start()
        self._log("[Dev] cek lisensi + pembaruan dijalankan (lihat baris [net]).")

    def _dev_hapus_lisensi(self):
        try:
            if os.path.exists(LICENSE_FILE):
                os.remove(LICENSE_FILE)
                self.lisensi_ok = False
                self._title_bar()
                self._log("[Dev] file lisensi dihapus - mesin kini 'fresh'. "
                          "Tekan 'Cek lisensi+update' untuk alur persetujuan "
                          "penuh, atau restart aplikasi.")
            else:
                self._log("[Dev] file lisensi memang tidak ada.")
        except Exception as ex:
            self._log(f"[Dev] gagal hapus lisensi: {ex}")

    def _dev_cek_update(self):
        threading.Thread(target=self._net_update_check, daemon=True).start()
        self._log("[Dev] cek pembaruan dijalankan.")

    def _dev_toggle_fake_version(self):
        if getattr(self, "_ver_override", None):
            self._ver_override = None
            self._log("[Dev] versi lokal kembali normal - cek pembaruan "
                      "akan bilang sudah terbaru.")
        else:
            self._ver_override = "0.0.1"
            self._log("[Dev] versi lokal DIKIRA 0.0.1 - tombol pembaruan "
                      "akan muncul setelah cek. Tekan tombol hijau itu untuk "
                      "uji unduh+verifikasi hash (swap exe hanya di EXE).")
        threading.Thread(target=self._net_update_check, daemon=True).start()
