"""Declarative MongoDB index registry.

Each module registers the indexes its collections need; the app applies all of
them idempotently at startup. Changing an existing index (same name, different
definition) is refused: that needs an explicit migration, not a silent rebuild.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pymongo import IndexModel
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import OperationFailure

# MongoDB server error codes for "an index with this name/keys exists with a different definition".
_INDEX_CONFLICT_CODES = {85, 86}  # IndexOptionsConflict, IndexKeySpecsConflict


class IndexConflictError(RuntimeError):
    """A declared index conflicts with an existing index in the database."""


@dataclass(frozen=True, slots=True)
class IndexSpec:
    collection: str
    name: str
    keys: tuple[tuple[str, int], ...]
    unique: bool = False
    partial_filter: Mapping[str, Any] | None = None
    expire_after_seconds: int | None = None

    def to_model(self) -> IndexModel:
        options: dict[str, Any] = {"name": self.name, "unique": self.unique}
        if self.partial_filter is not None:
            options["partialFilterExpression"] = dict(self.partial_filter)
        if self.expire_after_seconds is not None:
            options["expireAfterSeconds"] = self.expire_after_seconds
        return IndexModel(list(self.keys), **options)


class IndexRegistry:
    def __init__(self) -> None:
        self._specs: dict[tuple[str, str], IndexSpec] = {}

    def register(self, *specs: IndexSpec) -> None:
        for spec in specs:
            key = (spec.collection, spec.name)
            existing = self._specs.get(key)
            if existing is not None and existing != spec:
                raise ValueError(f"Index '{spec.name}' on '{spec.collection}' is registered twice with different definitions")
            self._specs[key] = spec

    def specs(self) -> list[IndexSpec]:
        return list(self._specs.values())


# Application-wide registry. Milestone modules register their collections' indexes here.
INDEX_REGISTRY = IndexRegistry()


async def ensure_indexes(db: AsyncDatabase, specs: Iterable[IndexSpec]) -> None:
    by_collection: dict[str, list[IndexSpec]] = defaultdict(list)
    for spec in specs:
        by_collection[spec.collection].append(spec)

    for collection, collection_specs in by_collection.items():
        try:
            await db[collection].create_indexes([spec.to_model() for spec in collection_specs])
        except OperationFailure as exc:
            if exc.code in _INDEX_CONFLICT_CODES:
                names = ", ".join(spec.name for spec in collection_specs)
                raise IndexConflictError(
                    f"Indexes [{names}] on '{collection}' conflict with existing indexes. "
                    "Changing an existing index requires an explicit migration."
                ) from exc
            raise
