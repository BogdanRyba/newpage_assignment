FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# git: clone repos at ingest time. build-essential: native wheels (tree-sitter).
RUN apt-get update \
 && apt-get install -y --no-install-recommends git build-essential \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

# Install deps first (cached) — needs the package source for metadata.
COPY pyproject.toml README.md ./
COPY app ./app
RUN uv pip install --system ".[dev]"

# Rest of the tree (tests, alembic, evals, sample data).
COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
