---
name: fastapi-conventions
description: API-layer conventions — thin endpoints, Depends DI, pydantic response models, single error handler, SSE streaming. Use when adding or changing an HTTP route.
---

# FastAPI conventions

- **Thin endpoints.** A route validates input, calls a service, shapes the response. No business logic,
  no raw SQL, no LLM calls in the route body.
- **DI via `Depends`**: `get_session` for DB, factory-built ports/services for everything else.
- **Pydantic response models** on every route (`response_model=`). Inputs are pydantic too.
- **One error layer.** Raise typed `AriadneError` subclasses (`RepoNotFound`, `RepoNotReady`, ...);
  the handler in `core/errors.py` maps them to clean JSON. No bare `HTTPException` scattered around,
  no unhandled 500s for expected cases.
- **SSE** for streaming (chat tokens, ingest progress): use `sse-starlette`'s `EventSourceResponse`,
  yield typed events (`token`, `citations`, `no_sources`, `done` / ingest `phase`, `progress`).
- **Async all the way**: async routes, async session, async ports. Don't block the event loop with
  sync IO — offload CPU-heavy work (parsing, embedding) to the Taskiq worker.

Routers live in `app/api/`, one module per resource (`health`, `repos`, `chat`, `source`), included
from `main.create_app()`.
