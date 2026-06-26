"""Acquire a repo's working tree: git clone a URL, or unzip an upload.

Returns the local root path + a best-effort commit SHA. Shallow clone keeps it fast;
the caller is responsible for cleaning up the temp directory.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

from app.core.errors import IngestError


def clone_repo(source_url: str) -> tuple[Path, str | None, Path]:
    """Returns (root, commit_sha, cleanup_dir)."""
    url = _normalize_url(source_url)
    dest = Path(tempfile.mkdtemp(prefix="ariadne_clone_"))
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", url, str(dest)],
            check=True,
            capture_output=True,
            timeout=180,
        )
    except subprocess.CalledProcessError as exc:
        raise IngestError(
            f"git clone failed: {exc.stderr.decode('utf-8', 'ignore')[:300]}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise IngestError("git clone timed out") from exc
    return dest, _head_sha(dest), dest


def unzip_repo(zip_bytes: bytes) -> tuple[Path, str | None, Path]:
    """Returns (root, commit_sha, cleanup_dir)."""
    dest = Path(tempfile.mkdtemp(prefix="ariadne_zip_"))
    try:
        import io

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            zf.extractall(dest)
    except zipfile.BadZipFile as exc:
        raise IngestError("uploaded file is not a valid .zip") from exc
    # If the zip contains a single top-level dir, descend into it (but clean up `dest`).
    entries = [p for p in dest.iterdir() if p.name != "__MACOSX"]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0], None, dest
    return dest, None, dest


def repo_name_from_url(source_url: str) -> str:
    tail = source_url.rstrip("/").split("/")[-1]
    return re.sub(r"\.git$", "", tail) or "repo"


def _normalize_url(source_url: str) -> str:
    u = source_url.strip()
    if u.startswith(("http://", "https://", "git@", "ssh://")):
        return u
    return f"https://{u}"  # accept "github.com/org/repo"


def _head_sha(root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            timeout=10,
        )
        return out.stdout.decode().strip()[:12]
    except Exception:
        return None
