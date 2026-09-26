from __future__ import annotations

import base64
import json
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"OSNC1"
NONCE_BYTES = 12
KEY_BYTES = 32


class DecryptionError(Exception):
    """Raised when a sealed snapshot cannot be opened."""


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def load_key(encoded: str) -> bytes:
    key = _b64d(encoded)
    if len(key) != KEY_BYTES:
        raise ValueError(f"data key must be {KEY_BYTES} bytes, got {len(key)}")
    return key


def seal(plaintext: bytes, key: bytes, key_id: str = "v1") -> bytes:
    nonce = os.urandom(NONCE_BYTES)
    aad = MAGIC + key_id.encode("utf-8")
    ct = AESGCM(key).encrypt(nonce, plaintext, aad)
    return json.dumps(
        {"key_id": key_id, "nonce": _b64e(nonce), "ct": _b64e(ct)},
        separators=(",", ":"),
    ).encode("utf-8")


def open_sealed(blob: bytes, keyring: dict[str, bytes]) -> bytes:
    try:
        envelope = json.loads(blob)
        key_id = envelope["key_id"]
        key = keyring[key_id]
        aad = MAGIC + key_id.encode("utf-8")
        return AESGCM(key).decrypt(
            _b64d(envelope["nonce"]), _b64d(envelope["ct"]), aad
        )
    except (KeyError, ValueError, TypeError, InvalidTag) as exc:
        raise DecryptionError("snapshot could not be decrypted") from exc
