"""`auth_sessions` — refresh-token sessions (DATABASE_SCHEMA.md §3.9).

Each login starts a *family*; every refresh rotates to a new session in the same
family. Rotated sessions are kept until they expire so a replayed (stolen) refresh
token can be detected. MongoDB's TTL monitor deletes documents after `expires_at`.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase

from app.core.indexes import INDEX_REGISTRY, IndexSpec

COLLECTION = "auth_sessions"

INDEX_REGISTRY.register(
    IndexSpec(collection=COLLECTION, name="uniq_session_id", keys=(("session_id", 1),), unique=True),
    IndexSpec(collection=COLLECTION, name="uniq_token_hash", keys=(("token_hash", 1),), unique=True),
    IndexSpec(collection=COLLECTION, name="by_game_user_id", keys=(("game_user_id", 1),)),
    IndexSpec(collection=COLLECTION, name="by_family_id", keys=(("family_id", 1),)),
    IndexSpec(collection=COLLECTION, name="ttl_expires_at", keys=(("expires_at", 1),), expire_after_seconds=0),
)


class SessionRepository:
    def __init__(self, db: AsyncDatabase) -> None:
        self._collection = db[COLLECTION]

    async def insert(self, doc: dict[str, Any], *, session: AsyncClientSession | None = None) -> None:
        await self._collection.insert_one(doc, session=session)

    async def get(self, session_id: UUID) -> dict[str, Any] | None:
        return await self._collection.find_one({"session_id": session_id}, {"_id": 0})

    async def find_by_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        return await self._collection.find_one({"token_hash": token_hash}, {"_id": 0})

    async def mark_rotated(self, session_id: UUID, now: datetime, *, session: AsyncClientSession) -> bool:
        """Atomically claim a live session for rotation. False if it was already rotated or revoked."""
        result = await self._collection.update_one(
            {"session_id": session_id, "rotated_at": None, "revoked_at": None},
            {"$set": {"rotated_at": now}},
            session=session,
        )
        return result.modified_count == 1

    async def revoke_family(self, family_id: UUID, now: datetime) -> None:
        await self._collection.update_many({"family_id": family_id, "revoked_at": None}, {"$set": {"revoked_at": now}})

    async def revoke_all_for_user(self, game_user_id: UUID, now: datetime) -> None:
        await self._collection.update_many(
            {"game_user_id": game_user_id, "revoked_at": None}, {"$set": {"revoked_at": now}}
        )
