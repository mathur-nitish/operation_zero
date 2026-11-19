"""`auth_identities` — login methods linked to an account (DATABASE_SCHEMA.md §3.2).

One account can have several identities (e.g. 'classic' email login now, 'steam' later).
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase

from app.core.indexes import INDEX_REGISTRY, IndexSpec

COLLECTION = "auth_identities"

PROVIDER_CLASSIC = "classic"

INDEX_REGISTRY.register(
    IndexSpec(
        collection=COLLECTION,
        name="uniq_provider_user",
        keys=(("provider", 1), ("provider_user_id", 1)),
        unique=True,
    ),
    IndexSpec(collection=COLLECTION, name="by_game_user_id", keys=(("game_user_id", 1),)),
)


class IdentityRepository:
    def __init__(self, db: AsyncDatabase) -> None:
        self._collection = db[COLLECTION]

    async def insert(self, doc: dict[str, Any], *, session: AsyncClientSession | None = None) -> None:
        await self._collection.insert_one(doc, session=session)

    async def find(self, provider: str, provider_user_id: str) -> dict[str, Any] | None:
        return await self._collection.find_one(
            {"provider": provider, "provider_user_id": provider_user_id}, {"_id": 0}
        )

    async def record_use(
        self, provider: str, provider_user_id: str, now: datetime, *, new_password_hash: str | None = None
    ) -> None:
        update: dict[str, Any] = {"last_used_at": now}
        if new_password_hash is not None:
            update["password_hash"] = new_password_hash
        await self._collection.update_one({"provider": provider, "provider_user_id": provider_user_id}, {"$set": update})
