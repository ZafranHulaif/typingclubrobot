"""Backend ASLI: menghubungkan UI Flutter ke engine/ + net/ (pengganti
gui/launch.py + gui/activity.py lama, tanpa Tk sebagai UI).

Prinsip (lihat docs/architecture/M0-decision.md):
- engine/ TIDAK diubah: kita menulis flag state yang sama seperti GUI lama
  (STOP, LEVEL_START, RANGE_READY, ...) dan membaca state yang sama.
- Satu thread poller (10 Hz) memetakan engine/state.py -> snapshot.
- stdout engine = log; diterjemahkan ramah (gui/translator.py) -> event.
- Semua yang menyentuh WebView2/.NET lewat self.host (win_host.py), yang
  mengantrekan kerja ke thread Tk/STA. Tidak ada callback .NET->Python.
"""
import json
import os
import sys
import threading
import time

from .backend import Backend
from .server import RpcError

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

import paths                                     # noqa: E402
from engine import state                         # noqa: E402

LOG_FILE = paths.data_path("bot.log")
SETTINGS_FILE = paths.data_path("typingbot_settings.json")
COURSE_URL = "https://www.edclub.com/student/course/3"

try:                                    # versi app: satu sumber (gui/theme)
    from gui.theme import APP_VERSION, PROGRAM_PATH
except Exception:                       # non-Windows / tanpa Tk
    APP_VERSION, PROGRAM_PATH = "4.0.0-dev", os.path.abspath(__file__)

try:
    from gui.translator import _friendly_text
except Exception:
    def _friendly_text(line):
        return None


