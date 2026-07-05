"""Code-review domain models — findings from the review personas, merged into one result.

Pure data: produced by parallel reviewer dimensions (security/style/perf) over a version diff,
then merged + deduped. Severity ordering lets the synthesizer sort and summarize.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


class Finding(BaseModel, frozen=True):
    dimension: str  # "security" | "style" | "performance"
    severity: str  # high | medium | low | info
    title: str
    path: str = ""
    detail: str = ""

    @property
    def rank(self) -> int:
        return _SEVERITY_ORDER.get(self.severity.lower(), 4)


class ReviewResult(BaseModel):
    base_ref: str
    head_ref: str
    files_reviewed: int
    findings: list[Finding] = Field(default_factory=list)

    @property
    def summary(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in self.findings:
            out[f.severity] = out.get(f.severity, 0) + 1
        return out


def merge_findings(groups: list[list[Finding]]) -> list[Finding]:
    """Flatten reviewer outputs, dedup on (path, title), sort by severity then dimension."""
    seen: set[tuple[str, str]] = set()
    merged: list[Finding] = []
    for group in groups:
        for f in group:
            key = (f.path, f.title.strip().lower())
            if key in seen:
                continue
            seen.add(key)
            merged.append(f)
    return sorted(merged, key=lambda f: (f.rank, f.dimension, f.path))
