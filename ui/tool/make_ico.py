# Rakit .ico multi-ukuran dari build/icon/<n>.png (payload PNG, Vista+).
import struct, sys, os
src = sys.argv[1] if len(sys.argv) > 1 else 'build/icon'
out = sys.argv[2] if len(sys.argv) > 2 else 'windows/runner/resources/app_icon.ico'
sizes = sorted(int(f[:-4]) for f in os.listdir(src) if f.endswith('.png'))
blobs = [open(os.path.join(src, f'{s}.png'), 'rb').read() for s in sizes]
hdr = struct.pack('<HHH', 0, 1, len(sizes))
off = 6 + 16 * len(sizes)
ent = b''
for s, b in zip(sizes, blobs):
    d = 0 if s >= 256 else s
    ent += struct.pack('<BBBBHHII', d, d, 0, 0, 1, 32, len(b), off)
    off += len(b)
open(out, 'wb').write(hdr + ent + b''.join(blobs))
print('ok', out, sizes)
