import base64

import pytest

from api.crypto import DecryptionError, load_key, open_sealed, seal

RAW_KEY = bytes(range(32))


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def test_roundtrip():
    blob = seal(b"hello snapshot", RAW_KEY, "v1")
    assert open_sealed(blob, {"v1": RAW_KEY}) == b"hello snapshot"


def test_nonce_differs_between_calls():
    first = seal(b"same", RAW_KEY, "v1")
    second = seal(b"same", RAW_KEY, "v1")
    assert first != second


def test_tampered_ciphertext_is_rejected():
    blob = seal(b"hello", RAW_KEY, "v1")
    tampered = blob.replace(b'"ct":"', b'"ct":"A')
    with pytest.raises(DecryptionError):
        open_sealed(tampered, {"v1": RAW_KEY})


def test_wrong_key_is_rejected():
    blob = seal(b"hello", RAW_KEY, "v1")
    with pytest.raises(DecryptionError):
        open_sealed(blob, {"v1": bytes(32)})


def test_unknown_key_id_is_rejected():
    blob = seal(b"hello", RAW_KEY, "v1")
    with pytest.raises(DecryptionError):
        open_sealed(blob, {"other": RAW_KEY})


def test_load_key_requires_32_bytes():
    with pytest.raises(ValueError):
        load_key(b64(b"short"))
    assert load_key(b64(RAW_KEY)) == RAW_KEY
