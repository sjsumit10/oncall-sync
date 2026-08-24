"""Envelope encryption for third-party credentials.

Two layers: a per-organization data key (DEK) encrypts the credential, and a
single key-encryption key (KEK) from the environment wraps each DEK. That keeps
one tenant's compromised DEK from reading another's data, and makes a future KEK
rotation a re-wrap of N small keys rather than a re-encrypt of every secret.

Ciphertext layout: version(1) || nonce(12) || AES-256-GCM ciphertext+tag.
The org id is bound in as additional authenticated data, so a ciphertext moved
between tenants fails to decrypt rather than silently succeeding.
"""

import base64
import os
import uuid

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models.encryption import OrgDataKey

VERSION = 1
NONCE_BYTES = 12
KEY_BYTES = 32

#: Process-local cache of unwrapped DEKs. Keys never leave the process, and a
#: restart simply re-unwraps them.
_dek_cache: dict[uuid.UUID, bytes] = {}


class CredentialDecryptionError(RuntimeError):
    """Raised when a stored credential cannot be decrypted."""


def _kek() -> AESGCM:
    raw = get_settings().credential_kek.get_secret_value()
    if not raw:
        raise RuntimeError("CREDENTIAL_KEK is not set; refusing to handle credentials")
    try:
        key = base64.urlsafe_b64decode(raw)
    except Exception as exc:
        raise RuntimeError("CREDENTIAL_KEK must be urlsafe-base64") from exc
    if len(key) != KEY_BYTES:
        raise RuntimeError(f"CREDENTIAL_KEK must decode to {KEY_BYTES} bytes, got {len(key)}")
    return AESGCM(key)


def _aad(org_id: uuid.UUID) -> bytes:
    return str(org_id).encode()


async def get_org_key(session: AsyncSession, org_id: uuid.UUID) -> bytes:
    """Unwrap this org's DEK, creating one on first use."""
    cached = _dek_cache.get(org_id)
    if cached is not None:
        return cached

    record = await session.scalar(select(OrgDataKey).where(OrgDataKey.org_id == org_id))
    if record is None:
        dek = AESGCM.generate_key(bit_length=256)
        nonce = os.urandom(NONCE_BYTES)
        wrapped = bytes([VERSION]) + nonce + _kek().encrypt(nonce, dek, _aad(org_id))
        session.add(OrgDataKey(org_id=org_id, version=VERSION, wrapped_key=wrapped))
        await session.flush()
    else:
        blob = record.wrapped_key
        nonce, payload = blob[1 : 1 + NONCE_BYTES], blob[1 + NONCE_BYTES :]
        try:
            dek = _kek().decrypt(nonce, payload, _aad(org_id))
        except InvalidTag as exc:
            raise CredentialDecryptionError(
                "Stored data key does not match CREDENTIAL_KEK"
            ) from exc

    _dek_cache[org_id] = dek
    return dek


async def encrypt(session: AsyncSession, org_id: uuid.UUID, plaintext: str) -> bytes:
    dek = await get_org_key(session, org_id)
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(dek).encrypt(nonce, plaintext.encode(), _aad(org_id))
    return bytes([VERSION]) + nonce + ciphertext


async def decrypt(session: AsyncSession, org_id: uuid.UUID, blob: bytes) -> str:
    if not blob or blob[0] != VERSION:
        raise CredentialDecryptionError("Unsupported credential ciphertext version")
    dek = await get_org_key(session, org_id)
    nonce, payload = blob[1 : 1 + NONCE_BYTES], blob[1 + NONCE_BYTES :]
    try:
        return AESGCM(dek).decrypt(nonce, payload, _aad(org_id)).decode()
    except InvalidTag as exc:
        raise CredentialDecryptionError("Credential failed authentication") from exc


def reset_key_cache() -> None:
    """Drop cached DEKs. Used by tests and after a key rotation."""
    _dek_cache.clear()
