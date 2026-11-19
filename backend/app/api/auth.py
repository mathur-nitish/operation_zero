"""/v1/auth — registration, login, token refresh, logout. Contracts: docs/API_CONTRACTS.md §3.2."""

from fastapi import APIRouter, Response, status

from app.api.deps import AuthServiceDep, CurrentPlayer
from app.schemas.auth import (
    AccountResponse,
    AuthTokensResponse,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
)
from app.schemas.common import ErrorResponse
from app.services.auth import IssuedTokens

router = APIRouter(prefix="/auth", tags=["auth"])

_UNAUTHORIZED = {401: {"model": ErrorResponse, "description": "Not authenticated / session ended"}}
_FORBIDDEN = {403: {"model": ErrorResponse, "description": "Account banned or unavailable"}}


def _tokens_response(tokens: IssuedTokens) -> AuthTokensResponse:
    return AuthTokensResponse(
        game_user_id=tokens.game_user_id,
        access_token=tokens.access_token,
        expires_in=tokens.access_expires_in,
        refresh_token=tokens.refresh_token,
        refresh_expires_in=tokens.refresh_expires_in,
    )


def _client_info(body: RegisterRequest | LoginRequest | RefreshRequest) -> dict[str, str] | None:
    return body.client_info.model_dump() if body.client_info else None


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=AuthTokensResponse,
    summary="Create an account (email + password + in-game name) and log in",
    responses={409: {"model": ErrorResponse, "description": "email_taken or name_taken"}},
)
async def register(body: RegisterRequest, service: AuthServiceDep) -> AuthTokensResponse:
    tokens = await service.register(
        email=str(body.email),
        password=body.password.get_secret_value(),
        game_user_name=body.game_user_name,
        client_info=_client_info(body),
    )
    return _tokens_response(tokens)


@router.post(
    "/login",
    response_model=AuthTokensResponse,
    summary="Log in with email and password",
    responses={**_UNAUTHORIZED, **_FORBIDDEN},
)
async def login(body: LoginRequest, service: AuthServiceDep) -> AuthTokensResponse:
    tokens = await service.login(
        email=str(body.email), password=body.password.get_secret_value(), client_info=_client_info(body)
    )
    return _tokens_response(tokens)


@router.post(
    "/refresh",
    response_model=AuthTokensResponse,
    summary="Exchange a refresh token for a new token pair (the old refresh token stops working)",
    responses={**_UNAUTHORIZED, **_FORBIDDEN},
)
async def refresh(body: RefreshRequest, service: AuthServiceDep) -> AuthTokensResponse:
    tokens = await service.refresh(
        refresh_token=body.refresh_token.get_secret_value(), client_info=_client_info(body)
    )
    return _tokens_response(tokens)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End the current login",
    responses=_UNAUTHORIZED,
)
async def logout(player: CurrentPlayer, service: AuthServiceDep) -> Response:
    await service.logout(player)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/logout-all",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End every login of this account on every device",
    responses=_UNAUTHORIZED,
)
async def logout_all(player: CurrentPlayer, service: AuthServiceDep) -> Response:
    await service.logout_all(player)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/me",
    response_model=AccountResponse,
    summary="The authenticated account",
    responses={**_UNAUTHORIZED, **_FORBIDDEN},
)
async def me(player: CurrentPlayer, service: AuthServiceDep) -> AccountResponse:
    account = await service.get_account(player)
    return AccountResponse(
        game_user_id=account["game_user_id"],
        account_status=account["account_status"],
        created_at=account["created_at"],
    )
