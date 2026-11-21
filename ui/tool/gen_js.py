"""Salin payload JS dari kode Python (spesifikasi) ke Dart, VERBATIM.

v4 memakai ulang JS yang sudah terbukti di 3.5.x (lihat
docs/architecture/v4-native-plan.md). Jangan edit file .dart hasilnya
dengan tangan: ubah sumber Python-nya lalu jalankan ulang:

    python3 ui/tool/gen_js.py          # tulis ulang
    python3 ui/tool/gen_js.py --check  # gagal kalau hasil basi (CI)

Dua keluaran:
- ui/lib/src/web/js_init.dart   init script halaman (N1)
- ui/lib/src/engine/js.dart     semua payload mesin bot (N3): seluruh
  konstanta jstemplates.py + beberapa dari levels.py / lessons/ocr.py,
  peta tombol, regex sesi, dan peta level bawaan (level_data.py)

Dibaca pakai ast (tanpa import), jadi jalan di Linux juga.
"""
import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT_INIT = ROOT / "ui/lib/src/web/js_init.dart"
OUT_ENGINE = ROOT / "ui/lib/src/engine/js.dart"
OUT_INLINE = ROOT / "ui/lib/src/engine/js_inline.dart"

# (file sumber, nama variabel Python, nama Dart)
INIT_SOURCES = [
    ("engine/browser.py", "NO_POPUP_JS", "noPopupJs"),
    ("engine/browser.py", "_DUR_FIX_JS", "durFixJs"),
    ("gui/webview2_host.py", "_LOGIN_REDIRECT_JS", "loginRedirectJs"),
    ("gui/webview2_host.py", "_OAUTH_RELAY_PAGE_JS", "oauthRelayPageJs"),
    ("gui/webview2_host.py", "OAUTH_MARKER_JS", "oauthMarkerJs"),
]

# tambahan di luar jstemplates.py (semua konstanta jstemplates ikut otomatis)
ENGINE_EXTRA = [
    ("engine/levels.py", "_KLIK_LANJUT_JS", "klikLanjutJs"),
    ("engine/levels.py", "_DAFTAR_JS", "daftarJs"),
    ("engine/lessons/ocr.py", "BALLOON_BRIDGE_JS", "balloonBridgeJs"),
    ("engine/lessons/ocr.py", "BALLOON_FEED_JS", "balloonFeedJs"),
    ("engine/lessons/ocr.py", "_MAJU_LABEL", "majuLabel"),
    ("engine/lessons/ocr.py", "_MAJU_DASAR", "majuDasar"),
    ("engine/lessons/ocr.py", "_CARI_ULANG_JS", "cariUlangJs"),
]


# JS yang ditulis langsung di dalam fungsi python (bukan konstanta modul):
# (file, fungsi, penanda unik di dalam string, nama Dart)
INLINE = [
    ("engine/jsutil.py", "close_overlays_all_frames", "window.__CLICKPT = cands", "closePointJs"),
    ("engine/jsutil.py", "dump_debug_info", "texts: (function()", "debugDumpJs"),
    ("engine/typing_core.py", "focus_frame", "document.body.focus", "focusFrameJs"),
    ("engine/lessons/games.py", "_phaser_try_advance", "const NX = ['next'", "advanceTextBtnJs"),
    ("engine/lessons/ocr.py", "try_balloon_core", "ready to start", "readyStartJs"),
    ("engine/lessons/ocr.py", "try_balloon_core", "new MouseEvent('pointerdown'", "canvasSkipJs"),
    ("engine/lessons/ocr.py", "_core_bridge_frame", "^return !!(window.core", "coreMainJs"),
    ("engine/lessons/ocr.py", "_core_bridge_frame", "if (!/phaser", "coreIframeJs"),
    ("engine/lessons/ocr.py", "_probe_iframe", "o.stateKeys", "probeIframeJs"),
    ("engine/lessons/ocr.py", "_balloon_frame", "return !!(window.Phaser && Phaser.GAMES", "phaserPresentJs"),
    ("engine/levels.py", "_baca_unlock_js", "is_unlocked", "bacaUnlockJs"),
    ("engine/levels.py", "_goto_level_via_daftar_isi", "(n) =>", "cariBarisJs"),
    ("engine/levels.py", "_goto_level_via_daftar_isi", "scrollTo", "scrollBawahJs"),
    ("engine/levels.py", "_lesson_hidup", "querySelectorAll('canvas').length", "lessonHidupJs"),
    ("engine/levels.py", "_gate_atau_mulai", "audio-activation-gate", "gateAtauMulaiJs"),
    ("engine/levels.py", "_klik_baris_js", "lsn_name", "klikBarisJs"),
    ("engine/levels.py", "_level_label", "Lesson\\s+", "levelLabelJs"),
    ("engine/levels.py", "build_level_map", "rows[i] ?", "barisLabelJs"),
    ("engine/levels.py", "build_level_map", "div.box-container').length", "jumlahBarisJs"),
    ("engine/recovery.py", "recover_and_restart_lesson", "v.currentTime", "mediaPlayingJs"),
    ("engine/recovery.py", "recover_and_restart_lesson", "has_progress", "recoveryListClickJs"),
]


