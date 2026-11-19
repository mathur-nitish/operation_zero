"""Password hashing and token primitives. No database access here."""

import asyncio
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import Settings
from app.core.ids import utc_now

# ---------------------------------------------------------------------------
# Passwords — Argon2id with argon2-cffi's defaults (RFC 9106 low-memory profile).
# Hashing is CPU/memory heavy, so it runs in a worker thread to keep the event loop free.
# ---------------------------------------------------------------------------

PASSWORD_HASH_ALGO = "argon2id"
_hasher = PasswordHasher()


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_hasher.hash, password)


async def verify_password(stored_hash: str, password: str) -> tuple[bool, str | None]:
    """Return (matches, upgraded_hash). upgraded_hash is set when the stored hash uses outdated parameters."""

    def _verify() -> tuple[bool, str | None]:
        try:
            _hasher.verify(stored_hash, password)
        except (VerificationError, InvalidHashError):
            return False, None
        return True, (_hasher.hash(password) if _hasher.check_needs_rehash(stored_hash) else None)

    return await asyncio.to_thread(_verify)


@lru_cache(maxsize=1)
def _timing_dummy_hash() -> str:
    return _hasher.hash("operation-zero-timing-equaliser")


async def spend_password_check_time(password: str) -> None:
    """Do the same work as a real verify, so unknown accounts are not distinguishable by response time."""
    dummy = await asyncio.to_thread(_timing_dummy_hash)
    await verify_password(dummy, password)


# ---------------------------------------------------------------------------
# Access tokens — short-lived HS256 JWTs.
# ---------------------------------------------------------------------------

_JWT_ALGORITHM = "HS256"
_ACCESS_TOKEN_TYPE = "access"
_REQUIRED_CLAIMS = ["iss", "sub", "sid", "epoch", "typ", "iat", "exp"]


class TokenError(Exception):
    pass


class TokenExpiredError(TokenError):
    pass


class TokenInvalidError(TokenError):
    pass


@dataclass(frozen=True, slots=True)
class AccessClaims:
    game_user_id: UUID
    session_id: UUID
    session_epoch: int


def create_access_token(
    *, game_user_id: UUID, session_id: UUID, session_epoch: int, settings: Settings, now: datetime | None = None
) -> str:
    issued_at = int((now or utc_now()).timestamp())
    payload = {
        "iss": settings.jwt_issuer,
        "sub": str(game_user_id),
        "sid": str(session_id),
        "epoch": session_epoch,
        "typ": _ACCESS_TOKEN_TYPE,
        "iat": issued_at,
        "exp": issued_at + settings.access_token_ttl_seconds,
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=_JWT_ALGORITHM)


def decode_access_token(token: str, settings: Settings) -> AccessClaims:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[_JWT_ALGORITHM],  # fixed list: rejects 'none' and algorithm confusion
            issuer=settings.jwt_issuer,
            options={"require": _REQUIRED_CLAIMS},
            leeway=5,
        )
    except jwt.ExpiredSignatureError:
        raise TokenExpiredError from None
    except jwt.InvalidTokenError:
        raise TokenInvalidError from None

    epoch = claims["epoch"]
    if claims["typ"] != _ACCESS_TOKEN_TYPE or not isinstance(epoch, int) or isinstance(epoch, bool):
        raise TokenInvalidError
    try:
        return AccessClaims(game_user_id=UUID(claims["sub"]), session_id=UUID(claims["sid"]), session_epoch=epoch)
    except (ValueError, TypeError, AttributeError):
        raise TokenInvalidError from None


# ---------------------------------------------------------------------------
# Refresh tokens — 256-bit random opaque strings. Only their SHA-256 is stored.
# (A fast hash is sufficient: the token has full entropy, unlike a password.)
# ---------------------------------------------------------------------------


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
