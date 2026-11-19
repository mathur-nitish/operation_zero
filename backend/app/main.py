"""Application factory.

Run locally:  uvicorn app.main:create_app --factory --reload
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_v1_router
from app.core.config import Settings, get_settings
from app.core.database import create_mongo_client
from app.core.errors import install_error_handlers
from app.core.indexes import INDEX_REGISTRY, IndexRegistry, ensure_indexes
from app.core.logging_config import configure_logging
from app.core.request_context import RequestIdMiddleware

logger = logging.getLogger(__name__)

API_V1_PREFIX = "/v1"


def create_app(settings: Settings | None = None, index_registry: IndexRegistry | None = None) -> FastAPI:
    settings = settings or get_settings()
    registry = index_registry if index_registry is not None else INDEX_REGISTRY
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        client = create_mongo_client(settings)
        try:
            db = client[settings.mongodb_db_name]
            await ensure_indexes(db, registry.specs())
            app.state.mongo_client = client
            app.state.db = db
            logger.info("Backend started (env=%s, database=%s)", settings.app_env, settings.mongodb_db_name)
            yield
        finally:
            await client.close()
            logger.info("Backend stopped")

    app = FastAPI(title="Operation Zero Backend", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(RequestIdMiddleware)
    install_error_handlers(app)
    app.include_router(api_v1_router, prefix=API_V1_PREFIX)
    return app
