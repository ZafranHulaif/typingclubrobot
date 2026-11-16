#!/data/data/com.termux/files/usr/bin/sh
# TypingBot Edisi Web di Termux (Android) - EKSPERIMEN.
# Jalur headless: chromium unduhan playwright + panel web di HP.
# Butuh: pkg install python glibc-runner (jalankan ini DENGAN glibc aktif,
# lihat platforms/README.md).
set -e
cd "$(dirname "$0")/.."

echo "== TypingBot Edisi Web (Termux) =="
command -v python3 >/dev/null 2>&1 || { echo "pkg install python dulu."; exit 1; }
echo "Python : $(python3 -V)"

if ! python3 -c "import playwright" >/dev/null 2>&1; then
    echo "Memasang playwright..."
    python3 -m pip install playwright pillow
fi
if ! ls ~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome >/dev/null 2>&1; then
    echo "Unduh chromium (sekali, ~150MB)..."
    python3 -m playwright install chromium
fi

PORT="${TYPINGBOT_PORT:-8765}"
echo ""
echo "Panel : http://localhost:$PORT  (buka di Chrome HP)"
echo "Login edclub lewat form di panel (mode headless)."
echo ""
exec python3 bot_web.py --headless --port "$PORT"
