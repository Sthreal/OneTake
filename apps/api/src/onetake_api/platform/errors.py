from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from onetake_api.platform.request_context import get_request_id

logger = logging.getLogger(__name__)


class DomainError(Exception):
    code = "DOMAIN_ERROR"
    http_status = 400
    retryable = False

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "retryable": exc.retryable,
                },
                "request_id": get_request_id(),
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "服务器内部错误",
                    "retryable": False,
                },
                "request_id": get_request_id(),
            },
        )