def inline_string(path, func, marker):
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.FunctionDef) and node.name == func:
            # '^' di depan penanda = string harus DIAWALI penanda itu
            cocok = ((lambda v: v.startswith(marker[1:])) if marker.startswith("^")
                     else (lambda v: marker in v))
            doc = ast.get_docstring(node, clean=False)
            found = {c.value for c in ast.walk(node)
                     if isinstance(c, ast.Constant) and isinstance(c.value, str)
                     and c.value != doc and cocok(c.value)}
            if len(found) != 1:
                sys.exit(f"{path}:{func} penanda {marker!r} cocok {len(found)} string")
            return found.pop()
    sys.exit(f"fungsi {func} tidak ada di {path}")


def _tree(path):
    return ast.parse((ROOT / path).read_text(encoding="utf-8"))


def assigns(path):
    """{nama: node nilai} utk assignment tingkat modul."""
    out = {}
    for node in _tree(path).body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            out[node.targets[0].id] = node.value
    return out


def strings(path):
    out = {}
    for k, v in assigns(path).items():
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            out[k] = v.value
        elif isinstance(v, ast.BinOp):   # "a" "b" / "a" + "b"
            try:
                val = ast.literal_eval(v)
                if isinstance(val, str):
                    out[k] = val
            except Exception:
                pass
    return out


def camel(py):
    parts = [p for p in py.strip("_").lower().split("_") if p]
    return parts[0] + "".join(p.title() for p in parts[1:])


def raw(dart, js, src):
    if "'''" in js:
        sys.exit(f"{src} memuat ''' - tak bisa jadi raw string Dart")
    return f"\n/// {src}\nconst {dart} = r'''{js}''';\n"


def dstr(s):
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


HEAD = ("// HASIL GENERATE oleh ui/tool/gen_js.py - JANGAN diedit tangan.\n"
        "// Sumber: payload JS Python 3.5.x (spesifikasi), disalin verbatim.\n")


def render_init():
    cache = {}
    parts = [HEAD]
    for path, py, dart in INIT_SOURCES:
        if path not in cache:
            cache[path] = strings(path)
        js = cache[path].get(py)
        if js is None:
            sys.exit(f"{py} tidak ditemukan di {path}")
        parts.append(raw(dart, js, f"{path} :: {py}"))
    return "".join(parts)


def render_engine():
    parts = [HEAD, "// ignore_for_file: constant_identifier_names\n"]
    tpl = assigns("engine/jstemplates.py")
    for py, node in tpl.items():
        src = f"engine/jstemplates.py :: {py}"
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            parts.append(raw(camel(py), node.value, src))
        elif isinstance(node, ast.Dict):
            d = ast.literal_eval(node)
            body = ", ".join(f"{dstr(k)}: {dstr(v)}" for k, v in d.items())
            parts.append(f"\n/// {src}\nconst {camel(py)} = <String, String>{{{body}}};\n")
        elif (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "compile"):
            pat = ast.literal_eval(node.args[0])
            ci = any("I" in ast.unparse(a) for a in node.args[1:])
            parts.append(f"\n/// {src} (pola regex; re.I={ci})\n"
                         f"const {camel(py)} = r'''{pat}''';\n"
                         f"const {camel(py)}IgnoreCase = {'true' if ci else 'false'};\n")
        else:
            sys.exit(f"{py}: jenis nilai tak dikenal di jstemplates.py")
    cache = {}
    for path, py, dart in ENGINE_EXTRA:
        if path not in cache:
            cache[path] = strings(path)
        js = cache[path].get(py)
        if js is None:
            sys.exit(f"{py} tidak ditemukan di {path}")
        parts.append(raw(dart, js, f"{path} :: {py}"))
    peta = ast.literal_eval(assigns("level_data.py")["PETA"])
    rows = []
    items = sorted(peta.items())
    for i in range(0, len(items), 8):
        rows.append("  " + " ".join(f"{k}: {v}," for k, v in items[i:i + 8]))
    parts.append("\n/// level_data.py :: PETA (level -> id lesson kursus program-3)\n"
                 "const levelPeta = <int, int>{\n" + "\n".join(rows) + "\n};\n")
    return "".join(parts)


def render_inline():
    parts = [HEAD, "// JS yang di python ditulis di dalam fungsi (dicari lewat penanda unik).\n"]
    for path, func, marker, dart in INLINE:
        parts.append(raw(dart, inline_string(path, func, marker), f"{path} :: {func}()"))
    return "".join(parts)


if __name__ == "__main__":
    outs = [(OUT_INIT, render_init()), (OUT_ENGINE, render_engine()),
            (OUT_INLINE, render_inline())]
    if "--check" in sys.argv:
        for out, text in outs:
            if not out.exists() or out.read_text(encoding="utf-8") != text:
                sys.exit(f"{out.relative_to(ROOT)} basi: jalankan ui/tool/gen_js.py")
        print("js_init.dart + engine/js.dart + js_inline.dart cocok dengan sumber Python")
    else:
        for out, text in outs:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
            print(f"tulis {out.relative_to(ROOT)}")
