"""Identifier and time helpers shared by all modules."""

import uuid
from datetime import UTC, datetime


def new_id() -> uuid.UUID:
    """Time-ordered UUIDv7 (schema decision 16). Stored in MongoDB as BSON UUID."""
    return uuid.uuid7()


def utc_now() -> datetime:
    """Current time as a timezone-aware UTC datetime (schema §2: native BSON Date, UTC)."""
    return datetime.now(UTC)
