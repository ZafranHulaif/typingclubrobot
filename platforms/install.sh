#!/bin/sh
# TypingBot Edisi Web - pemasang sekali jalan (macOS / Linux).
# butuh: python3. browser Chromium dicari otomatis (Chrome/Brave/Edge/
# Chromium). Panel: http://localhost:8765
set -e
cd "$(dirname "$0")/.."   # root repo (platforms/ -> ..)

printf "\n== TypingBot Edisi Web ==\n"

# 1. Python 3
if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 tidak ada."
    echo "  macOS : brew install python3  (atau dari python.org)"
    echo "  Linux : sudo apt install python3 python3-pip"
    exit 1
fi
echo "Python : $(python3 -V)"

# 2. playwright (untuk CDP; browser pakai yang terpasang di sistem)
if ! python3 -c "import playwright" >/dev/null 2>&1; then
    echo "Memasang playwright..."
    python3 -m pip install --user playwright 2>/dev/null \
        || python3 -m pip install --break-system-packages playwright
fi

# 3. browser Chromium
ketemu=""
for p in \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    "/Applications/Chromium.app/Contents/MacOS/Chromium" \
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser" \
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
    /usr/bin/chromium /usr/bin/chromium-browser \
    /usr/bin/google-chrome /usr/bin/google-chrome-stable \
    /usr/bin/brave-browser /usr/bin/microsoft-edge; do
    [ -x "$p" ] && ketemu="$p" && break
done
if [ -n "$ketemu" ]; then
    echo "Browser: $ketemu"
else
    echo "Tidak ada Chrome/Brave/Edge/Chromium terpasang."
    echo "  macOS : brew install --cask google-chrome"
    echo "  Linux : sudo apt install chromium-browser"
    echo "Bot tetap dicoba (mungkin ketemu di jalur lain)."
fi

# 4. jalankan
PORT="${TYPINGBOT_PORT:-8765}"
echo ""
echo "Panel : http://localhost:$PORT"
echo "Stop  : Ctrl+C di sini (atau tombol Berhenti di panel)"
echo ""
python3 bot_web.py --port "$PORT" ${ketemu:+--browser "$ketemu"}
