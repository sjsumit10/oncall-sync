"""Org-scoped data access.

The first belt of tenant isolation: every query for tenant-owned data goes through
here, so ``org_id`` is applied by construction rather than by remembering. Postgres
RLS (see the initial migration) is the second belt, catching anything that bypasses
this layer.
"""

import uuid
from typing import Any, Protocol, TypeVar, cast

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession


class HasOrgId(Protocol):
    org_id: Any
    id: Any


ModelT = TypeVar("ModelT", bound=HasOrgId)


class OrgScope:
    """Query helper bound to one organization."""

    def __init__(self, session: AsyncSession, org_id: uuid.UUID) -> None:
        self.session = session
        self.org_id = org_id

    def select(self, model: type[ModelT]) -> Select[tuple[ModelT]]:
        return select(model).where(model.org_id == self.org_id)

    async def get(self, model: type[ModelT], record_id: uuid.UUID) -> ModelT | None:
        """Fetch by id, returning None for rows belonging to another org."""
        return cast(
            ModelT | None,
            await self.session.scalar(self.select(model).where(model.id == record_id)),
        )

    async def list(self, model: type[ModelT], *criteria: Any) -> list[ModelT]:
        result = await self.session.scalars(self.select(model).where(*criteria))
        return list(result)

    def add(self, instance: ModelT) -> ModelT:
        instance.org_id = self.org_id
        self.session.add(instance)
        return instance
