"""FastAPI dependencies for shared application resources and authentication."""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import Settings
from app.core.errors import AppError
from app.services.auth import AuthContext, AuthService


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> AsyncDatabase:
    return request.app.state.db


def get_auth_service(
    db: Annotated[AsyncDatabase, Depends(get_db)], settings: Annotated[Settings, Depends(get_app_settings)]
) -> AuthService:
    return AuthService(db, settings)


# auto_error=False so a missing header produces our error envelope, not FastAPI's default body.
_bearer = HTTPBearer(auto_error=False, description="Access token from /v1/auth/login, /register or /refresh.")


async def get_current_player(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthContext:
    if credentials is None:
        raise AppError(
            status_code=401,
            code="not_authenticated",
            message="Missing bearer access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await service.authenticate(credentials.credentials)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
CurrentPlayer = Annotated[AuthContext, Depends(get_current_player)]
