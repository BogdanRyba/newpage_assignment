"""Code-review agent: review the diff between two indexed versions.

Parallel fan-out — security / style / performance reviewers run concurrently over the changed
files, each returning JSON findings; results are merged + deduped + severity-sorted (pure code,
no LLM at the merge step). Built on VersioningService.compare, so it works on any two indexed
versions with no git at review time. The reviewed code is untrusted DATA (see the prompts).
"""

from __future__ import annotations

import asyncio
import json
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.repositories.versions import RepoVersionRepository, VersionFileRepository
from app.domain.review import Finding, ReviewResult, merge_findings
from app.ports.generator import Generator
from app.prompts import code_review
from app.services.versioning_service import VersioningService

log = get_logger("code_review")
_JSON = re.compile(r"\{.*\}", re.S)
_DIMENSIONS = ("security", "style", "performance")
_MAX_FILE_CHARS = 4000  # cap per file so the review prompt stays bounded
_MAX_FILES = 25


def _parse_findings(raw: str, dimension: str) -> list[Finding]:
    m = _JSON.search(raw or "")
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError):
        return []
    out: list[Finding] = []
    for f in data.get("findings", []) if isinstance(data, dict) else []:
        if not isinstance(f, dict) or "title" not in f:
            continue
        out.append(
            Finding(
                dimension=dimension,
                severity=str(f.get("severity", "info")),
                title=str(f["title"]),
                path=str(f.get("path", "")),
                detail=str(f.get("detail", "")),
            )
        )
    return out


class CodeReviewService:
    def __init__(self, session: AsyncSession, generator: Generator) -> None:
        self.session = session
        self.versioning = VersioningService(session)
        self.versions = RepoVersionRepository(session)
        self.vfiles = VersionFileRepository(session)
        self.generator = generator

    async def review(self, repo_id: str, base_ref: str, head_ref: str) -> ReviewResult:
        diff = await self.versioning.compare(repo_id, base_ref, head_ref)
        changed = [c.path for c in (diff.added + diff.modified)]
        if not changed:
            return ReviewResult(base_ref=base_ref, head_ref=head_ref, files_reviewed=0)

        head = await self._resolve_version(repo_id, head_ref)
        capped = changed[:_MAX_FILES]
        contents = await self.vfiles.contents_for(head.id, capped)
        files_block = "\n\n".join(
            f"### {path}\n{(contents.get(path) or '')[:_MAX_FILE_CHARS]}" for path in capped
        )
        summary = (
            f"{len(diff.added)} added, {len(diff.removed)} removed, {len(diff.modified)} modified"
        )

        groups = await asyncio.gather(
            *[self._review_dimension(d, summary, files_block) for d in _DIMENSIONS]
        )
        findings = merge_findings(list(groups))
        return ReviewResult(
            base_ref=base_ref,
            head_ref=head_ref,
            files_reviewed=len(changed),
            findings=findings,
        )

    async def _review_dimension(
        self, dimension: str, summary: str, files_block: str
    ) -> list[Finding]:
        raw = await self.generator.complete(
            code_review.system(dimension), code_review.build_user(summary, files_block)
        )
        return _parse_findings(raw, dimension)

    async def _resolve_version(self, repo_id: str, ref: str):  # noqa: ANN202 - RepoVersion
        by_commit = await self.versions.get_by_commit(repo_id, ref)
        if by_commit is not None:
            return by_commit
        by_ref = await self.versions.latest_for_ref(repo_id, ref)
        if by_ref is None:
            raise ValueError(f"no indexed version for ref '{ref}'")
        return by_ref
