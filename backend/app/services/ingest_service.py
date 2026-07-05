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
from app.db.repositories.versions import RepoVersionRepository, VersionFileRepository
from app.domain.chunking.service import chunk_file
from app.domain.models import Chunk as DomainChunk
from app.domain.models import RepoContext, VectorPoint
from app.ingestion.clone import (
    EMPTY_TREE_SHA,
    clone_repo,
    default_branch,
    diff_name_status,
    file_history,
    read_blob,
    resolve_ref,
    unzip_repo,
)
from app.ingestion.walk import path_denied, source_file_from_bytes, walk

log = get_logger("ingest")
EMBED_BATCH = 64


def _manifest_commit_id(manifest: dict[str, str]) -> str:
    """A stable pseudo-commit id for upload sources from their path→file_id manifest.

    Identical content dedupes to identical file rows → identical manifest → identical id,
    so re-uploading the same project is detected as a no-op; changed content yields a new id.
    """
    import hashlib

    payload = "\n".join(f"{p}:{fid}" for p, fid in sorted(manifest.items()))
    return hashlib.sha256(payload.encode()).hexdigest()  # 64 hex — fits commit_sha(64)


class IngestService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repos = RepoRepository(session)
        self.jobs = IngestJobRepository(session)
        self.files = FileRepository(session)
        self.chunks = ChunkRepository(session)
        self.versions = RepoVersionRepository(session)
        self.vfiles = VersionFileRepository(session)
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
        ref: str | None = None,
        parent_version_id: str | None = None,
    ) -> None:
        """Ingest one version of a repo.

        Creates a RepoVersion and indexes it. When a parent version is given and the source
        is git, only blobs that changed between parent and head are re-embedded (incremental);
        otherwise the full tree is walked (first ingest / zip / local). Unchanged blobs are
        shared — never re-embedded — and the version's path→blob manifest is recorded.
        """
        ctx = RepoContext(repo_id=repo_id)
        cleanup_dir: Path | None = None
        version_id: str | None = None
        try:
            await self.repos.set_status(repo_id, "indexing")
            await self._progress(repo_id, job_id, phase="cloning", pct=2, status="running")

            root, head_sha, cleanup_dir, is_git = self._acquire(
                source_url, zip_bytes, local_path, ref
            )
            ref_name = ref or (default_branch(root) if is_git else "upload")
            ref_type = "branch" if is_git else "commit"
            parent = (
                await self.versions.get(parent_version_id) if parent_version_id else None
            )

            # --- build the version's pending chunks + path→blob manifest ---
            await self._progress(repo_id, job_id, phase="parsing", pct=10)
            if is_git and head_sha is not None:
                # Git sources always go through diff so blob_shas are git OIDs. First ingest
                # diffs against the empty tree (all "A"); incremental against the parent commit.
                base_sha = parent.commit_sha if parent else EMPTY_TREE_SHA
                base_map = await self.vfiles.load_file_map(parent.id) if parent else {}
                pending, manifest = await self._git_index(
                    repo_id, root, base_sha, head_sha, base_map, job_id
                )
                commit_sha = head_sha
            else:
                pending, manifest = await self._full_walk(repo_id, root, job_id)
                # Uploads have no git history: derive a stable, content-derived commit id so
                # re-ingesting identical content is a no-op (and distinct content is a new row).
                commit_sha = _manifest_commit_id(manifest)

            # --- no-op gate: this exact commit is already indexed ---
            existing = await self.versions.get_by_commit(repo_id, commit_sha)
            if existing is not None and existing.status == "ready":
                log.info("ingest_noop", repo_id=repo_id, commit_sha=commit_sha[:12])
                await self.repos.finalize(
                    repo_id,
                    commit_sha=commit_sha,
                    file_count=existing.file_count,
                    chunk_count=existing.chunk_count,
                )
                await self._progress(
                    repo_id, job_id, phase="done", pct=100, status="done",
                    files_done=existing.file_count, chunks_done=existing.chunk_count,
                )
                return

            version = await self.versions.create(
                repo_id=repo_id,
                ref_name=ref_name,
                ref_type=ref_type,
                commit_sha=commit_sha,
                parent_version_id=parent.id if parent else None,
            )
            version_id = version.id

            file_count = len(manifest)
            await self._progress(repo_id, job_id, phase="parsing", files_done=file_count, pct=40)

            # --- embed + index (only the new/changed blobs) ---
            await self._progress(repo_id, job_id, phase="embedding", pct=45)
            chunk_count = await self._embed_and_index(ctx, pending, repo_id, job_id)

            # --- record the version manifest (path -> blob) ---
            await self.vfiles.add_many(version.id, list(manifest.items()))

            # --- graph (optional, opt-in) — full rebuild only on a full ingest for now ---
            if self.graph.enabled and parent is None:
                from app.domain.graph.extract import build_graph

                nodes, edges = build_graph([c for c, _ in pending])
                await self.graph.ensure_schema()
                await self.graph.clear_repo(ctx)
                await self.graph.upsert_graph(ctx, nodes, edges)
                log.info("graph_written", repo_id=repo_id, nodes=len(nodes), edges=len(edges))

            # --- finalize version + repo (back-compat surface) ---
            await self._progress(repo_id, job_id, phase="building_index", pct=98)
            await self.versions.finalize(
                version.id, file_count=file_count, chunk_count=chunk_count
            )
            await self.repos.finalize(
                repo_id, commit_sha=head_sha, file_count=file_count, chunk_count=chunk_count
            )
            await self.repos.mark_needs_reingest(repo_id, False)
            await self._gc_orphans(ctx, repo_id)
            await self._progress(
                repo_id,
                job_id,
                phase="done",
                pct=100,
                status="done",
                files_done=file_count,
                chunks_done=chunk_count,
            )
            log.info(
                "ingest_done",
                repo_id=repo_id,
                version_id=version.id,
                files=file_count,
                chunks=chunk_count,
                incremental=parent is not None,
            )
        except Exception as exc:  # noqa: BLE001 — surface failure explicitly
            log.exception("ingest_failed", repo_id=repo_id, error=str(exc))
            await self.repos.set_status(repo_id, "failed")
            if version_id is not None:
                await self.versions.set_status(version_id, "failed")
            await self.jobs.update(job_id, status="failed", error=str(exc)[:500])
            await publish(repo_id, {"type": "error", "message": str(exc)[:300]})
        finally:
            if cleanup_dir is not None:
                shutil.rmtree(cleanup_dir, ignore_errors=True)

    async def _full_walk(
        self, repo_id: str, root: Path, job_id: str
    ) -> tuple[list[tuple[DomainChunk, str]], dict[str, str]]:
        """Walk the whole tree (first ingest / zip / local). Returns (pending, manifest).

        Content-addressed by sha256, so two identical files dedupe to one blob row and
        re-ingesting identical content reuses existing chunks (created=False → skip).
        """
        pending: list[tuple[DomainChunk, str]] = []
        manifest: dict[str, str] = {}  # path -> file_id
        n = 0
        for sf in walk(root):
            file, created = await self.files.get_or_create_blob(
                repo_id=repo_id,
                blob_sha=sf.sha256,
                path=sf.path,
                lang=self.parser.language_of(sf.path),
                size=sf.size,
                sha256=sf.sha256,
                content=sf.text,
                raw=sf.raw,
            )
            manifest[sf.path] = file.id
            if created:
                for ch in chunk_file(repo_id, sf.path, sf.text, self.parser, blob_sha=sf.sha256):
                    pending.append((ch, file.id))
            n += 1
            if n % 10 == 0:
                await self._progress(
                    repo_id, job_id, phase="parsing", files_done=n, pct=min(40, 10 + n)
                )
        return pending, manifest

    async def _git_index(
        self,
        repo_id: str,
        root: Path,
        base_sha: str,
        head_sha: str,
        base_map: dict[str, str],
        job_id: str,
    ) -> tuple[list[tuple[DomainChunk, str]], dict[str, str]]:
        """Index the blobs the diff base_sha..head_sha reports as changed.

        Unchanged paths carry their parent file_id forward via base_map (never re-embedded).
        The git blob OID is the content address, so a blob already indexed (shared with
        another branch, or a pure rename) is reused. First ingest passes base_sha=EMPTY_TREE
        and base_map={}, so every path is an addition through this same path.
        """
        manifest: dict[str, str] = dict(base_map)
        pending: list[tuple[DomainChunk, str]] = []

        for e in diff_name_status(root, base_sha, head_sha):
            if e.status == "R" and e.old_path:
                manifest.pop(e.old_path, None)
            if e.status == "D":
                manifest.pop(e.path, None)
                continue
            rel = e.path
            if path_denied(rel) or e.dst_blob is None:
                manifest.pop(rel, None)
                continue
            sf = source_file_from_bytes(rel, read_blob(root, e.dst_blob))
            if sf is None:
                manifest.pop(rel, None)
                continue
            file, created = await self.files.get_or_create_blob(
                repo_id=repo_id,
                blob_sha=e.dst_blob,
                path=rel,
                lang=self.parser.language_of(rel),
                size=sf.size,
                sha256=sf.sha256,
                content=sf.text,
                raw=sf.raw,
            )
            manifest[rel] = file.id
            if created:
                for ch in chunk_file(repo_id, rel, sf.text, self.parser, blob_sha=e.dst_blob):
                    pending.append((ch, file.id))
                await self._capture_authorship(root, rel, file.id)
        return pending, manifest

    async def _capture_authorship(self, root: Path, rel: str, file_id: str) -> None:
        """Store who last changed ``rel`` + recent history (git sources only)."""
        history = file_history(root, rel, limit=5)
        if not history:
            return
        head = history[0]
        await self.files.set_authorship(
            file_id,
            last_author=head.author,
            last_author_email=head.email,
            last_commit_sha=head.sha,
            last_commit_at=head.committed_at,
            commit_history=[c.model_dump() for c in history],
        )

    async def _gc_orphans(self, ctx: RepoContext, repo_id: str) -> None:
        """Reclaim blobs no version references: drop Qdrant points → chunks (cascade) → row.

        Idempotent — a re-run re-finds anything left half-done. Ordering deletes Qdrant
        first so a crash leaves a recoverable orphan rather than a dangling point.
        """
        orphans = await self.files.orphan_blobs(repo_id)
        for file_id, blob_sha in orphans:
            if blob_sha:
                await self.vectors.delete_by_blob(ctx, blob_sha)
            await self.files.delete(file_id)
        if orphans:
            log.info("gc_orphans", repo_id=repo_id, removed=len(orphans))

    def _acquire(
        self,
        source_url: str | None,
        zip_bytes: bytes | None,
        local_path: str | None,
        ref: str | None,
    ) -> tuple[Path, str | None, Path | None, bool]:
        """Returns (root, head_sha, cleanup_dir, is_git)."""
        if local_path:
            root = Path(local_path)
            # A local path may itself be a git checkout (used by tests/dev).
            is_git = (root / ".git").exists()
            head_sha = resolve_ref(root, ref or "HEAD") if is_git else None
            return root, head_sha, None, is_git
        if zip_bytes is not None:
            root, sha, cleanup = unzip_repo(zip_bytes)
            return root, sha, cleanup, False
        if source_url:
            root, sha, cleanup = clone_repo(source_url, ref)
            return root, sha, cleanup, True
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
                        "blob_sha": ch.blob_sha,
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
        # Always stream the latest counts. A partial update (the embedding phase sends only
        # chunks_done) must not drop files_done from the payload, or the Indexing screen resets
        # to "0 files" mid-ingest (frontend reads `job.files_done ?? 0`).
        job = await self.jobs.get(job_id)
        event = {"type": "progress", **fields}
        if job is not None:
            event.setdefault("files_done", job.files_done)
            event.setdefault("chunks_done", job.chunks_done)
        await publish(repo_id, event)
