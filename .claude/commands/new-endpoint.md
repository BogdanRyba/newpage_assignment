---
description: Scaffold a new thin FastAPI endpoint with response model, service call, test, and router registration.
argument-hint: <resource> <verb> (e.g. "repos list")
---

Create a new endpoint following the `fastapi-conventions` skill. Arguments: $ARGUMENTS

Steps:
1. Write the failing test first (`backend/tests/unit/test_<resource>_api.py`) using `httpx.ASGITransport`
   against `app.main.app`. Cover positive + negative (e.g. not-found → mapped error) + one edge case.
2. Add/extend the router in `backend/app/api/<resource>.py`: thin handler, pydantic request/response
   models, `Depends` for session/services, typed `AriadneError` for expected failures. No business
   logic in the handler.
3. Put the actual logic in the relevant service under `app/services/`.
4. Register the router in `app/main.create_app()` if new.
5. Run `/run-checks`.
