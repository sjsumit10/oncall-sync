"""Envelope encryption of provider credentials."""

import uuid

import pytest
from sqlalchemy import select

from app.core.crypto import CredentialDecryptionError, decrypt, encrypt, reset_key_cache
from app.db.models import OrgDataKey
from app.db.session import SessionLocal, set_current_org
from tests.conftest import make_org


async def test_round_trip(org_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        blob = await encrypt(session, org_id, "pd-api-key-abc123")
        await session.commit()
        assert b"pd-api-key-abc123" not in blob
        assert await decrypt(session, org_id, blob) == "pd-api-key-abc123"


async def test_a_data_key_is_created_once_per_org(org_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        await encrypt(session, org_id, "one")
        await encrypt(session, org_id, "two")
        await session.commit()

    reset_key_cache()
    async with SessionLocal() as session:
        keys = list(await session.scalars(select(OrgDataKey).where(OrgDataKey.org_id == org_id)))
    assert len(keys) == 1


async def test_ciphertext_does_not_transfer_between_orgs(org_id: uuid.UUID) -> None:
    """The org id is bound in as AAD, so a stolen blob is useless elsewhere.

    Even handed the other tenant's own data key, the ciphertext fails to
    authenticate rather than decrypting to something plausible.
    """
    async with SessionLocal() as session:
        blob = await encrypt(session, org_id, "secret-value")
        await session.commit()

    other_id = await make_org("Other")
    set_current_org(other_id)
    async with SessionLocal() as session:
        with pytest.raises(CredentialDecryptionError):
            await decrypt(session, other_id, blob)


async def test_survives_a_process_restart(org_id: uuid.UUID) -> None:
    """The wrapped key round-trips through the KEK, not just the in-memory cache."""
    async with SessionLocal() as session:
        blob = await encrypt(session, org_id, "persisted-token")
        await session.commit()

    reset_key_cache()  # stands in for a fresh process

    async with SessionLocal() as session:
        assert await decrypt(session, org_id, blob) == "persisted-token"


async def test_tampered_ciphertext_is_rejected(org_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        blob = bytearray(await encrypt(session, org_id, "authentic"))
        await session.commit()
        blob[-1] ^= 0xFF
        with pytest.raises(CredentialDecryptionError):
            await decrypt(session, org_id, bytes(blob))
