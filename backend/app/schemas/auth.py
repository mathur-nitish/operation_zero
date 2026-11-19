"""Auth request/response models. `extra="forbid"` rejects unknown fields (no mass assignment)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr

# D6: length-only password rule (no composition rules), Argon2id-hashed.
PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 128
# D7: 3–16 ASCII letters, digits or underscore; uniqueness is case-insensitive.
GAME_USER_NAME_PATTERN = r"^[A-Za-z0-9_]{3,16}$"


class ClientInfo(BaseModel):
    """Optional client description stored on the session (helps users recognise their logins)."""

    model_config = ConfigDict(extra="forbid")

    platform: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9._-]+$", examples=["windows"])
    build: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._+-]+$", examples=["0.1.0+1234"])


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: SecretStr = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    game_user_name: str = Field(pattern=GAME_USER_NAME_PATTERN, examples=["Ghost_01"])
    client_info: ClientInfo | None = None


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    # No minimum here: length rules may change, and existing passwords must still work.
    password: SecretStr = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)
    client_info: ClientInfo | None = None


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: SecretStr = Field(min_length=1, max_length=512)
    client_info: ClientInfo | None = None


class AuthTokensResponse(BaseModel):
    game_user_id: UUID
    token_type: Literal["Bearer"] = "Bearer"
    access_token: str
    expires_in: int = Field(description="Access token lifetime in seconds.")
    refresh_token: str
    refresh_expires_in: int = Field(description="Refresh token lifetime in seconds.")


class AccountResponse(BaseModel):
    game_user_id: UUID
    account_status: Literal["active", "banned", "pending_deletion", "deleted"]
    created_at: datetime
