"""`user_data` — account status, bans and the session epoch (DATABASE_SCHEMA.md §3.1)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase

from app.core.indexes import INDEX_REGISTRY, IndexSpec

COLLECTION = "user_data"

INDEX_REGISTRY.register(
    IndexSpec(collection=COLLECTION, name="uniq_game_user_id", keys=(("game_user_id", 1),), unique=True),
)


class UserRepository:
    def __init__(self, db: AsyncDatabase) -> None:
        self._collection = db[COLLECTION]

    async def insert(self, doc: dict[str, Any], *, session: AsyncClientSession | None = None) -> None:
        await self._collection.insert_one(doc, session=session)

    async def get(self, game_user_id: UUID) -> dict[str, Any] | None:
        return await self._collection.find_one({"game_user_id": game_user_id}, {"_id": 0})

    async def record_login(self, game_user_id: UUID, now: datetime) -> None:
        await self._collection.update_one(
            {"game_user_id": game_user_id}, {"$set": {"last_logged_in": now, "updated_at": now}}
        )

    async def bump_session_epoch(self, game_user_id: UUID, now: datetime) -> None:
        """Invalidate every access token issued so far for this account."""
        await self._collection.update_one(
            {"game_user_id": game_user_id}, {"$inc": {"session_epoch": 1}, "$set": {"updated_at": now}}
        )
