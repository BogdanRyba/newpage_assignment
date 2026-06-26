"""Explicit error types + a single FastAPI exception layer.

Expected failure modes get typed exceptions and a clean HTTP status — no bare
500s for things we anticipate (missing repo, repo still indexing, bad upload).
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.logging import get_logger

log = get_logger("api")


class AriadneError(Exception):
    """Base class for expected, mapped failures."""

    status_code = 400
    code = "ariadne_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class RepoNotFound(AriadneError):
    status_code = 404
    code = "repo_not_found"


class RepoNotReady(AriadneError):
    status_code = 409
    code = "repo_not_ready"


class FileNotIndexed(AriadneError):
    status_code = 404
    code = "file_not_indexed"


class IngestError(AriadneError):
    status_code = 422
    code = "ingest_error"


class BudgetExceeded(AriadneError):
    status_code = 429
    code = "budget_exceeded"


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AriadneError)
    async def _handle_ariadne(_: Request, exc: AriadneError) -> JSONResponse:
        log.info("handled_error", code=exc.code, message=exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "Internal server error"}},
        )
