"""Consistent error envelope for every error response.

    { "error": { "code": str, "message": str, "details": any | null, "request_id": str | null } }

Validation errors never echo submitted values (they may contain passwords), and
unexpected errors never expose exception text to the client.
"""

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import REQUEST_ID_HEADER
from app.schemas.common import ErrorBody, ErrorResponse

logger = logging.getLogger(__name__)

_HTTP_STATUS_CODES = {
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
}


class AppError(Exception):
    """Raise from services to return a specific error code to the client."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details, request_id=request_id))
    response_headers = dict(headers or {})
    if request_id:
        response_headers[REQUEST_ID_HEADER] = request_id
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"), headers=response_headers)


async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return error_response(request, exc.status_code, exc.code, exc.message, exc.details, exc.headers)


async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [{"loc": list(err["loc"]), "message": err["msg"], "type": err["type"]} for err in exc.errors()]
    return error_response(request, 422, "validation_error", "Request validation failed.", details)


async def _http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _HTTP_STATUS_CODES.get(exc.status_code, "http_error")
    message = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
    return error_response(request, exc.status_code, code, message, headers=exc.headers)


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return error_response(request, 500, "internal_error", "An unexpected error occurred.")


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
