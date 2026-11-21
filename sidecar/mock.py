"""Backend palsu yang meniru bot sungguhan - buat bangun & screenshot UI
tanpa Windows/edclub. Semua alur ada: mulai, jeda, ganti akun (cover),
lisensi, update, lapor bug, + dev.simulate buat memicu dialog/ask."""
import random
import threading
import time

from .backend import Backend, SPEED_TIERS
from .server import RpcError

_KINDS = ["standard", "standard", "game", "standard", "video", "ocr"]
_KIND_NAME = {"standard": "Pelajaran", "game": "Game", "video": "Video",
              "ocr": "Ketik dari gambar"}


class MockBackend(Backend):
    def __init__(self, version="4.0.0-dev1"):
        super().__init__()
        s = self.snapshot
        s.update("app", version=version, platform="mock", mode="mock")
        s.update("account", active="zafran",
                 list=[{"name": "zafran", "email": "zafran@sekolah.id"},
                       {"name": "budi.s", "email": "budi.s@sekolah.id"}])
        s.update("license", state="ok", nickname="Zafran", days_left=27)
        s.update("range", start=87, end=120, mapped=640, total=685,
                 position=86)
        s.update("level", num=86, label="L86")
        s.update("plan", segments=[
            {"from": 87, "to": 100, "stars": 5, "silver": True},
            {"from": 101, "to": 140, "stars": 5, "silver": False},
            {"from": 141, "to": 180, "stars": 4, "silver": False},
            {"from": 181, "to": 0, "stars": 3, "silver": False},
        ])
        self._run = threading.Event()     # set = jalan
        self._stop = threading.Event()
        self._thr = None
        self._settings = {"speed": 400, "hotkey": True}
        # cek update otomatis saat boot (seperti app asli)
        threading.Timer(3.0, self.m_update_check).start()

    # -------------------------------------------------------------- rencana
    # bagian yg mulai <= level kini + JARAK_KUNCI terkunci selama bot jalan
    JARAK_KUNCI = 2

    def batas_kunci(self):
        """Level tertinggi yg bagiannya terkunci (None = tak ada kunci)."""
        if self.snapshot.get("bot")["phase"] not in ("starting", "running",
                                                       "paused", "stopping"):
            return None
        return self.snapshot.get("level")["num"] + self.JARAK_KUNCI

    def m_plan_set(self, segments):
        bersih = []
        for sg in segments:
            a, b = int(sg["from"]), int(sg.get("to") or 0)
            st = max(1, min(5, int(sg.get("stars", 5))))
            if a < 1 or (b and b < a):
                raise RpcError("bad_input", f"Rentang {a}-{b} tidak valid.")
            if bersih and (bersih[-1]["to"] == 0 or a <= bersih[-1]["to"]):
                raise RpcError("bad_input",
                               "Bagian harus berurutan dan tidak tumpang tindih.")
            bersih.append({"from": a, "to": b, "stars": st,
                           "silver": bool(sg.get("silver")) and st == 5})
        batas = self.batas_kunci()
        if batas is not None:
            lama = [x for x in self.snapshot.get("plan")["segments"]
                    if x["from"] <= batas]
            if bersih[:len(lama)] != lama:
                raise RpcError("locked", "Bagian yang sedang dikerjakan "
                               "belum bisa diubah. Stop dulu ya.")
            self.snapshot.update("plan", segments=bersih)
            return {"segments": bersih}
        self.snapshot.update("plan", segments=bersih, active=None,
                             done_in_active=0)
        return {"segments": bersih}

    def _segmen(self, num):
        for i, sg in enumerate(self.snapshot.get("plan")["segments"]):
            if num >= sg["from"] and (sg["to"] == 0 or num <= sg["to"]):
                return i, sg
        return None, None

    # ---------------------------------------------------------------- bot
    def m_bot_start(self, range=None):
        s = self.snapshot
        if s.get("bot")["phase"] in ("running", "paused", "starting"):
            raise RpcError("busy", "Bot sudah jalan.")
        if s.get("license")["state"] != "ok":
            raise RpcError("license", "Aktifkan lisensi dulu ya.")
        segs = s.get("plan")["segments"]
        if range is None and segs:
            range = {"mode": "custom", "start": segs[0]["from"],
                     "end": segs[-1]["to"]}
        if range is None:
            r = s.get("range")
            range = self.ask("range.pick", r, timeout=120,
                             default={"mode": "cancel"})
        if not range or range.get("mode") == "cancel":
            return {"started": False}
        if range.get("mode") == "custom":
            s.update("range", start=int(range["start"]),
                     end=int(range.get("end") or 0))
        elif range.get("mode") == "lanjut":
            pos = s.get("range")["position"]
            s.update("range", start=pos + 1, end=0)
        s.update("bot", phase="starting", error="")
        s.update("activity", headline="Menyiapkan",
                 sub="Menghubungkan ke halaman edclub...")
        self._stop.clear()
        self._run.set()
        s.update("stats", started_at=time.time())
        self._thr = threading.Thread(target=self._loop, daemon=True)
        self._thr.start()
        return {"started": True}

    def m_bot_pause(self):
        if self.snapshot.get("bot")["phase"] == "running":
            self._run.clear()
            self.snapshot.update("bot", phase="paused")
            self.snapshot.update("activity", headline="Dijeda",
                                 sub="Tekan Lanjut atau F9.")
            self.log("[GUI] jeda", "Bot dijeda")
        return {}

    def m_bot_resume(self):
        if self.snapshot.get("bot")["phase"] == "paused":
            self._run.set()
            self.snapshot.update("bot", phase="running")
            self.log("[GUI] lanjut", "Bot lanjut lagi")
        return {}

    def m_bot_stop(self):
        ph = self.snapshot.get("bot")["phase"]
        if ph in ("running", "paused", "starting"):
            self.snapshot.update("bot", phase="stopping")
            self._stop.set()
            self._run.set()
        return {}

    def m_bot_recover(self):
        self.log("[RECOVERY] muat ulang lesson", "Memulihkan pelajaran...")
        return {}

    def _loop(self):
        s = self.snapshot
        time.sleep(1.2)
        s.update("bot", phase="running")
        num = s.get("range")["start"]
        while not self._stop.is_set():
            end = s.get("range")["end"]
            if end and num > end:
                s.update("bot", phase="done")
                s.update("plan", active=None, lock_until=None)
                s.update("activity", headline="Selesai!",
                         sub=f"Semua level sampai L{end} beres.")
                self.log("Selesai. Total: rentang tuntas",
                         "Rentang selesai")
                return
            idx, seg = self._segmen(num)
            if s.get("plan")["segments"] and seg is None:
                num += 1          # di luar rencana: lewati
                continue
            s.update("plan", lock_until=num + self.JARAK_KUNCI)
            if idx != s.get("plan")["active"]:
                s.update("plan", active=idx, done_in_active=0)
            kind = _KINDS[num % len(_KINDS)]
            s.update("level", num=num, label=f"L{num}", kind=kind,
                     url=f"https://www.edclub.com/sportal/program-3/{num}"
                         ".play", progress=0.0)
            s.update("activity", headline=f"Level {num}",
                     sub=f"{_KIND_NAME[kind]} sedang dikerjakan otomatis.")
            self.log(f"[LEVEL] {num} ({kind}) mulai",
                     f"Mulai level {num}")
            chars = random.randint(120, 420)
            wpm = s.get("speed")["wpm"]
            dur = max(2.5, min(9.0, chars / (wpm * 5 / 60)))
            t0 = time.time()
            while True:
                if self._stop.is_set():
                    break
                self._run.wait()
                frac = min(1.0, (time.time() - t0) / dur)
                s.update("level", progress=round(frac, 3))
                if frac >= 1.0:
                    break
                time.sleep(0.1)
            if self._stop.is_set():
                break
            st = s.get("stats")
            s.update("stats", levels_done=st["levels_done"] + 1,
                     chars=st["chars"] + chars)
            s.update("range", position=num)
            stars = seg["stars"] if seg else random.choice([5, 5, 4])
            s.update("plan", done_in_active=s.get("plan")["done_in_active"] + 1)
            self.emit("level.result", {"level": num, "wpm": wpm,
                                       "acc": 100.0, "stars": stars})
            self.log(f"[Standard] L{num} selesai {stars} bintang",
                     f"Level {num} selesai, {stars} bintang")
            num += 1
        s.update("bot", phase="idle")
        s.update("plan", active=None, done_in_active=0, lock_until=None)
        s.update("level", progress=0.0)
        s.update("activity", headline="Berhenti",
                 sub="Klik Mulai untuk mulai lagi.")
        self.log("[GUI] bot berhenti", "Bot berhenti")

    # -------------------------------------------------------- setting kecil
    def m_speed_set(self, wpm, save=True):
        wpm = max(40, min(400, int(wpm)))
        self.snapshot.update("speed", wpm=wpm)
        if save:
            self._settings["speed"] = wpm
        return {"wpm": wpm}

    def m_hotkeys_set(self, on):
        self.snapshot.update("hotkeys", on=bool(on))
        self._settings["hotkey"] = bool(on)
        return {}

    def m_range_get(self):
        return self.snapshot.get("range")

    def m_levels_build_map(self):
        def kerja():
            for i in range(0, 686, 45):
                self.snapshot.update("activity", headline="Memetakan level",
                                     sub=f"{i}/685 level terpetakan")
                time.sleep(0.15)
            self.snapshot.update("range", mapped=685)
            self.snapshot.update("activity", headline="Siap",
                                 sub="Peta level lengkap.")
        threading.Thread(target=kerja, daemon=True).start()
        return {}

    def m_login_open(self, kind="individu"):
        self.snapshot.update("bot", needs_login=False)
        self.log(f"[LOGIN] buka halaman login {kind}",
                 "Membuka halaman login")
        return {}

    # ---------------------------------------------------------------- akun
    def m_acct_list(self):
        return self.snapshot.get("account")

    def _cover(self, phase, teks, dur=2.4):
        s = self.snapshot
        s.update("cover", visible=True, phase=phase, text=teks, progress=0.0)
        n = 24
        for i in range(1, n + 1):
            time.sleep(dur / n)
            s.update("cover", progress=round(i / n, 3))
        s.update("cover", visible=False, progress=None)

    def m_acct_switch(self, name):
        a = self.snapshot.get("account")
        if name not in [x["name"] for x in a["list"]]:
            raise RpcError("not_found", "Akun tidak ditemukan.")
        if self.snapshot.get("bot")["phase"] in ("running", "paused"):
            raise RpcError("busy", "Hentikan bot dulu sebelum ganti akun.")
        self._cover("switch", f"Pindah ke {name}...")
        self.snapshot.update("account", active=name)
        self.log(f"[AKUN] aktif: {name}", f"Sekarang pakai akun {name}")
        return {}

    def m_acct_add(self):
        self._cover("oauth", "Membuka login Google...", 1.6)
        return {"pending_login": True}

    def m_acct_remove(self, name):
        a = self.snapshot.get("account")
        lst = [x for x in a["list"] if x["name"] != name]
        act = a["active"] if a["active"] != name else (
            lst[0]["name"] if lst else "")
        self.snapshot.update("account", list=lst, active=act)
        return {}

    def m_acct_logout(self):
        self.snapshot.update("account", needs_relogin=True)
        self.snapshot.update("bot", needs_login=True)
        return {}

    # ------------------------------------------------------------- lisensi
    def m_license_request(self, nickname):
        nickname = (nickname or "").strip()
        if len(nickname) < 2:
            raise RpcError("bad_input", "Nama panggilan minimal 2 huruf.")
        self.snapshot.update("license", state="pending", nickname=nickname,
                             message="Menunggu persetujuan pemilik...")

        def setuju():
            time.sleep(4)
            self.snapshot.update("license", state="ok", days_left=30,
                                 message="")
        threading.Thread(target=setuju, daemon=True).start()
        return {}

    def m_license_refresh(self):
        return self.snapshot.get("license")

    # -------------------------------------------------------------- update
    def m_update_check(self):
        self.snapshot.update(
            "update", available=True, version="3.6.0", size=88_400_000,
            notes="## Fixes in 3.6.0\n- **New look**: rebuilt in Flutter.\n"
                  "- **Smoother switching** between accounts.")
        return self.snapshot.get("update")

    def m_update_download(self):
        def kerja():
            u = self.snapshot
            u.update("update", phase="downloading", progress=0.0)
            for i in range(1, 41):
                if u.get("update")["phase"] != "downloading":
                    return
                time.sleep(0.12)
                u.update("update", progress=round(i / 40, 3))
            u.update("update", phase="ready")
        threading.Thread(target=kerja, daemon=True).start()
        return {}

    def m_update_cancel(self):
        self.snapshot.update("update", phase="idle", progress=0.0)
        return {}

    def m_update_install(self):
        if self.snapshot.get("update")["phase"] != "ready":
            raise RpcError("not_ready", "Unduhan belum selesai.")
        self.log("[UPDATE] pasang & mulai ulang", "Memasang pembaruan...")
        return {"restarting": True}

    # ---------------------------------------------------------------- lain
    def m_report_send(self, category, text):
        if not (text or "").strip():
            raise RpcError("bad_input", "Ceritakan sedikit masalahnya ya.")
        time.sleep(0.8)
        return {"sent": True}

    def m_log_tail(self, n=100):
        return {"lines": []}

    def m_settings_get(self):
        return dict(self._settings)

    def m_settings_set(self, **kv):
        self._settings.update(kv)
        return dict(self._settings)

    def m_dev_info(self):
        return {"version": self.snapshot.get("app")["version"],
                "data_dir": "/mock/TypingBot", "python": "mock",
                "tiers": SPEED_TIERS}

    def m_dev_open(self, what):
        return {}

    def m_dev_reset_settings(self):
        self._settings = {"speed": 400, "hotkey": True}
        return {}

    def m_web_visible(self, on):
        return {}

    def m_app_quit(self):
        return {}

    def m_dev_simulate(self, what):
        """Picu dialog/ask buat uji UI (khusus mock)."""
        s = self.snapshot
        if what == "login":
            s.update("bot", needs_login=True)
            r = self.ask("login.needed", {}, default={"kind": None})
            s.update("bot", needs_login=False)
            return {"answer": r}
        if what == "locked":
            return {"answer": self.ask("level.locked", {"level": 312},
                                       default={"skip": False})}
        if what == "next":
            return {"answer": self.ask("level.next", {"level": 99},
                                       default={"wait": True})}
        if what == "force_close":
            return {"answer": self.ask(
                "browser.force_close", {"name": "Brave", "pid": 4412},
                default={"ok": False})}
        if what == "error":
            s.update("bot", phase="error", error="Halaman edclub tidak merespons.")
            return {}
        if what == "license":
            s.update("license", state="need", days_left=None)
            return {}
        if what == "boot":
            threading.Thread(target=self._cover,
                             args=("boot", "Menyiapkan edclub..."),
                             daemon=True).start()
            return {}
        raise RpcError("bad_input", what)
