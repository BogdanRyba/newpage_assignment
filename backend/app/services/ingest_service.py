"""Ingest use-case: orchestrates the ingestion pipeline over domain + ports.

Pipeline: acquire → walk → chunk → embed(dense+sparse) → index(Qdrant) + persist(Postgres).
Idempotent (uuid5 point IDs), and it reports phase/percent to Redis as it goes so the
Indexing screen can stream progress.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.factory import (
    make_embedder,
    make_graph_store,
    make_parser,
    make_sparse_embedder,
    make_vector_store,
)
from app.core.logging import get_logger
from app.core.progress import publish
from app.db.repositories.files import ChunkRepository, FileRepository
from app.db.repositories.ingest_jobs import IngestJobRepository
from app.db.repositories.repos import RepoRepository
from app.domain.chunking.service import chunk_file
from app.domain.models import Chunk as DomainChunk
from app.domain.models import RepoContext, VectorPoint
from app.ingestion.clone import clone_repo, unzip_repo
from app.ingestion.walk import walk

log = get_logger("ingest")
EMBED_BATCH = 64


class IngestService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repos = RepoRepository(session)
        self.jobs = IngestJobRepository(session)
        self.files = FileRepository(session)
        self.chunks = ChunkRepository(session)
        self.parser = make_parser()
        self.embedder = make_embedder()
        self.sparse = make_sparse_embedder()
        self.vectors = make_vector_store()
        self.graph = make_graph_store()

    async def run(
        self,
        *,
        repo_id: str,
        job_id: str,
        source_url: str | None = None,
        zip_bytes: bytes | None = None,
        local_path: str | None = None,
    ) -> None:
        ctx = RepoContext(repo_id=repo_id)
        cleanup_dir: Path | None = None
        try:
            await self.repos.set_status(repo_id, "indexing")
            await self._progress(repo_id, job_id, phase="cloning", pct=2, status="running")

            root, commit_sha, cleanup_dir = self._acquire(source_url, zip_bytes, local_path)

            # --- parse + chunk ---
            await self._progress(repo_id, job_id, phase="parsing", pct=10)
            pending: list[tuple[DomainChunk, str]] = []  # (chunk, file_id)
            file_count = 0
            for sf in walk(root):
                db_file = await self.files.upsert(
                    repo_id=repo_id,
                    path=sf.path,
                    lang=self.parser.language_of(sf.path),
                    size=sf.size,
                    sha256=sf.sha256,
                    content=sf.text,
                )
                await self.chunks.delete_for_file(db_file.id)  # idempotent re-ingest
                for ch in chunk_file(repo_id, sf.path, sf.text, self.parser):
                    pending.append((ch, db_file.id))
                file_count += 1
                if file_count % 10 == 0:
                    await self._progress(
                        repo_id,
                        job_id,
                        phase="parsing",
                        files_done=file_count,
                        pct=min(40, 10 + file_count),
                    )

            await self._progress(repo_id, job_id, phase="parsing", files_done=file_count, pct=40)

            # --- embed + index ---
            await self._progress(repo_id, job_id, phase="embedding", pct=45)
            chunk_count = await self._embed_and_index(ctx, pending, repo_id, job_id)

            # --- graph (optional, opt-in) ---
            if self.graph.enabled:
                from app.domain.graph.extract import build_graph

                nodes, edges = build_graph([c for c, _ in pending])
                await self.graph.ensure_schema()
                await self.graph.clear_repo(ctx)
                await self.graph.upsert_graph(ctx, nodes, edges)
                log.info("graph_written", repo_id=repo_id, nodes=len(nodes), edges=len(edges))

            # --- finalize ---
            await self._progress(repo_id, job_id, phase="building_index", pct=98)
            await self.repos.finalize(
                repo_id, commit_sha=commit_sha, file_count=file_count, chunk_count=chunk_count
            )
            await self._progress(
                repo_id,
                job_id,
                phase="done",
                pct=100,
                status="done",
                files_done=file_count,
                chunks_done=chunk_count,
            )
            log.info("ingest_done", repo_id=repo_id, files=file_count, chunks=chunk_count)
        except Exception as exc:  # noqa: BLE001 — surface failure explicitly
            log.exception("ingest_failed", repo_id=repo_id, error=str(exc))
            await self.repos.set_status(repo_id, "failed")
            await self.jobs.update(job_id, status="failed", error=str(exc)[:500])
            await publish(repo_id, {"type": "error", "message": str(exc)[:300]})
        finally:
            if cleanup_dir is not None:
                shutil.rmtree(cleanup_dir, ignore_errors=True)

    def _acquire(
        self, source_url: str | None, zip_bytes: bytes | None, local_path: str | None
    ) -> tuple[Path, str | None, Path | None]:
        if local_path:
            return Path(local_path), None, None
        if zip_bytes is not None:
            root, sha, cleanup = unzip_repo(zip_bytes)
            return root, sha, cleanup
        if source_url:
            root, sha, cleanup = clone_repo(source_url)
            return root, sha, cleanup
        raise ValueError("ingest requires one of: source_url, zip_bytes, local_path")

    async def _embed_and_index(
        self, ctx: RepoContext, pending: list[tuple[DomainChunk, str]], repo_id: str, job_id: str
    ) -> int:
        total = len(pending)
        done = 0
        ensured = False
        for start in range(0, total, EMBED_BATCH):
            batch = pending[start : start + EMBED_BATCH]
            texts = [c.text for c, _ in batch]
            dense = await self.embedder.embed_documents(texts)
            sparse = await self.sparse.embed_documents(texts)

            if not ensured:
                await self.vectors.ensure_collection(ctx, dense_dim=len(dense[0]))
                ensured = True

            points = [
                VectorPoint(
                    id=ch.point_id,
                    dense=dense[i],
                    sparse=sparse[i],
                    payload={
                        "path": ch.path,
                        "symbol": ch.symbol,
                        "kind": ch.kind,
                        "lang": ch.lang,
                        "start_line": ch.start_line,
                        "end_line": ch.end_line,
                        "index": ch.index,
                        "text": ch.text,
                    },
                )
                for i, (ch, _) in enumerate(batch)
            ]
            await self.vectors.upsert(ctx, points)

            # persist chunk metadata, grouped by file
            by_file: dict[str, list[dict]] = {}
            for ch, file_id in batch:
                by_file.setdefault(file_id, []).append(
                    {
                        "symbol": ch.symbol,
                        "kind": ch.kind,
                        "start_line": ch.start_line,
                        "end_line": ch.end_line,
                        "qdrant_point_id": ch.point_id,
                    }
                )
            for file_id, rows in by_file.items():
                await self.chunks.add_many(file_id=file_id, repo_id=repo_id, rows=rows)

            done += len(batch)
            pct = 45 + int(50 * done / max(total, 1))
            await self._progress(repo_id, job_id, phase="embedding", chunks_done=done, pct=pct)
        return done

    async def _progress(self, repo_id: str, job_id: str, **fields) -> None:
        await self.jobs.update(job_id, **fields)
        await publish(repo_id, {"type": "progress", **fields})
