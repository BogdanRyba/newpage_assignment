"""FastAPI application factory.

The HTTP layer stays thin: it wires middleware, error handling and routers, then
delegates to services. No business logic lives here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, get_logger

log = get_logger("api")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    log.info("startup")
    yield
    log.info("shutdown")


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="Ariadne API", version="0.1.0", lifespan=lifespan)

    # Dev CORS: the Next.js frontend talks to this API from the browser.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)
    app.include_router(health_router)

    # Routers added in later phases (repos, chat, source) register here.
    return app


app = create_app()
