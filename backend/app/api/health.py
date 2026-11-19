"""Liveness and readiness probes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pymongo.asynchronous.database import AsyncDatabase

from app.api.deps import get_app_settings, get_db
from app.core.config import Settings
from app.core.database import ping
from app.schemas.common import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthResponse, summary="Liveness: the process is running")
async def liveness() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get(
    "/ready",
    response_model=HealthResponse,
    summary="Readiness: dependencies are reachable",
    responses={503: {"model": HealthResponse, "description": "A dependency is unavailable"}},
)
async def readiness(
    response: Response,
    db: Annotated[AsyncDatabase, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> HealthResponse:
    mongodb_ok = await ping(db, settings.readiness_timeout_seconds)
    if not mongodb_ok:
        response.status_code = 503
        return HealthResponse(status="unavailable", checks={"mongodb": "unavailable"})
    return HealthResponse(status="ok", checks={"mongodb": "ok"})
