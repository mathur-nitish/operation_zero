"""Application settings, loaded from environment variables and backend/.env.

Real environment variables take precedence over values in the .env file.
Secrets are held as ``SecretStr`` and configuration errors never include
setting values, so a bad configuration cannot leak credentials into logs.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BACKEND_DIR / ".env"

TEST_DB_SUFFIX = "_test"

_DB_NAME_VAR_BY_ENV = {
    "production": "MONGODB_DB_NAME_PROD",
    "development": "MONGODB_DB_NAME_DEV",
    "test": "MONGODB_DB_NAME_TEST",
}


class ConfigError(RuntimeError):
    """Settings are missing or invalid. The message never contains setting values."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # MongoDB. The URI must not embed credentials; they are passed to the driver separately.
    mongodb_uri: SecretStr
    game_data_db_user: str = Field(min_length=1)
    game_data_db_password: SecretStr
    # One database per environment; APP_ENV selects which one is used (see mongodb_db_name).
    # Only the selected environment's name is required.
    mongodb_db_name_prod: str | None = Field(default=None, min_length=1)
    mongodb_db_name_dev: str | None = Field(default=None, min_length=1)
    mongodb_db_name_test: str | None = Field(default=None, min_length=1)
    mongodb_timeout_ms: int = Field(default=5000, ge=100, le=60_000)

    readiness_timeout_seconds: float = Field(default=3.0, gt=0, le=30)

    # Authentication (M1). Access tokens are HS256 JWTs; refresh tokens are opaque and stored hashed.
    jwt_secret: SecretStr
    jwt_issuer: str = Field(default="operation-zero", min_length=1)
    access_token_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    refresh_token_ttl_days: int = Field(default=30, ge=1, le=90)

    @field_validator("jwt_secret")
    @classmethod
    def _jwt_secret_is_strong(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("must be at least 32 characters")
        return value

    @field_validator("mongodb_uri")
    @classmethod
    def _uri_is_credential_free(cls, value: SecretStr) -> SecretStr:
        parts = urlsplit(value.get_secret_value())
        if parts.scheme not in ("mongodb", "mongodb+srv"):
            raise ValueError("must start with mongodb:// or mongodb+srv://")
        if not parts.netloc:
            raise ValueError("must include a host")
        if "@" in parts.netloc:
            raise ValueError(
                "must not contain credentials; set GAME_DATA_DB_USER and GAME_DATA_DB_PASSWORD instead"
            )
        return value

    @field_validator("game_data_db_password")
    @classmethod
    def _password_not_empty(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value():
            raise ValueError("must not be empty")
        return value

    @model_validator(mode="after")
    def _database_names_are_safe(self) -> Self:
        names = {
            "MONGODB_DB_NAME_PROD": self.mongodb_db_name_prod,
            "MONGODB_DB_NAME_DEV": self.mongodb_db_name_dev,
            "MONGODB_DB_NAME_TEST": self.mongodb_db_name_test,
        }
        selected = _DB_NAME_VAR_BY_ENV[self.app_env]
        if names[selected] is None:
            raise ValueError(f"{selected} is required when APP_ENV={self.app_env}")
        if self.mongodb_db_name_test is not None and not self.mongodb_db_name_test.endswith(TEST_DB_SUFFIX):
            # Tests empty this database, so its name must make that obvious.
            raise ValueError(f"MONGODB_DB_NAME_TEST must end with '{TEST_DB_SUFFIX}'")
        configured = [name for name in names.values() if name is not None]
        if len(configured) != len(set(configured)):
            raise ValueError("MONGODB_DB_NAME_PROD, _DEV and _TEST must all be different databases")
        return self

    @property
    def mongodb_db_name(self) -> str:
        """The database for the current APP_ENV (guaranteed set by validation)."""
        name = {
            "production": self.mongodb_db_name_prod,
            "development": self.mongodb_db_name_dev,
            "test": self.mongodb_db_name_test,
        }[self.app_env]
        assert name is not None
        return name


def load_settings(**overrides: Any) -> Settings:
    """Build settings, converting validation failures into a value-free ConfigError."""
    try:
        return Settings(**overrides)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']).upper() or 'SETTINGS'}: {err['msg']}"
            for err in exc.errors(include_input=False, include_url=False, include_context=False)
        )
        # 'from None' drops the original exception, whose text includes input values.
        raise ConfigError(f"Invalid backend configuration: {problems}") from None


@lru_cache
def get_settings() -> Settings:
    return load_settings()
