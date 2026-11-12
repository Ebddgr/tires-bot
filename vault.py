"""
vault.py - Secure encrypted credential vault for Tire Purchase Bot.
Uses AES-256-GCM via PBKDF2HMAC key derivation.
"""

import os
import sys
import json
import base64
import argparse
from typing import Any, Dict, Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

DEFAULT_VAULT_PATH = os.getenv("TIRES_VAULT_PATH", os.path.join(os.path.dirname(__file__), ".vault.enc"))
DEFAULT_KEY_PATH = os.getenv("TIRES_VAULT_KEY_PATH", os.path.join(os.path.dirname(__file__), ".vault.key"))


class Vault:
    """Encrypted credential store backed by AES-GCM."""

    def __init__(self, vault_path: str = DEFAULT_VAULT_PATH, master_key: Optional[str] = None):
        self.vault_path = os.path.abspath(vault_path)
        self.master_key = master_key or os.getenv("HERMES_VAULT_KEY") or self._load_or_create_key()
        self._store: Dict[str, Any] = {}
        self.load()

    def _load_or_create_key(self) -> str:
        """Loads a persistent master key from disk or creates a new 32-byte key."""
        if os.path.exists(DEFAULT_KEY_PATH):
            try:
                with open(DEFAULT_KEY_PATH, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except Exception:
                pass

        new_key = base64.b64encode(os.urandom(32)).decode("ascii")
        try:
            with open(DEFAULT_KEY_PATH, "w", encoding="utf-8") as f:
                f.write(new_key)
            os.chmod(DEFAULT_KEY_PATH, 0o600)
        except Exception:
            pass
        return new_key

    def _derive_aes_key(self, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100_000,
        )
        return kdf.derive(self.master_key.encode("utf-8"))

    def load(self) -> None:
        """Decrypts and loads credentials into memory."""
        if not os.path.exists(self.vault_path):
            self._store = {}
            return

        try:
            with open(self.vault_path, "rb") as f:
                raw_bytes = f.read()

            if len(raw_bytes) < 28:  # 16-byte salt + 12-byte nonce
                self._store = {}
                return

            salt = raw_bytes[:16]
            nonce = raw_bytes[16:28]
            ciphertext = raw_bytes[28:]

            aes_key = self._derive_aes_key(salt)
            aesgcm = AESGCM(aes_key)
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
            self._store = json.loads(plaintext.decode("utf-8"))
        except Exception:
            self._store = {}

    def save(self) -> None:
        """Encrypts and persists credentials to disk."""
        salt = os.urandom(16)
        nonce = os.urandom(12)
        aes_key = self._derive_aes_key(salt)
        aesgcm = AESGCM(aes_key)

        data = json.dumps(self._store).encode("utf-8")
        ciphertext = aesgcm.encrypt(nonce, data, None)

        os.makedirs(os.path.dirname(self.vault_path), exist_ok=True)
        with open(self.vault_path, "wb") as f:
            f.write(salt + nonce + ciphertext)
        try:
            os.chmod(self.vault_path, 0o600)
        except Exception:
            pass

    def get(self, key: str, default: Any = None) -> Any:
        """Returns credential by key; falls back to environment variable then default."""
        if key in self._store:
            return self._store[key]
        return os.getenv(key, default)

    def set(self, key: str, value: Any) -> None:
        """Sets a credential and persists vault."""
        self._store[key] = value
        self.save()

    def set_batch(self, mapping: Dict[str, Any]) -> None:
        """Sets multiple credentials in a single write."""
        self._store.update(mapping)
        self.save()

    def list_keys(self) -> list:
        """Lists stored credential keys (values are masked)."""
        return sorted(list(self._store.keys()))

    def delete(self, key: str) -> bool:
        """Deletes a key from vault."""
        if key in self._store:
            del self._store[key]
            self.save()
            return True
        return False


_GLOBAL_VAULT: Optional[Vault] = None


def get_vault() -> Vault:
    """Returns singleton Vault instance."""
    global _GLOBAL_VAULT
    if _GLOBAL_VAULT is None:
        _GLOBAL_VAULT = Vault()
    return _GLOBAL_VAULT


# ponytail: Using AES-256-GCM local encrypted vault file. Add remote HSM / HashiCorp Vault when enterprise infrastructure required.

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hermes Secure Vault CLI")
    subparsers = parser.add_subparsers(dest="command")

    set_p = subparsers.add_parser("set", help="Set secret in vault")
    set_p.add_argument("key", help="Key name (e.g. TIRES_USER)")
    set_p.add_argument("value", help="Secret value")

    get_p = subparsers.add_parser("get", help="Get secret from vault")
    get_p.add_argument("key", help="Key name")

    subparsers.add_parser("list", help="List secret keys")

    args = parser.parse_args()
    v = get_vault()

    if args.command == "set":
        v.set(args.key, args.value)
        print(f"Key '{args.key}' securely saved in vault.")
    elif args.command == "get":
        val = v.get(args.key)
        if val is not None:
            print(val)
        else:
            print(f"Key '{args.key}' not found.")
            sys.exit(1)
    elif args.command == "list":
        keys = v.list_keys()
        print(f"Stored keys ({len(keys)}): {', '.join(keys) if keys else 'None'}")
    else:
        parser.print_help()
