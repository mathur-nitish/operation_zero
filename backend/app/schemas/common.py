"""Response models shared across the API."""

from typing import Any, Literal

from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


CheckStatus = Literal["ok", "unavailable"]


class HealthResponse(BaseModel):
    status: CheckStatus
    checks: dict[str, CheckStatus] = {}
