import uuid

import pytest
from pymongo.errors import DuplicateKeyError

from app.core.indexes import IndexConflictError, IndexRegistry, IndexSpec, ensure_indexes


def scratch_collection() -> str:
    return f"m0_index_test_{uuid.uuid4().hex[:8]}"


async def test_ensure_indexes_creates_unique_index_and_is_idempotent(mongo_db):
    collection = scratch_collection()
    spec = IndexSpec(collection=collection, name="uniq_code", keys=(("code", 1),), unique=True)

    await ensure_indexes(mongo_db, [spec])
    await ensure_indexes(mongo_db, [spec])  # second run must be a no-op

    info = await mongo_db[collection].index_information()
    assert info["uniq_code"]["unique"] is True
    await mongo_db[collection].insert_one({"code": "a"})
    with pytest.raises(DuplicateKeyError):
        await mongo_db[collection].insert_one({"code": "a"})


async def test_partial_filter_and_ttl_options_are_applied(mongo_db):
    collection = scratch_collection()
    await ensure_indexes(
        mongo_db,
        [
            IndexSpec(
                collection=collection,
                name="uniq_reward",
                keys=(("reason", 1), ("ref_id", 1)),
                unique=True,
                partial_filter={"reason": "match_reward"},
            ),
            IndexSpec(collection=collection, name="ttl_expires", keys=(("expires_at", 1),), expire_after_seconds=0),
        ],
    )
    info = await mongo_db[collection].index_information()
    assert info["uniq_reward"]["partialFilterExpression"] == {"reason": "match_reward"}
    assert info["ttl_expires"]["expireAfterSeconds"] == 0


async def test_changing_an_existing_index_definition_is_refused(mongo_db):
    collection = scratch_collection()
    await ensure_indexes(mongo_db, [IndexSpec(collection=collection, name="by_code", keys=(("code", 1),))])
    changed = IndexSpec(collection=collection, name="by_code", keys=(("code", 1),), unique=True)
    with pytest.raises(IndexConflictError, match="explicit migration"):
        await ensure_indexes(mongo_db, [changed])


def test_registry_accepts_identical_reregistration():
    registry = IndexRegistry()
    spec = IndexSpec(collection="c", name="i", keys=(("a", 1),))
    registry.register(spec)
    registry.register(spec)
    assert registry.specs() == [spec]


def test_registry_rejects_conflicting_definitions():
    registry = IndexRegistry()
    registry.register(IndexSpec(collection="c", name="i", keys=(("a", 1),)))
    with pytest.raises(ValueError, match="different definitions"):
        registry.register(IndexSpec(collection="c", name="i", keys=(("a", 1),), unique=True))
