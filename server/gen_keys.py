"""Generator keypair Ed25519 untuk lisensi online.

Output: server/_signing.json (di-gitignore) berisi:
  {"priv_pkcs8_b64": "...", "pub_hex": "..."}

pub_hex ditanam di net/license.py (SERVER_PUBLIC_KEY_HEX) saat rilis.
priv_pkcs8_b64 dipakai local_server.py; versi Worker dipakai sebagai
secret SIGN_PRIV. Simpan salinannya di vault privat.
"""

import base64
import json
import os
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def generate(out_path=None):
    key = Ed25519PrivateKey.generate()
    priv = key.private_bytes(serialization.Encoding.DER,
                             serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())
    pub = key.public_key().public_bytes(serialization.Encoding.Raw,
                                        serialization.PublicFormat.Raw)
    data = {"priv_pkcs8_b64": base64.b64encode(priv).decode("ascii"),
            "pub_hex": pub.hex()}
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    return data


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "_signing.json")
    data = generate(path)
    print("ditulis:", path)
    print("pub_hex (tanam ke net/license.py):")
    print(data["pub_hex"])
