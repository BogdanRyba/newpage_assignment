"""Walk a checked-out repo, yielding indexable source files.

Two filter layers: a built-in deny-list (vendored dirs, binaries, lockfiles, size cap)
that applies regardless of .gitignore, plus the repo's own .gitignore. Files are read
once and hashed so a later run can re-index only what changed.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Iterator
from pathlib import Path

import structlog
from pathspec import PathSpec
from pydantic import BaseModel

log = structlog.get_logger(__name__)

DENY_DIRS = {
    ".git",
    "node_modules",
    "dist",
    "build",
    ".venv",
    "venv",
    "__pycache__",
    ".next",
    "out",
}
DENY_EXT = {
    ".lock",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".zip",
    ".gz",
    ".tar",
    ".bin",
    ".so",
    ".dylib",
    ".dll",
    ".woff",
    ".woff2",
    ".ttf",
    ".mp4",
    ".mp3",
    ".lockb",
}
MAX_BYTES = 512_000
# Raw PDF bytes are persisted so the UI can render the real document; cap to keep the
# files table lean. Larger PDFs still get text-extracted (askable + citable), just no
# visual view (raw=None) — the panel falls back to the extracted-text view.
MAX_PDF_RAW_BYTES = 8_000_000


class SourceFile(BaseModel):
    path: str  # repo-relative, posix
    text: str
    sha256: str
    size: int
    raw: bytes | None = None  # original bytes, only for PDFs we can render visually


def load_gitignore(root: Path) -> PathSpec:
    patterns: list[str] = []
    gi = root / ".gitignore"
    if gi.exists():
        patterns = gi.read_text(encoding="utf-8", errors="ignore").splitlines()
    return PathSpec.from_lines("gitignore", patterns)


def walk(root: Path) -> Iterator[SourceFile]:
    gitignore = load_gitignore(root)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if path_denied(rel) or gitignore.match_file(rel):
            continue
        sf = source_file_from_bytes(rel, path.read_bytes())
        if sf is not None:
            yield sf


def source_file_from_bytes(rel: str, data: bytes) -> SourceFile | None:
    """Build a SourceFile from a path + raw bytes, or None if it should be skipped.

    Shared by the filesystem walk and the git-incremental path (which feeds blob bytes
    here), so deny rules — binary, oversize, image-only PDF — are decided in one place.
    Caller is responsible for the path-level deny-list / .gitignore check first.
    """
    if rel.lower().endswith(".pdf"):
        return _read_pdf(rel, data)
    if len(data) > MAX_BYTES or _looks_binary(data):
        return None
    return SourceFile(
        path=rel,
        text=data.decode("utf-8", "ignore"),
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
    )


def path_denied(rel: str) -> bool:
    """Path-only deny check (no filesystem access): vendored dirs + binary extensions."""
    parts = Path(rel).parts
    if set(parts) & DENY_DIRS:
        return True
    return Path(rel).suffix.lower() in DENY_EXT


def _read_pdf(rel: str, data: bytes) -> SourceFile | None:
    """Extract a PDF's text so it can be chunked/cited, and keep the raw bytes for the viewer.

    Returns None for PDFs we can't extract text from (encrypted, corrupt, or scanned/image-only):
    indexing image bytes as if they were prose would only pollute retrieval.
    """
    text = _extract_pdf_text(data)
    if not text.strip():
        log.info("pdf.skip_no_text", path=rel, size=len(data))
        return None
    return SourceFile(
        path=rel,
        text=text,
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
        raw=data if len(data) <= MAX_PDF_RAW_BYTES else None,
    )


def _extract_pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)
    except (PyPdfError, ValueError, OSError) as exc:  # malformed / encrypted / truncated
        log.warning("pdf.extract_failed", error=str(exc))
        return ""


def _looks_binary(data: bytes) -> bool:
    return b"\x00" in data[:1024]
