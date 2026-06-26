"""Walk a checked-out repo, yielding indexable source files.

Two filter layers: a built-in deny-list (vendored dirs, binaries, lockfiles, size cap)
that applies regardless of .gitignore, plus the repo's own .gitignore. Files are read
once and hashed so a later run can re-index only what changed.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

from pathspec import PathSpec
from pydantic import BaseModel

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
    ".pdf",
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


class SourceFile(BaseModel):
    path: str  # repo-relative, posix
    text: str
    sha256: str
    size: int


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
        if _denied(rel, path) or gitignore.match_file(rel):
            continue
        data = path.read_bytes()
        if len(data) > MAX_BYTES or _looks_binary(data):
            continue
        yield SourceFile(
            path=rel,
            text=data.decode("utf-8", "ignore"),
            sha256=hashlib.sha256(data).hexdigest(),
            size=len(data),
        )


def _denied(rel: str, path: Path) -> bool:
    if set(Path(rel).parts) & DENY_DIRS:
        return True
    return path.suffix.lower() in DENY_EXT


def _looks_binary(data: bytes) -> bool:
    return b"\x00" in data[:1024]
