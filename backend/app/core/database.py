"""MongoDB client creation and connectivity checks (PyMongo native async API)."""

import asyncio
import logging
from typing import Any

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import PyMongoError

from app.core.config import Settings

logger = logging.getLogger(__name__)


def mongo_client_options(settings: Settings) -> dict[str, Any]:
    """Driver options shared by the async app client and the sync test-cleanup client."""
    return {
        "username": settings.game_data_db_user,
        "password": settings.game_data_db_password.get_secret_value(),
        # Required so Python uuid.UUID values are stored as BSON UUID subtype 4 (schema §2).
        "uuidRepresentation": "standard",
        # Return datetimes as timezone-aware UTC (schema §2: timestamps are UTC).
        "tz_aware": True,
        "serverSelectionTimeoutMS": settings.mongodb_timeout_ms,
        "connectTimeoutMS": settings.mongodb_timeout_ms,
        "appname": "operation-zero-backend",
    }


def create_mongo_client(settings: Settings) -> AsyncMongoClient:
    """Create the client. It connects lazily, on the first operation."""
    return AsyncMongoClient(settings.mongodb_uri.get_secret_value(), **mongo_client_options(settings))


async def ping(db: AsyncDatabase, timeout_seconds: float) -> bool:
    """Return True if MongoDB answers a ping within the timeout. Never raises."""
    try:
        async with asyncio.timeout(timeout_seconds):
            await db.command("ping")
        return True
    except (PyMongoError, TimeoutError) as exc:
        # Log only the error type: driver messages can include cluster host names.
        logger.warning("MongoDB ping failed: %s", type(exc).__name__)
        return False
