"""Make the keys that sign Lit Review releases. Run once, on your own computer.

    python packaging/make_update_key.py --active D:\\keys\\lit-review-active.pem --spare E:\\keys\\lit-review-spare.pem

It writes two passphrase-protected private keys (an active one and a spare) to the paths
you give, and prints the two public keys to paste into PUBLIC_KEYS in
backend/update_manifest.py. Only the public keys go in the app. Keep the private keys
OUT of this repository (it refuses to write inside it) and in different places: the spare
is what lets a lost or leaked active key be replaced by an ordinary release. Anyone who
holds the active key can ship an update to every user until they move to a build that no
longer trusts it, so protect it like a bank password.
"""

import argparse
import base64
import getpass
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

REPO = Path(__file__).resolve().parent.parent


def new_pair(passphrase):
    """(encrypted private key PEM bytes, base64 raw public key text)."""
    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(passphrase),
    )
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return pem, base64.b64encode(public).decode()


def check_destination(path):
    path = Path(path).resolve()
    if REPO == path or REPO in path.parents:
        raise SystemExit(f"{path} is inside the repository: keep private keys outside it")
    if path.exists():
        raise SystemExit(f"{path} already exists: this will not overwrite a key")
    if not path.parent.is_dir():
        raise SystemExit(f"the folder {path.parent} does not exist")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--active", required=True)
    parser.add_argument("--spare", required=True)
    args = parser.parse_args(argv)
    active, spare = check_destination(args.active), check_destination(args.spare)
    if active == spare:
        raise SystemExit("the active and spare keys must be different files")
    public = []
    for path in (active, spare):
        passphrase = getpass.getpass(f"Passphrase for {path.name}: ").encode()
        if not passphrase or getpass.getpass("Again: ").encode() != passphrase:
            raise SystemExit("the passphrase was empty or did not match")
        pem, key = new_pair(passphrase)
        path.write_bytes(pem)
        public.append(key)
        print(f"wrote {path}")
    print("\nPaste this into backend/update_manifest.py:\n")
    print("PUBLIC_KEYS = [")
    for key in public:
        print(f'    "{key}",')
    print("]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
