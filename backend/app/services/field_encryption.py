import base64
import hashlib
import os
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


ENCRYPTED_VALUE_PREFIX = "enc:v1:"


def data_encryption_key_is_configured() -> bool:
    return bool(os.getenv("APP_DATA_ENCRYPTION_KEY", "").strip())


def _key_material() -> str:
    material = (
        os.getenv("APP_DATA_ENCRYPTION_KEY")
        or os.getenv("AUTH_SECRET_KEY")
        or os.getenv("SECRET_KEY")
        or "job-finder-dev-secret-change-me"
    ).strip()
    return material or "job-finder-dev-secret-change-me"


@lru_cache(maxsize=4)
def _fernet_for_material(material: str) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(material.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_text(value: Optional[str]) -> Optional[str]:
    if value is None or value.startswith(ENCRYPTED_VALUE_PREFIX):
        return value
    token = _fernet_for_material(_key_material()).encrypt(value.encode("utf-8")).decode("ascii")
    return f"{ENCRYPTED_VALUE_PREFIX}{token}"


def decrypt_text(value: Optional[str], fallback: Optional[str] = None) -> Optional[str]:
    if value is None or not value.startswith(ENCRYPTED_VALUE_PREFIX):
        return value
    token = value[len(ENCRYPTED_VALUE_PREFIX):].encode("ascii")
    try:
        return _fernet_for_material(_key_material()).decrypt(token).decode("utf-8")
    except (InvalidToken, ValueError):
        return fallback
