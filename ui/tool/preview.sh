#!/usr/bin/env bash
# Preview UI di VPS (RAM kecil!): build web dgn batas memori, lalu jalankan
# sidecar mock + server statis. Buka http://127.0.0.1:<port>/?port=8766
# JANGAN build tanpa batas: dart2js pernah bikin VPS 3 GB mati kehabisan RAM.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/flutter/bin:$PATH"
if [ "${1:-}" != "--no-build" ]; then
  systemd-run --user --scope -q -p MemoryMax=1400M -p MemorySwapMax=700M \
    env DART_VM_OPTIONS=--old_gen_heap_size=1000 \
    flutter build web --release -O1 --no-wasm-dry-run
fi
HOST="${HOST:-127.0.0.1}"   # HOST=100.x (tailscale) supaya bisa dibuka dari HP/laptop
(cd .. && python3 -m sidecar --mock --no-token --host "$HOST" --port 8766 &)
PORT=$(python3 -c "import socket;s=socket.socket();s.bind(('$HOST',0));print(s.getsockname()[1])")
echo "UI: http://$HOST:$PORT/?host=$HOST&port=8766"
cd build/web && exec python3 -m http.server "$PORT" --bind "$HOST"
