"""
bot_gui.py - Antarmuka grafis untuk TypingClub Autopilot.

Tampilan ala auto-clicker: tombol Start/Pause/Stop, pilihan kecepatan,
log aktivitas live, dan status bot. Bot tetap bisa dikontrol lewat hotkey
global (F9/F10/F11) walau jendela ini diminimize.

Log juga disalin ke bot.log di sebelah program ini (berguna untuk
mendiagnosis kalau ada masalah).
"""

import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

LOG_FILE = os.path.join(BASE_DIR, "bot.log")

BG = "#1e1f24"
FG = "#e8e8ec"
ACCENT = "#4f8cff"
ACCENT_DIM = "#2d4a80"
GREEN = "#3ecf6e"
YELLOW = "#f0c04a"
RED = "#e05555"
PANEL = "#26282f"
BTN_FG = "#101116"


class App:
    def __init__(self, root):
        self.root = root
        self.bot = None
        self.bot_thread = None
        self.log_q = queue.Queue()
        self.log_file = None

        root.title("TypingClub Autopilot")
        root.geometry("760x520")
        root.minsize(620, 420)
        root.configure(bg=BG)

        try:
            root.attributes("-topmost", True)
            root.attributes("-topmost", False)
        except Exception:
            pass

        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # ---------- baris status ----------
        status = tk.Frame(root, bg=BG)
        status.pack(fill="x", padx=14, pady=(12, 6))

        self.state_lbl = tk.Label(status, text="⏻ Siap", font=("Segoe UI", 15, "bold"),
                                  fg=FG, bg=BG)
        self.state_lbl.pack(side="left")

        self.lesson_lbl = tk.Label(status, text="", font=("Segoe UI", 10), fg="#9aa0ab",
                                   bg=BG)
        self.lesson_lbl.pack(side="left", padx=(12, 0), pady=(5, 0))

        # ---------- baris kontrol ----------
        ctrl = tk.Frame(root, bg=BG)
        ctrl.pack(fill="x", padx=14, pady=(4, 8))

        self.btn_start = self._btn(ctrl, "▶  Start", GREEN, self.on_start)
        self.btn_pause = self._btn(ctrl, "⏸  Pause", YELLOW, self.on_pause)
        self.btn_pause["state"] = "disabled"
        self.btn_stop = self._btn(ctrl, "⏹  Stop", RED, self.on_stop)
        self.btn_stop["state"] = "disabled"

        speedbox = tk.Frame(ctrl, bg=BG)
        speedbox.pack(side="right")
        tk.Label(speedbox, text="Kecepatan:", font=("Segoe UI", 10), fg="#9aa0ab",
                 bg=BG).pack(side="left", padx=(0, 6))
        self.speed_var = tk.StringVar(value="Normal")
        self.speed_cbox = ttk.Combobox(speedbox, textvariable=self.speed_var,
                                       state="readonly", width=8,
                                       values=("Normal", "Cepat", "Santai"))
        self.speed_cbox.pack(side="left")
        self.speed_cbox.bind("<<ComboboxSelected>>", self.on_speed)

        # ---------- log ----------
        logbox = tk.Frame(root, bg=PANEL)
        logbox.pack(fill="both", expand=True, padx=14, pady=(2, 8))

        self.log = ScrolledText(logbox, bg=PANEL, fg="#c7cbd4", relief="flat",
                                font=("Consolas", 9), state="disabled", wrap="word",
                                borderwidth=0, highlightthickness=0)
        self.log.pack(fill="both", expand=True, padx=1, pady=1)

        # ---------- footer ----------
        tk.Label(root, text="Hotkey global:  F9 jeda/lanjut   •   F10 kecepatan   •   "
                            "F11 stop        Log: bot.log",
                 font=("Segoe UI", 9), fg="#6b7280", bg=BG).pack(fill="x", pady=(0, 8))

        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._log("Selamat datang! Klik Start untuk menghubungkan ke Brave.")
        threading.Thread(target=self._load_bot, daemon=True).start()
        self.root.after(150, self._poll)

    # ------------------------------------------------------------------ UI util

    def _btn(self, parent, text, color, cmd):
        b = tk.Label(parent, text=text, font=("Segoe UI", 10, "bold"), fg=BTN_FG,
                     bg=color, padx=16, pady=6, cursor="hand2")
        b.pack(side="left", padx=(0, 8))

        def on_enter(_):
            if str(b["state"]) != "disabled":
                b.configure(bg=self._dim(color, 0.88))

        def on_leave(_):
            if str(b["state"]) != "disabled":
                b.configure(bg=color)

        b.bind("<Enter>", on_enter)
        b.bind("<Leave>", on_leave)
        b.bind("<Button-1>", lambda e: self._safe(cmd))
        b._base_color = color
        return b

    @staticmethod
    def _dim(hex_color, f):
        r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
        return f"#{int(r * f):02x}{int(g * f):02x}{int(b * f):02x}"

    def _set_state(self, text, color):
        self.state_lbl.configure(text=text, fg=color)

    def _safe(self, cmd):
        try:
            cmd()
        except Exception as ex:
            self._log(f"[GUI] error: {ex}")

    # ------------------------------------------------------------------ logging

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

    def _log(self, line):
        self.log_q.put(line)

    def _poll(self):
        try:
            while True:
                line = self.log_q.get_nowait()
                self.log.configure(state="normal")
                self.log.insert("end", line + "\n")
                if float(self.log.index("end-1c").split(".")[0]) > 800:
                    self.log.delete("1.0", "200.0")
                self.log.see("end")
                self.log.configure(state="disabled")
        except queue.Empty:
            pass

        bot = self.bot
        if bot:
            url = getattr(bot, "STATUS_URL", "")
            name = ""
            m = re.search(r"/program-\d+/(\d+)\.play", url)
            if m:
                # URL program-3 di-offset: level 1 = /116.play, jadi -115
                try:
                    name = f"Level {int(m.group(1)) - 115}"
                except ValueError:
                    name = url.rstrip("/").split("/")[-1]
            elif ".game" in url:
                name = "Daftar pelajaran"
            self.lesson_lbl.configure(text=name)

            if bot.STOP:
                self._set_state("⏹ Berhenti", RED)
            elif bot.PAUSED:
                self._set_state("⏸ Jeda", YELLOW)
            else:
                self._set_state("● Berjalan", GREEN)

            self.btn_pause.configure(
                text="⏸  Pause" if not bot.PAUSED else "▶  Lanjut")
            self.btn_pause["state"] = "normal" if self.bot_thread else "disabled"
            self.btn_stop["state"] = "normal" if self.bot_thread else "disabled"
            self.btn_start["state"] = "disabled" if self.bot_thread else "normal"

        self.root.after(150, self._poll)

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
            self._log("Modul bot dimuat. Klik Start untuk mulai.")
        except Exception as ex:
            self._log(f"GAGAL memuat bot: {ex}")

    def on_start(self):
        bot = self.bot
        if not bot or self.bot_thread:
            return
        bot.STOP = False
        bot.PAUSED = False
        self.bot_thread = threading.Thread(target=self._run_bot, daemon=True)
        self.bot_thread.start()

    def _run_bot(self):
        try:
            self.bot.connect()
            self.bot.main_loop()
        except SystemExit:
            self._log("GAGAL: Brave debug tidak bisa disambung (port 9222).")
            self._log("Tutup semua Brave lalu klik Start lagi.")
        except BaseException as ex:
            self._log(f"[GUI] bot berhenti: {ex}")
        self.bot_thread = None

    def on_pause(self):
        if self.bot:
            self.bot.PAUSED = not self.bot.PAUSED

    def on_stop(self):
        if self.bot:
            self.bot.STOP = True
            self.bot.PAUSED = False

    def on_speed(self, _=None):
        if not self.bot:
            return
        idx = {"Normal": 0, "Cepat": 1, "Santai": 2}.get(self.speed_var.get(), 0)
        self.bot.SPEED_IDX = idx

    def on_close(self):
        if self.bot:
            self.bot.STOP = True
            self.bot.PAUSED = False
        time.sleep(0.2)
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    try:
        from tkinter import font as tkfont
        default_font = tkfont.nametofont("TkDefaultFont")
        default_font.configure(family="Segoe UI", size=10)
    except Exception:
        pass
    App(root)
    root.mainloop()
