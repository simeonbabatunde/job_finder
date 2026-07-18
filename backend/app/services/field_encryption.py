import base64
import hashlib
import os
from functools import lru_cache
from typing import Literal, Optional

from cryptography.fernet import Fernet, InvalidToken


ENCRYPTED_VALUE_PREFIX = "enc:v1:"
DecryptionKeyStatus = Literal["none", "plaintext", "current", "previous", "unreadable"]


def data_encryption_key_is_configured() -> bool:
    return bool(os.getenv("APP_DATA_ENCRYPTION_KEY", "").strip())


def _key_material() -> str:
    material = (
        os.getenv("APP_DATA_ENCRYPTION_KEY")
        or os.getenv("AUTH_SECRET_KEY")
        or os.getenv("SECRET_KEY")
        or "jobmatchkit-dev-secret-change-me"
    ).strip()
    return material or "jobmatchkit-dev-secret-change-me"


def _previous_key_materials() -> list[str]:
    return [
        material.strip()
        for material in os.getenv("APP_DATA_PREVIOUS_ENCRYPTION_KEYS", "").split(",")
        if material.strip()
    ]


@lru_cache(maxsize=16)
def _fernet_for_material(material: str) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(material.encode("utf-8")).digest())
    return Fernet(key)


def _encrypt_plain_text(value: str) -> str:
    token = _fernet_for_material(_key_material()).encrypt(value.encode("utf-8")).decode("ascii")
    return f"{ENCRYPTED_VALUE_PREFIX}{token}"


def encrypt_text(value: Optional[str]) -> Optional[str]:
    if value is None or value.startswith(ENCRYPTED_VALUE_PREFIX):
        return value
    return _encrypt_plain_text(value)


def encrypt_text_with_current_key(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return _encrypt_plain_text(value)


def decrypt_text_with_key_status(
    value: Optional[str],
    fallback: Optional[str] = None,
) -> tuple[Optional[str], DecryptionKeyStatus]:
    if value is None:
        return None, "none"
    if not value.startswith(ENCRYPTED_VALUE_PREFIX):
        return value, "plaintext"

    token = value[len(ENCRYPTED_VALUE_PREFIX):].encode("ascii")
    for index, material in enumerate((_key_material(), *_previous_key_materials())):
        try:
            decrypted = _fernet_for_material(material).decrypt(token).decode("utf-8")
            return decrypted, "current" if index == 0 else "previous"
        except (InvalidToken, ValueError):
            continue
    return fallback, "unreadable"


def decrypt_text(value: Optional[str], fallback: Optional[str] = None) -> Optional[str]:
    decrypted, _status = decrypt_text_with_key_status(value, fallback=fallback)
    return decrypted
