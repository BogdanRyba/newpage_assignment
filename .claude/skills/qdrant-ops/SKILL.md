---
name: qdrant-ops
description: Qdrant topology and operations — collection-per-repo, named dense+sparse vectors, uuid5 point IDs, idempotent upserts, recreate-on-embedding-change. Use when touching the vector adapter or indexing.
---

# Qdrant ops

- **Collection per repo**: `repo_{repo_id}` (from `RepoContext.qdrant_collection`). Hard data isolation.
- **Named vectors** in one collection: `dense` (Gemini embedding) + `sparse` (fastembed). Hybrid search
  queries both, then we fuse with RRF in the domain layer.
- **Point IDs** are `uuid5(repo_id:path:index)` (`domain.models.point_id`). Re-ingesting the same repo
  upserts the same points → **idempotent**, never duplicates.
- **Dimension**: don't hardcode. Probe the embedder once (length of the first dense vector) and create
  the collection with that size. Changing the embedding model means a **different dim** → recreate the
  collection and re-embed; the adapter detects a size mismatch and recreates.
- **Upsert in batches**; the worker reports progress (chunks done) to Redis as it goes.
- Filtering by `lang`/`path` uses Qdrant payload filters; keep payload small (metadata, not full text —
  full text lives in Postgres `files.content`).

All Qdrant access stays behind the `vector_store` port. The domain never imports `qdrant_client`.
