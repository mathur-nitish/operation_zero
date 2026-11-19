"""Shared fixtures.

Database tests run with APP_ENV=test against MONGODB_DB_NAME_TEST. The
test database is emptied (collection by collection) before and after the session;
fixtures refuse to touch any database whose name does not end in '_test'.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI
from pymongo import MongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import TEST_DB_SUFFIX, Settings, load_settings
from app.core.database import create_mongo_client, mongo_client_options
from app.core.indexes import INDEX_REGISTRY
from app.main import create_app

TEST_JWT_SECRET = "test-only-jwt-secret-0123456789-abcdefghij"


def _assert_test_database(name: str) -> None:
    if not name.endswith(TEST_DB_SUFFIX):
        pytest.exit(f"Refusing to run tests against database '{name}': name must end with '{TEST_DB_SUFFIX}'", 2)


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    # Tests sign tokens with their own key, independent of the developer's .env.
    settings = load_settings(app_env="test", jwt_secret=TEST_JWT_SECRET)
    _assert_test_database(settings.mongodb_db_name)
    return settings


@pytest.fixture(scope="session")
def clean_test_database(test_settings: Settings):
    """Empty the test database before and after the session (sync client: no event-loop coupling)."""
    _assert_test_database(test_settings.mongodb_db_name)
    client = MongoClient(test_settings.mongodb_uri.get_secret_value(), **mongo_client_options(test_settings))
    db = client[test_settings.mongodb_db_name]

    def drop_all() -> None:
        # Drop collections individually: dropDatabase needs a broader role than readWrite.
        for name in db.list_collection_names():
            db.drop_collection(name)

    drop_all()
    yield
    drop_all()
    client.close()


@pytest.fixture
async def mongo_db(test_settings: Settings, clean_test_database) -> AsyncIterator[AsyncDatabase]:
    client = create_mongo_client(test_settings)
    try:
        yield client[test_settings.mongodb_db_name]
    finally:
        await client.close()


AppClientFactory = Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]]


@pytest.fixture
def app_client(test_settings: Settings, clean_test_database) -> AppClientFactory:
    """Factory: `async with app_client(app=..., settings=...) as client:` runs the app's lifespan."""

    @asynccontextmanager
    async def factory(
        app: FastAPI | None = None, settings: Settings | None = None
    ) -> AsyncIterator[httpx.AsyncClient]:
        # The real registry: auth tests rely on the unique indexes existing.
        app = app or create_app(settings or test_settings, INDEX_REGISTRY)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                yield client

    return factory
