"""Authentication business rules: registration, login, token refresh, logout, request authentication.

Provider-agnostic core: everything after "which account is this?" works on `game_user_id`
only, so adding a platform login (e.g. Steam) means a new identity provider and a new
login entry point — tokens, sessions, profiles and the API shapes stay the same.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from app.core.config import Settings
from app.core.errors import AppError
from app.core.ids import new_id, utc_now
from app.core.security import (
    PASSWORD_HASH_ALGO,
    TokenExpiredError,
    TokenInvalidError,
    create_access_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    spend_password_check_time,
    verify_password,
)
from app.repositories.identities import PROVIDER_CLASSIC, IdentityRepository
from app.repositories.profiles import ProfileRepository
from app.repositories.sessions import SessionRepository
from app.repositories.users import UserRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    game_user_id: UUID
    access_token: str
    access_expires_in: int
    refresh_token: str
    refresh_expires_in: int


@dataclass(frozen=True, slots=True)
class AuthContext:
    """The authenticated caller of a request."""

    game_user_id: UUID
    session_id: UUID


# --- error constructors -----------------------------------------------------------------


def _auth_error(code: str, message: str) -> AppError:
    return AppError(status_code=401, code=code, message=message, headers={"WWW-Authenticate": "Bearer"})


def _invalid_credentials() -> AppError:
    return _auth_error("invalid_credentials", "Email or password is incorrect.")


def _session_revoked() -> AppError:
    return _auth_error("session_revoked", "This session has ended. Please log in again.")


class _ConcurrentRotation(Exception):
    """The refresh token was rotated by another request between our read and our write."""


def normalize_email(email: str) -> str:
    """The 'classic' provider_user_id: the whole address, trimmed and lower-cased (schema §3.2)."""
    return email.strip().lower()


def normalize_name(name: str) -> str:
    return name.lower()


def ensure_account_usable(user: dict[str, Any], now: datetime) -> None:
    status = user["account_status"]
    if status == "active":
        return
    if status == "banned":
        ban = user.get("ban") or {}
        until: datetime | None = ban.get("until")
        if until is not None and until <= now:
            return  # the ban has expired
        raise AppError(
            status_code=403,
            code="account_banned",
            message="This account is banned.",
            details={"reason": ban.get("reason"), "until": until.isoformat() if until else None},
        )
    raise AppError(status_code=403, code="account_unavailable", message="This account is not available.")


class AuthService:
    def __init__(self, db: AsyncDatabase, settings: Settings) -> None:
        self._db = db
        self._settings = settings
        self._users = UserRepository(db)
        self._identities = IdentityRepository(db)
        self._profiles = ProfileRepository(db)
        self._sessions = SessionRepository(db)

    # --- registration and login ---------------------------------------------------------

    async def register(
        self, *, email: str, password: str, game_user_name: str, client_info: dict[str, str] | None
    ) -> IssuedTokens:
        email_key = normalize_email(email)
        password_hash = await hash_password(password)  # before the transaction: it is slow
        now = utc_now()
        game_user_id = new_id()
        session_doc, tokens = self._new_session(
            game_user_id=game_user_id, session_epoch=0, family_id=new_id(), now=now, client_info=client_info
        )

        user_doc = {
            "game_user_id": game_user_id,
            "account_status": "active",
            "ban": None,
            "session_epoch": 0,
            "last_logged_in": now,
            "created_at": now,
            "updated_at": now,
        }
        identity_doc = {
            "game_user_id": game_user_id,
            "provider": PROVIDER_CLASSIC,
            "provider_user_id": email_key,
            "password_hash": password_hash,
            "hash_algo": PASSWORD_HASH_ALGO,
            "email_verified": False,
            "linked_at": now,
            "last_used_at": now,
        }
        profile_doc = {
            "game_user_id": game_user_id,
            "game_user_name": game_user_name,
            "game_user_name_lower": normalize_name(game_user_name),
            "name_changed_at": None,  # no rename yet, so no cooldown
            "avatar_id": None,
            "body_type": None,
            "country": None,
            "detected_region": None,
            "created_at": now,
            "updated_at": now,
        }

        async def create_account(session: AsyncClientSession) -> None:
            await self._users.insert(user_doc, session=session)
            await self._identities.insert(identity_doc, session=session)
            await self._profiles.insert(profile_doc, session=session)
            await self._sessions.insert(session_doc, session=session)

        try:
            await self._run_transaction(create_account)
        except DuplicateKeyError as exc:
            raise self._registration_conflict(exc) from None

        logger.info("Account registered (game_user_id=%s)", game_user_id)
        return tokens

    async def login(self, *, email: str, password: str, client_info: dict[str, str] | None) -> IssuedTokens:
        email_key = normalize_email(email)
        identity = await self._identities.find(PROVIDER_CLASSIC, email_key)
        if identity is None:
            await spend_password_check_time(password)  # same cost as a wrong password
            raise _invalid_credentials()

        matches, upgraded_hash = await verify_password(identity["password_hash"], password)
        if not matches:
            raise _invalid_credentials()

        now = utc_now()
        game_user_id: UUID = identity["game_user_id"]
        user = await self._users.get(game_user_id)
        if user is None:
            logger.error("Identity without user_data (game_user_id=%s)", game_user_id)
            raise _invalid_credentials()
        ensure_account_usable(user, now)  # only after the password check, so bans are not probeable

        session_doc, tokens = self._new_session(
            game_user_id=game_user_id,
            session_epoch=user["session_epoch"],
            family_id=new_id(),
            now=now,
            client_info=client_info,
        )
        await self._sessions.insert(session_doc)
        await asyncio.gather(
            self._identities.record_use(PROVIDER_CLASSIC, email_key, now, new_password_hash=upgraded_hash),
            self._users.record_login(game_user_id, now),
        )
        return tokens

    # --- refresh and logout ---------------------------------------------------------------

    async def refresh(self, *, refresh_token: str, client_info: dict[str, str] | None) -> IssuedTokens:
        now = utc_now()
        current = await self._sessions.find_by_token_hash(hash_refresh_token(refresh_token))
        if current is None:
            raise _auth_error("invalid_refresh_token", "The refresh token is not valid.")
        if current["revoked_at"] is not None:
            raise _session_revoked()
        if current["rotated_at"] is not None:
            await self._handle_reuse(current, now)
        if current["expires_at"] <= now:
            raise _auth_error("refresh_token_expired", "The refresh token has expired. Please log in again.")

        user = await self._users.get(current["game_user_id"])
        if user is None or user["session_epoch"] != current["session_epoch"]:
            raise _session_revoked()
        ensure_account_usable(user, now)

        new_doc, tokens = self._new_session(
            game_user_id=current["game_user_id"],
            session_epoch=user["session_epoch"],
            family_id=current["family_id"],
            now=now,
            client_info=client_info if client_info is not None else current.get("client_info"),
        )

        async def rotate(session: AsyncClientSession) -> None:
            if not await self._sessions.mark_rotated(current["session_id"], now, session=session):
                raise _ConcurrentRotation
            await self._sessions.insert(new_doc, session=session)

        try:
            await self._run_transaction(rotate)
        except _ConcurrentRotation:
            await self._handle_reuse(current, now)
        return tokens

    async def logout(self, ctx: AuthContext) -> None:
        """End the caller's login: revokes every rotation of the current session's family."""
        current = await self._sessions.get(ctx.session_id)
        if current is not None:
            await self._sessions.revoke_family(current["family_id"], utc_now())

    async def logout_all(self, ctx: AuthContext) -> None:
        """End every login of the account on every device."""
        now = utc_now()
        # Epoch first: also invalidates a session created by a refresh racing with this call.
        await self._users.bump_session_epoch(ctx.game_user_id, now)
        await self._sessions.revoke_all_for_user(ctx.game_user_id, now)

    # --- per-request authentication -------------------------------------------------------

    async def authenticate(self, access_token: str) -> AuthContext:
        try:
            claims = decode_access_token(access_token, self._settings)
        except TokenExpiredError:
            raise _auth_error("token_expired", "The access token has expired. Refresh it and retry.") from None
        except TokenInvalidError:
            raise _auth_error("invalid_token", "The access token is not valid.") from None

        user, session = await asyncio.gather(
            self._users.get(claims.game_user_id), self._sessions.get(claims.session_id)
        )
        if user is None or session is None or session["game_user_id"] != claims.game_user_id:
            raise _auth_error("invalid_token", "The access token is not valid.")
        if session["revoked_at"] is not None or user["session_epoch"] != claims.session_epoch:
            raise _session_revoked()
        ensure_account_usable(user, utc_now())
        return AuthContext(game_user_id=claims.game_user_id, session_id=claims.session_id)

    async def get_account(self, ctx: AuthContext) -> dict[str, Any]:
        user = await self._users.get(ctx.game_user_id)
        if user is None:
            raise _auth_error("invalid_token", "The access token is not valid.")
        return user

    # --- helpers --------------------------------------------------------------------------

    def _new_session(
        self,
        *,
        game_user_id: UUID,
        session_epoch: int,
        family_id: UUID,
        now: datetime,
        client_info: dict[str, str] | None,
    ) -> tuple[dict[str, Any], IssuedTokens]:
        session_id = new_id()
        refresh_token = new_refresh_token()
        refresh_ttl = timedelta(days=self._settings.refresh_token_ttl_days)
        doc = {
            "session_id": session_id,
            "game_user_id": game_user_id,
            "token_hash": hash_refresh_token(refresh_token),
            "family_id": family_id,
            "session_epoch": session_epoch,
            "created_at": now,
            "expires_at": now + refresh_ttl,
            "rotated_at": None,
            "revoked_at": None,
            "client_info": client_info,
        }
        tokens = IssuedTokens(
            game_user_id=game_user_id,
            access_token=create_access_token(
                game_user_id=game_user_id,
                session_id=session_id,
                session_epoch=session_epoch,
                settings=self._settings,
                now=now,
            ),
            access_expires_in=self._settings.access_token_ttl_seconds,
            refresh_token=refresh_token,
            refresh_expires_in=int(refresh_ttl.total_seconds()),
        )
        return doc, tokens

    async def _handle_reuse(self, session: dict[str, Any], now: datetime) -> None:
        """A rotated refresh token was presented again: assume theft and end the whole login."""
        await self._sessions.revoke_family(session["family_id"], now)
        logger.warning(
            "Refresh token reuse detected; session family revoked (game_user_id=%s)", session["game_user_id"]
        )
        raise _auth_error("refresh_token_reused", "This refresh token was already used. Please log in again.")

    async def _run_transaction(self, callback) -> None:
        # with_transaction retries transient errors (e.g. write conflicts from concurrent requests).
        async with self._db.client.start_session() as session:
            await session.with_transaction(callback)

    @staticmethod
    def _registration_conflict(exc: DuplicateKeyError) -> Exception:
        key_pattern = (exc.details or {}).get("keyPattern", {})
        if "provider_user_id" in key_pattern:
            return AppError(status_code=409, code="email_taken", message="An account with this email already exists.")
        if "game_user_name_lower" in key_pattern:
            return AppError(status_code=409, code="name_taken", message="That in-game name is already taken.")
        return exc  # unexpected (e.g. UUID collision): surface as a 500
