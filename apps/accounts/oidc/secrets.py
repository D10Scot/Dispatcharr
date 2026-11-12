"""Encryption at rest for a provider's client credential (SSO spec D11, section 5.2).

Fernet with a key derived from ``SECRET_KEY`` by HKDF-SHA256, one ``info`` label per kind of
secret so a ciphertext of one kind never decrypts as another. ``SECRET_KEY`` changing (a
backup restored onto a new instance) makes every ciphertext unreadable; that surfaces as
``CredentialUnreadable`` and the provider reports ``credential_unreadable``.

Nothing here logs, and no exception carries the plaintext or the ciphertext.
"""

import base64
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings

CLIENT_SECRET = b"mino-oidc-client-secret"
CLIENT_KEY = b"mino-oidc-client-key"


class CredentialUnreadable(Exception):
    """The stored ciphertext cannot be decrypted with the current ``SECRET_KEY``."""


@lru_cache(maxsize=8)
def _fernet(secret_key: str, info: bytes) -> Fernet:
    derived = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=info
    ).derive(secret_key.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(derived))


def _current(info: bytes) -> Fernet:
    return _fernet(str(settings.SECRET_KEY), info)


def encrypt(plaintext: str, info: bytes = CLIENT_SECRET) -> str:
    return _current(info).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str, info: bytes = CLIENT_SECRET) -> str:
    try:
        return _current(info).decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError):
        # InvalidToken's message is empty, but never chain it: nothing about the input
        # belongs in a traceback.
        raise CredentialUnreadable("credential cannot be decrypted") from None


def is_readable(token: str, info: bytes = CLIENT_SECRET) -> bool:
    """True when ``token`` is empty (nothing to read) or decrypts."""
    if not token:
        return True
    try:
        decrypt(token, info)
    except CredentialUnreadable:
        return False
    return True
