"""`player_data_profile` — the single home of the in-game name (DATABASE_SCHEMA.md §3.3).

Name uniqueness is enforced only by the unique index on `game_user_name_lower`.
"""

from typing import Any

from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase

from app.core.indexes import INDEX_REGISTRY, IndexSpec

COLLECTION = "player_data_profile"
NAME_INDEX = "uniq_game_user_name_lower"

INDEX_REGISTRY.register(
    IndexSpec(collection=COLLECTION, name="uniq_game_user_id", keys=(("game_user_id", 1),), unique=True),
    IndexSpec(collection=COLLECTION, name=NAME_INDEX, keys=(("game_user_name_lower", 1),), unique=True),
)


class ProfileRepository:
    def __init__(self, db: AsyncDatabase) -> None:
        self._collection = db[COLLECTION]

    async def insert(self, doc: dict[str, Any], *, session: AsyncClientSession | None = None) -> None:
        await self._collection.insert_one(doc, session=session)
