"""Salin payload JS dari kode Python (spesifikasi) ke Dart, VERBATIM.

v4 memakai ulang JS yang sudah terbukti di 3.5.x (lihat
docs/architecture/v4-native-plan.md). Jangan edit file .dart hasilnya
dengan tangan: ubah sumber Python-nya lalu jalankan ulang:

    python3 ui/tool/gen_js.py          # tulis ulang
    python3 ui/tool/gen_js.py --check  # gagal kalau hasil basi (CI)

Dibaca pakai ast (tanpa import), jadi jalan di Linux juga.
"""
import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "ui/lib/src/web/js_init.dart"

# (file sumber, nama variabel Python, nama Dart)
SOURCES = [
    ("engine/browser.py", "NO_POPUP_JS", "noPopupJs"),
    ("engine/browser.py", "_DUR_FIX_JS", "durFixJs"),
    ("gui/webview2_host.py", "_LOGIN_REDIRECT_JS", "loginRedirectJs"),
    ("gui/webview2_host.py", "_OAUTH_RELAY_PAGE_JS", "oauthRelayPageJs"),
    ("gui/webview2_host.py", "OAUTH_MARKER_JS", "oauthMarkerJs"),
]


def strings(path):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    out = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            out[node.targets[0].id] = node.value.value
    return out


def render():
    cache = {}
    parts = [
        "// HASIL GENERATE oleh ui/tool/gen_js.py - JANGAN diedit tangan.\n"
        "// Sumber: payload JS Python 3.5.x (spesifikasi), disalin verbatim.\n"
    ]
    for path, py, dart in SOURCES:
        if path not in cache:
            cache[path] = strings(path)
        js = cache[path].get(py)
        if js is None:
            sys.exit(f"{py} tidak ditemukan di {path}")
        if "'''" in js:
            sys.exit(f"{py} memuat ''' - tak bisa jadi raw string Dart")
        parts.append(f"\n/// {path} :: {py}\nconst {dart} = r'''{js}''';\n")
    return "".join(parts)


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            sys.exit(f"{OUT.relative_to(ROOT)} basi: jalankan ui/tool/gen_js.py")
        print("js_init.dart cocok dengan sumber Python")
    else:
        OUT.write_text(text, encoding="utf-8")
        print(f"tulis {OUT.relative_to(ROOT)}")
