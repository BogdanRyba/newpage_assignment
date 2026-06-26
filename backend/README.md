# Ariadne — backend

FastAPI + LangChain/LangGraph service for the Ariadne code documentation assistant.
See the repository root `README.md` for the full picture and `docs/` for design notes.

Run everything via Docker Compose from the repo root:

```bash
docker compose up --build
```

Run checks inside the container:

```bash
docker compose run --rm api ruff check . && \
docker compose run --rm api mypy app && \
docker compose run --rm -e CASSETTE_MODE=replay api pytest
```