class _LogTee:
    """stdout/stderr -> bot.log + event 'log' (pengganti launch._Writer)."""

    def __init__(self, backend, asli):
        self._be = backend
        self._asli = asli
        self._buf = ""
        self._lock = threading.Lock()

    def write(self, s):
        if not s:
            return
        with self._lock:
            self._buf += s
            if "\n" not in self._buf:
                return
            utuh, self._buf = self._buf.rsplit("\n", 1)
            baris = utuh.split("\n")
        for b in baris:
            b = b.rstrip()
            if not b:
                continue
            try:
                with open(LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(time.strftime("%H:%M:%S ") + b + "\n")
            except Exception:
                pass
            try:
                ramah = _friendly_text(b)
            except Exception:
                ramah = None
            self._be.emit("log", {"t": time.time(), "raw": b[:400],
                                  "friendly": ramah, "level": "info"})

    def flush(self):
        pass

    def isatty(self):
        return False


class EngineBackend(Backend):
    JARAK_KUNCI = 2      # sama dgn mock: bagian <= level+2 terkunci saat jalan

    def __init__(self, host=None):
        super().__init__()
        self.host = host                 # WinHost (Windows) atau None
        self._bot_thread = None
        self._stop_minta = 0.0
        self._tok = None                 # token lisensi online (cache)
        self._update_info = None
        self._update_cancel = False
        self._asked = set()              # ask yg sedang tampil (anti dobel)
        self._settings = self._muat_settings()
        s = self.snapshot
        s.update("app", version=APP_VERSION, platform=sys.platform,
                 mode="engine", embedded_web=host is not None)
        # engine: hotkey global mati total (UI v4 tanpa hotkey)
        state.HOTKEYS_ON = False
        wpm = int(self._settings.get("speed") or 400)
        state.SPEED_WPM = max(40, min(400, wpm))
        s.update("speed", wpm=state.SPEED_WPM)
        s.update("plan", segments=list(self._settings.get("plan") or []))
        sys.stdout = _LogTee(self, sys.__stdout__)
        sys.stderr = _LogTee(self, sys.__stderr__)
        try:
            from engine import browser
            browser.set_confirmer(self._konfirmasi_tutup_browser)
        except Exception:
            pass
        self._akun_refresh()
        self._posisi_refresh()

    # ============================================================ hidup
    def attach(self, server):
        super().attach(server)
        threading.Thread(target=self._poller, daemon=True,
                         name="engine-poll").start()
        threading.Thread(target=self._net_boot, daemon=True,
                         name="net-boot").start()

    # ============================================================ settings
    def _muat_settings(self):
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception:
            return {}

    def _simpan_settings(self, **kv):
        # SATU penulis (dulu 3 tempat menulis tanpa kunci -> balapan)
        self._settings.update(kv)
        try:
            tmp = SETTINGS_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, ensure_ascii=False, indent=1)
            os.replace(tmp, SETTINGS_FILE)
        except Exception as e:
            print(f"[SIDECAR] gagal simpan pengaturan: {e}")

    # ============================================================ poller
    @property
    def _jalan(self):
        t = self._bot_thread
        return bool(t and t.is_alive())

    def _level_kini(self):
        lbl = getattr(state, "STATUS_LABEL", "") or ""
        if lbl.startswith("L") and lbl[1:].isdigit():
            return int(lbl[1:])
        try:
            from engine import levels
            return levels.url_to_level(state.STATUS_URL or "") or 0
        except Exception:
            return 0

    def _fase(self):
        if not self._jalan:
            if state.RANGE_DONE:
                return "done"
            return "idle"
        if state.STOP:
            return "stopping"
        if not state.PAGE:
            return "starting"
        return "running"

    def _poller(self):
        s = self.snapshot
        while True:
            time.sleep(0.1)
            try:
                fase = self._fase()
                s.update("bot", phase=fase,
                         needs_login=bool(state.NEEDS_LOGIN),
                         browser_closed=bool(state.BROWSER_CLOSED),
                         waiting_setup=bool(state.WAITING_SETUP))
                lvl = self._level_kini() if fase in ("running",
                                                    "stopping") else 0
                s.update("level", num=lvl, url=state.STATUS_URL or "",
                         label=state.STATUS_LABEL or "")
                s.update("range", start=int(state.LEVEL_START or 1),
                         end=int(state.LEVEL_END or 0))
                self._plan_tick(fase, lvl)
                self._ask_tick()
                self._login_tick()
            except Exception as e:     # poller tak boleh mati
                print(f"[SIDECAR] poll: {str(e)[:120]}")
                time.sleep(1)

    def _posisi_refresh(self):
        try:
            from engine import levels
            levels.muat_posisi()
            total = len(getattr(state, "_level_map", None) or {}) or 0
            self.snapshot.update("range", position=int(state.POSISI_LEVEL or 0),
                                 total=total, mapped=total)
        except Exception:
            pass

    # ============================================================ rencana
    def _segmen_utk(self, lvl):
        for i, sg in enumerate(self.snapshot.get("plan")["segments"]):
            if lvl >= sg["from"] and (not sg["to"] or lvl <= sg["to"]):
                return i, sg
        return None, None

    def _plan_tick(self, fase, lvl):
        p = self.snapshot.get("plan")
        if fase not in ("running", "stopping") or not lvl:
            if p.get("active") is not None or p.get("lock_until") is not None:
                self.snapshot.update("plan", active=None, lock_until=None,
                                     done_in_active=0)
            return
        i, sg = self._segmen_utk(lvl)
        if i != p.get("active"):
            self.snapshot.update("plan", active=i, done_in_active=0)
        if sg is not None:
            self.snapshot.update("plan", done_in_active=max(0, lvl - sg["from"]))
        self.snapshot.update("plan", lock_until=lvl + self.JARAK_KUNCI)
        # TODO(M3): target bintang per bagian -> atur kecepatan/akurasi
        # engine di sini begitu ambang bintang edclub sudah diriset.

    def m_plan_set(self, segments):
        bersih = []
        for sg in segments:
            a, b = int(sg["from"]), int(sg.get("to") or 0)
            st = max(1, min(5, int(sg.get("stars", 5))))
            if a < 1 or (b and b < a):
                raise RpcError("bad_input", f"Rentang {a}-{b} tidak valid.")
            if bersih and (bersih[-1]["to"] == 0 or a <= bersih[-1]["to"]):
                raise RpcError("bad_input", "Bagian harus berurutan dan "
                               "tidak tumpang tindih.")
            bersih.append({"from": a, "to": b, "stars": st,
                           "silver": bool(sg.get("silver")) and st == 5})
        lock = self.snapshot.get("plan").get("lock_until")
        if self._jalan and lock is not None:
            lama = [x for x in self.snapshot.get("plan")["segments"]
                    if x["from"] <= lock]
            if bersih[:len(lama)] != lama:
                raise RpcError("locked", "Bagian yang sedang dikerjakan "
                               "belum bisa diubah. Stop dulu ya.")
            # akhir rentang ikut rencana baru (bagian depan boleh berubah)
            state.LEVEL_END = bersih[-1]["to"] if bersih else 0
        self.snapshot.update("plan", segments=bersih)
        self._simpan_settings(plan=bersih)
        return {"segments": bersih}

    # ============================================================ bot
    def m_bot_start(self, range=None):
        if self._jalan:
            if state.STOP and time.time() - self._stop_minta > 12:
                print("[SIDECAR] sesi lama tak selesai berhenti - dilepas.")
                self._bot_thread = None
            else:
                raise RpcError("busy", "Bot masih menyiapkan sesi "
                               "sebelumnya. Tunggu sebentar ya.")
        if self.snapshot.get("license")["state"] != "ok":
            raise RpcError("license", "Aktifkan TypingBot dulu ya.")
        self._gerbang_lisensi()
        segs = self.snapshot.get("plan")["segments"]
        if segs:
            mulai, akhir = segs[0]["from"], segs[-1]["to"]
        elif range and range.get("mode") == "custom":
            mulai, akhir = int(range["start"]), int(range.get("end") or 0)
        else:                                # lanjut dari posisi akun
            mulai, akhir = 1, 0
        state.BROWSER_CLOSED = False
        state.STOP = False
        state.PAUSED = False
        state.RANGE_DONE = False
        state.LEVEL_START = mulai
        state.LEVEL_END = akhir
        state._range_jump_done = mulai <= 1
        state.RANGE_READY = True             # rentang sudah pasti (rencana)
        state.AWAIT_RANGE = False
        if mulai > 1 or akhir:
            print(f"Rentang level aktif: {mulai} - {akhir or 'akhir kursus'}.")
        self.snapshot.update("bot", phase="starting", error="")
        self._bot_thread = threading.Thread(target=self._run_bot,
                                            daemon=True, name="bot")
        self._bot_thread.start()
        return {"started": True}

    def _run_bot(self):
        from engine import browser, supervisor
        state.BOT_JALAN = True
        try:
            browser.connect()
            supervisor.main_loop()
        except SystemExit:
            if not state.STOP:
                self.snapshot.update("bot", error="Gagal menyambung ke "
                                     "halaman edclub.")
                print("Gagal menyambung ke browser.")
        except BaseException as ex:
            self.snapshot.update("bot", error=str(ex)[:200])
            print(f"[SIDECAR] bot berhenti: {ex}")
        finally:
            state.BOT_JALAN = False
            try:
                browser.disconnect()
            except Exception:
                pass
            print("Bot berhenti.")
            self._posisi_refresh()

    def m_bot_stop(self):
        state.STOP = True
        state.PAUSED = False
        state.AWAIT_RANGE = False
        self._stop_minta = time.time()
        return {}

    def m_bot_pause(self):
        state.PAUSED = True
        return {}

    def m_bot_resume(self):
        state.PAUSED = False
        return {}

    def m_bot_recover(self):
        state.ASK_RECOVERY = True
        return {}

    # ============================================================ kecil
    def m_speed_set(self, wpm, save=True):
        wpm = max(40, min(400, int(wpm)))
        state.SPEED_WPM = wpm
        self.snapshot.update("speed", wpm=wpm)
        if save:
            self._simpan_settings(speed=wpm)
        return {"wpm": wpm}

    def m_hotkeys_set(self, on):
        return {}                       # v4: hotkey dihapus

    def m_range_get(self):
        self._posisi_refresh()
        return self.snapshot.get("range")

    def m_levels_build_map(self):
        state.ASK_BUILD_MAP = True
        return {}

    def m_login_open(self, kind="individu"):
        url = (getattr(state, "LOGIN_URL_SCHOOL", "") if kind == "sekolah"
               else getattr(state, "LOGIN_URL_INDIVIDUAL", ""))
        if self.host:
            self.host.navigate(url or "https://www.edclub.com/signin")
        else:
            state.ASK_LOGIN_URL = url
            state.ASK_LOGIN_NAV = True
        return {}

    def m_settings_get(self):
        return dict(self._settings)

    def m_settings_set(self, **kv):
        self._simpan_settings(**kv)
        return dict(self._settings)

    def m_log_tail(self, n=100):
        try:
            with open(LOG_FILE, encoding="utf-8", errors="replace") as f:
                return {"lines": f.read().split("\n")[-int(n):]}
        except Exception:
            return {"lines": []}

    def m_dev_info(self):
        return {"version": APP_VERSION, "data_dir": paths.data_dir(),
                "python": sys.version.split()[0],
                "debug_port": state.DEBUG_PORT}

    def m_dev_open(self, what):
        target = LOG_FILE if what == "log" else paths.data_dir()
        try:
            os.startfile(target)        # Windows saja
        except Exception as e:
            raise RpcError("unsupported", str(e)[:100])
        return {}

    def m_dev_reset_settings(self):
        self._settings = {}
        self._simpan_settings()
        return {}

    def m_dev_simulate(self, what):
        raise RpcError("unsupported", "Hanya untuk mode uji.")

    def m_web_visible(self, on):
        if self.host:
            self.host.set_visible(bool(on))
        return {}

    def m_app_quit(self):
        state.STOP = True
        if self.host:
            self.host.shutdown()
        threading.Timer(1.0, lambda: os._exit(0)).start()
        return {}

    # ============================================================ ask
    def _ask_async(self, kunci, m, p, jawab_fn, default, timeout=300):
        """Tanya UI tanpa memblokir poller; satu ask per kunci."""
        if kunci in self._asked:
            return
        self._asked.add(kunci)

        def kerja():
            try:
                r = self.ask(m, p, timeout=timeout, default=default)
                jawab_fn(r or default)
            finally:
                self._asked.discard(kunci)
        threading.Thread(target=kerja, daemon=True).start()

    def _ask_tick(self):
        la = state.LEVEL_ASKED
        if la.get("aktif"):
            def jawab(r):
                la["jawab"] = "mulai" if r.get("skip") else "stop"
                ev = la.get("event")
                if ev:
                    ev.set()
            self._ask_async("locked", "level.locked",
                            {"level": la.get("start"),
                             "fallback": la.get("fallback")},
                            jawab, {"skip": True})
        if state.ASK_NEXT_LEVEL:
            state.ASK_NEXT_LEVEL = False

            def jawab2(r):
                if not r.get("wait"):
                    self.m_bot_stop()
            self._ask_async("next", "level.next",
                            {"level": self._level_kini()}, jawab2,
                            {"wait": True})

    def _login_tick(self):
        # mode tertanam: halaman login tampil di area web; cukup arahkan
        # sekali per episode (sama spt GUI lama, tanpa popup)
        if not state.NEEDS_LOGIN:
            self._login_nav_t = 0
            return
        if time.time() - getattr(self, "_login_nav_t", 0) > 300:
            self._login_nav_t = time.time()
            state.ASK_LOGIN_URL = getattr(state, "LOGIN_URL_INDIVIDUAL", "")
            state.ASK_LOGIN_NAV = True

    def _konfirmasi_tutup_browser(self, nama, pid=None, *a, **kw):
        """browser.set_confirmer: dipanggil dari THREAD ENGINE (Python,
        bukan .NET) - boleh menunggu jawaban UI dgn batas waktu."""
        r = self.ask("browser.force_close", {"name": nama, "pid": pid},
                     timeout=60, default={"ok": False})
        return bool((r or {}).get("ok"))

    # ============================================================ akun
    def _w2v(self):
        try:
            from gui import webview2_host
            return webview2_host
        except Exception:
            return None

    def _akun_refresh(self):
        w = self._w2v()
        if not w:
            return
        lst = [{"name": a["nama"], "email": ""} for a in w.daftar_akun()]
        self.snapshot.update("account", list=lst,
                             active=w.akun_aktif_nama() or "")

    def m_acct_list(self):
        self._akun_refresh()
        return self.snapshot.get("account")

    def _perlu_host(self):
        if not self.host:
            raise RpcError("unsupported", "Fitur akun butuh versi Windows.")
        if self._jalan:
            raise RpcError("busy", "Hentikan bot dulu sebelum ganti akun.")

    def m_acct_switch(self, name):
        self._perlu_host()
        self.host.switch_account(name, selesai=self._akun_refresh)
        return {}

    def m_acct_add(self):
        self._perlu_host()
        self.host.add_account(selesai=self._akun_refresh)
        return {"pending_login": True}

    def m_acct_logout(self):
        self._perlu_host()
        self.host.logout(selesai=self._akun_refresh)
        return {}

    def m_acct_remove(self, name):
        w = self._w2v()
        if not w:
            raise RpcError("unsupported", "Fitur akun butuh versi Windows.")
        if name == (w.akun_aktif_nama() or ""):
            raise RpcError("bad_input", "Pindah ke akun lain dulu sebelum "
                           "menghapus akun ini.")
        w.hapus_akun(name)
        self._akun_refresh()
        return {}

    # ============================================================ lisensi
    def _lic(self):
        from gui import licensing
        from net import license as netlic
        return licensing, netlic

    def _net_boot(self):
        """Pengganti launch._net_worker: lisensi lalu cek update, sekali."""
        try:
            from net import api
            if not api.BASE_URL:
                print("[net] server tidak dikonfigurasi - mode offline")
                self._lisensi_lokal()
                return
            self._lisensi_online()
        except Exception as e:
            print(f"[net] lisensi online gagal: {e}")
            self._lisensi_lokal()
        try:
            self.m_update_check()
        except Exception as e:
            print(f"[net] cek pembaruan gagal: {e}")

    def _lisensi_lokal(self):
        try:
            licensing, netlic = self._lic()
            ok = licensing._license_valid()
        except Exception:
            ok = False
        self.snapshot.update("license", state="ok" if ok else "need")

    def _lisensi_online(self):
        licensing, netlic = self._lic()
        mc = licensing._machine_code()
        tok = licensing._load_online_token()
        lokal_ok = licensing._license_valid()
        if tok and netlic.verify_token(tok):
            data = netlic.fetch_status(mc)
            st = data.get("status")
            if st == "approved":
                if data.get("token"):
                    licensing._save_online_token(data["token"])
                    tok = data["token"]
                self._tok = tok
                self.snapshot.update("license", state="ok",
                                     days_left=netlic.days_left(tok))
            else:
                self.snapshot.update("license", state="revoked")
            return
        if lokal_ok:                         # kunci lama manual masih sah
            self.snapshot.update("license", state="ok")
            nick = self._settings.get("nickname") or "pemilik-lama"
            data = netlic.request_approval(mc, nick, APP_VERSION)
            if data.get("status") == "approved" and data.get("token"):
                licensing._save_online_token(data["token"])
                self._tok = data["token"]
            return
        awal = netlic.fetch_status(mc)
        if awal.get("status") == "approved" and awal.get("token"):
            licensing._save_online_token(awal["token"])
            self._tok = awal["token"]
            self.snapshot.update("license", state="ok",
                                 days_left=netlic.days_left(awal["token"]))
            return
        if awal.get("status") == "pending":
            self.snapshot.update("license", state="pending",
                                 nickname=self._settings.get("nickname", ""))
            threading.Thread(target=self._tunggu_setuju, args=(mc,),
                             daemon=True).start()
            return
        self.snapshot.update("license", state="need",
                             nickname=self._settings.get("nickname", ""))

    def m_license_request(self, nickname):
        nickname = (nickname or "").strip()
        if len(nickname) < 2:
            raise RpcError("bad_input", "Nama panggilan minimal 2 huruf.")
        licensing, netlic = self._lic()
        mc = licensing._machine_code()
        self._simpan_settings(nickname=nickname)
        data = netlic.request_approval(mc, nickname, APP_VERSION)
        if data.get("status") == "approved" and data.get("token"):
            licensing._save_online_token(data["token"])
            self._tok = data["token"]
            self.snapshot.update("license", state="ok", nickname=nickname,
                                 days_left=netlic.days_left(data["token"]))
            return {}
        self.snapshot.update("license", state="pending", nickname=nickname)
        threading.Thread(target=self._tunggu_setuju, args=(mc,),
                         daemon=True).start()
        return {}

    def _tunggu_setuju(self, mc):
        licensing, netlic = self._lic()
        batas = time.time() + 30 * 60
        while time.time() < batas:
            time.sleep(5)
            try:
                data = netlic.fetch_status(mc)
            except Exception:
                continue
            st = data.get("status")
            if st == "approved" and data.get("token"):
                licensing._save_online_token(data["token"])
                self._tok = data["token"]
                self.snapshot.update("license", state="ok",
                                     days_left=netlic.days_left(data["token"]))
                return
            if st in ("rejected", "revoked"):
                self.snapshot.update("license", state="revoked")
                return
        self.snapshot.update("license", state="need")

    def m_license_refresh(self):
        threading.Thread(target=self._net_boot, daemon=True).start()
        return self.snapshot.get("license")

    def _gerbang_lisensi(self):
        """Cek cepat (maks 1.2 dtk) sebelum Mulai: dicabut = tolak."""
        hasil = {}

        def cek():
            try:
                licensing, netlic = self._lic()
                from net import api
                _, data = api.http_json(
                    "GET", "/api/license/status?mc="
                    + licensing._machine_code(), timeout=3)
                hasil["st"] = data.get("status")
            except Exception:
                pass
        t = threading.Thread(target=cek, daemon=True)
        t.start()
        t.join(1.2)
        if hasil.get("st") not in ("approved", None):
            self.snapshot.update("license", state="revoked")
            raise RpcError("license", "Akses perangkat ini dicabut.")

    # ============================================================ update
    def m_update_check(self):
        from net import updater as netupd
        info = netupd.check(APP_VERSION)
        if not info:
            self.snapshot.update("update", available=False)
            return self.snapshot.get("update")
        licensing, netlic = self._lic()
        tok = self._tok or licensing._load_online_token()
        if not (tok and netlic.verify_token(tok)):
            print("[net] pembaruan ada tapi mesin belum disetujui server")
            return self.snapshot.get("update")
        self._tok = tok
        self._update_info = info
        self.snapshot.update("update", available=True,
                             version=info.get("version", ""),
                             notes=info.get("notes", ""),
                             size=int(info.get("size") or 0))
        return self.snapshot.get("update")

    def m_update_download(self):
        if not self._update_info:
            raise RpcError("not_ready", "Belum ada pembaruan.")
        if self.snapshot.get("update")["phase"] == "downloading":
            return {}
        self._update_cancel = False
        threading.Thread(target=self._unduh, daemon=True).start()
        return {}

    def _unduh(self):
        from net import updater as netupd
        u = self.snapshot
        u.update("update", phase="downloading", progress=0.0)

        def prog(got, total):
            if total:
                u.update("update", progress=round(got / total, 3))
            return not self._update_cancel
        try:
            err = None
            for jalur in (True, True, False):     # worker, worker, GitHub
                try:
                    netupd.download(self._update_info, self._tok,
                                    PROGRAM_PATH + netupd.NEW_SUFFIX,
                                    prog, lewat_worker=jalur)
                    err = None
                    break
                except netupd.UpdateCancelled:
                    raise
                except Exception as e:
                    err = e
                    print(f"[net] jalur unduh gagal: {str(e)[:80]}")
                    time.sleep(2)
            if err:
                raise err
            netupd.stage_pending(PROGRAM_PATH, self._update_info)
            u.update("update", phase="ready", progress=1.0)
        except netupd.UpdateCancelled:
            u.update("update", phase="idle", progress=0.0)
        except Exception as e:
            print(f"[net] pembaruan gagal: {e}")
            u.update("update", phase="idle", progress=0.0)

    def m_update_cancel(self):
        self._update_cancel = True
        return {}

    def m_update_install(self):
        from net import updater as netupd
        if self.snapshot.get("update")["phase"] != "ready":
            raise RpcError("not_ready", "Unduhan belum selesai.")
        state.STOP = True
        if not netupd.apply_update_and_restart(PROGRAM_PATH):
            raise RpcError("internal", "Pasang otomatis gagal.")
        self.emit("app.exit", {"reason": "update"})
        return {"restarting": True}

    # ============================================================ lapor
    def m_report_send(self, category, text):
        try:
            with open(LOG_FILE, encoding="utf-8", errors="replace") as f:
                ekor = "\n".join(f.read().split("\n")[-400:])
        except Exception as e:
            ekor = f"(log tak terbaca: {e})"
        akun = self.snapshot.get("account").get("active") or "?"
        isi = (f"TypingBot laporan bug\nversi: {APP_VERSION}\n"
               f"akun aktif: {akun}\nkategori: {category}\n"
               f"waktu: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
               + (f"=== CERITA USER ===\n{text}\n\n" if text else "")
               + "=== LOG (400 baris terakhir) ===\n" + ekor + "\n")
        try:
            from net import api
            st, _ = api.http_json("POST", "/api/lapor",
                                  {"versi": APP_VERSION, "akun": akun,
                                   "isi": isi}, timeout=15)
            if st == 200:
                print("[LAPOR] terkirim otomatis.")
                return {"sent": True}
            print(f"[LAPOR] server tolak ({st}).")
        except Exception as e:
            print(f"[LAPOR] kirim otomatis gagal: {str(e)[:60]}")
        # cadangan offline: simpan ke Desktop
        desk = os.path.join(os.path.expanduser("~"), "Desktop")
        if not os.path.isdir(desk):
            desk = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop")
        try:
            os.makedirs(desk, exist_ok=True)
            p = os.path.join(desk, "TypingBot-laporan-"
                             + time.strftime("%Y%m%d-%H%M%S") + ".txt")
            with open(p, "w", encoding="utf-8") as f:
                f.write(isi)
        except Exception:
            pass
        raise RpcError("offline", "Gagal terkirim. Laporan disimpan di "
                       "Desktop, kirim manual ya.")
