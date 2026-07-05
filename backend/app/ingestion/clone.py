"""Acquire a repo's working tree: git clone a URL, or unzip an upload.

Cloning is *blobless* (``--filter=blob:none``): the full commit graph and all refs come
down cheaply, while file contents (blobs) are fetched on demand. That gives us the
history needed for diff/blame between branches/tags without paying for every blob, and
lets incremental ingest re-index only the blobs that actually changed between commits.
The caller is responsible for cleaning up the temp directory.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import zipfile
from hashlib import sha1
from pathlib import Path

from pydantic import BaseModel

from app.core.errors import IngestError
from app.domain.models import CommitRef

# git's well-known empty tree object. Diffing a first ingest against it makes the whole
# tree an all-"A" (added) delta, so first ingest and incremental share one code path.
EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

# Field separator for `git log --format`. Unit Separator (0x1f) never appears in names/subjects.
_LOG_FMT = "%H%x1f%an%x1f%ae%x1f%aI%x1f%s"


class DiffEntry(BaseModel, frozen=True):
    """One path that changed between two commits, with its source/destination blob OIDs."""

    status: str  # A | M | D | R (rename) | C (copy)
    path: str  # destination path (new path for renames/copies)
    old_path: str | None = None  # source path, only for renames/copies
    src_blob: str | None = None  # blob OID before (None for additions)
    dst_blob: str | None = None  # blob OID after (None for deletions)


def parse_diff_raw(output: str) -> list[DiffEntry]:
    """Parse ``git diff --raw -M --no-abbrev`` into DiffEntry rows.

    Each non-blank line looks like::

        :<src_mode> <dst_mode> <src_sha> <dst_sha> <status>\t<path>[\t<path2>]

    For renames/copies the status carries a similarity score (``R100``, ``C75``) and two
    tab-separated paths (old, new). Pure: no git invocation, fully unit-testable.
    """
    entries: list[DiffEntry] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        meta, _, rest = line.partition("\t")
        fields = meta.lstrip(":").split()
        if len(fields) < 5:
            continue
        _src_mode, _dst_mode, src_sha, dst_sha, raw_status = fields[:5]
        status = raw_status[0]  # strip rename/copy similarity score
        paths = rest.split("\t")
        if status in ("R", "C") and len(paths) == 2:
            old_path, path = paths[0], paths[1]
        else:
            old_path, path = None, paths[0]
        entries.append(
            DiffEntry(
                status=status,
                path=path,
                old_path=old_path,
                src_blob=None if _is_null_oid(src_sha) else src_sha,
                dst_blob=None if _is_null_oid(dst_sha) else dst_sha,
            )
        )
    return entries


def _is_null_oid(oid: str) -> bool:
    return set(oid) == {"0"}


def clone_repo(source_url: str, ref: str | None = None) -> tuple[Path, str, Path]:
    """Blobless-clone a repo and check out ``ref`` (default branch if None).

    Returns (root, full_commit_sha, cleanup_dir). Unlike the old shallow clone this keeps
    the full history + all branches/tags so diff/blame work, and returns the FULL 40-char
    SHA (versioning needs it; a 12-char prefix is not enough to address a commit safely).
    """
    url = _normalize_url(source_url)
    dest = Path(tempfile.mkdtemp(prefix="ariadne_clone_"))
    try:
        subprocess.run(
            ["git", "clone", "--filter=blob:none", "--no-checkout", url, str(dest)],
            check=True,
            capture_output=True,
            timeout=300,
        )
        target = ref or default_branch(dest)
        sha = resolve_ref(dest, target)
        subprocess.run(
            ["git", "-C", str(dest), "checkout", sha],
            check=True,
            capture_output=True,
            timeout=300,
        )
    except subprocess.CalledProcessError as exc:
        raise IngestError(
            f"git clone failed: {exc.stderr.decode('utf-8', 'ignore')[:300]}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise IngestError("git clone timed out") from exc
    return dest, sha, dest


def unzip_repo(zip_bytes: bytes) -> tuple[Path, str | None, Path]:
    """Returns (root, commit_sha, cleanup_dir). Uploads have no git history."""
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


def git_blob_oid(data: bytes) -> str:
    """git's blob object id for raw bytes: sha1("blob <len>\\0" + data).

    Used to content-address files from zip uploads (which carry no git history) the same
    way git does, so a zip and a later URL ingest of the same project share blobs.
    """
    header = f"blob {len(data)}\0".encode()
    return sha1(header + data).hexdigest()  # noqa: S324 — git's object id, not a security hash


def repo_name_from_url(source_url: str) -> str:
    tail = source_url.rstrip("/").split("/")[-1]
    return re.sub(r"\.git$", "", tail) or "repo"


def default_branch(root: Path) -> str:
    """The remote's default branch (e.g. 'main'), falling back to HEAD."""
    try:
        out = _git(root, "rev-parse", "--abbrev-ref", "origin/HEAD", timeout=10)
        return out.rsplit("/", 1)[-1] or "HEAD"
    except IngestError:
        return "HEAD"


def resolve_ref(root: Path, ref: str) -> str:
    """Resolve a branch/tag/sha to its FULL 40-char commit OID (locally cloned repo)."""
    # Prefer the remote-tracking ref for a bare branch name, then fall back to the ref itself.
    for candidate in (f"origin/{ref}", ref):
        try:
            return _git(root, "rev-parse", "--verify", f"{candidate}^{{commit}}", timeout=10)
        except IngestError:
            continue
    raise IngestError(f"could not resolve ref: {ref}")


def resolve_ref_remote(source_url: str, ref: str) -> str | None:
    """Resolve a ref to its commit SHA WITHOUT cloning (``git ls-remote``).

    Lets the API decide NEW/NO_OP/INCREMENTAL cheaply before enqueuing a full clone.
    Returns None if the ref can't be found remotely.
    """
    url = _normalize_url(source_url)
    try:
        out = subprocess.run(
            ["git", "ls-remote", url, ref],
            check=True,
            capture_output=True,
            timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    first = out.stdout.decode("utf-8", "ignore").split("\n", 1)[0].strip()
    return first.split("\t", 1)[0] if first else None


def diff_name_status(root: Path, base_sha: str, head_sha: str) -> list[DiffEntry]:
    """Changed paths between two commits, with full blob OIDs (``git diff --raw``).

    Pass ``EMPTY_TREE_SHA`` as base for a first ingest (everything becomes "A").
    """
    out = _git(
        root, "diff", "--raw", "-M", "--no-abbrev", base_sha, head_sha, timeout=120
    )
    return parse_diff_raw(out)


def parse_git_log(output: str) -> list[CommitRef]:
    """Parse ``git log --format=_LOG_FMT`` output into CommitRefs (pure, unit-testable)."""
    commits: list[CommitRef] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\x1f")
        if len(parts) < 5:
            continue
        sha, author, email, committed_at, subject = parts[:5]
        commits.append(
            CommitRef(
                sha=sha, author=author, email=email, committed_at=committed_at, subject=subject
            )
        )
    return commits


def file_history(root: Path, path: str, limit: int = 5) -> list[CommitRef]:
    """Recent commits that touched ``path`` (newest first). Empty if untracked/unknown."""
    try:
        out = _git(
            root, "log", f"-n{limit}", f"--format={_LOG_FMT}", "--", path, timeout=30
        )
    except IngestError:
        return []
    return parse_git_log(out)


def read_blob(root: Path, blob_oid: str) -> bytes:
    """Read a blob's raw bytes by OID (fetched on demand under the blobless filter)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "cat-file", "blob", blob_oid],
            check=True,
            capture_output=True,
            timeout=60,
        )
    except subprocess.CalledProcessError as exc:
        raise IngestError(
            f"git cat-file failed for {blob_oid[:12]}: "
            f"{exc.stderr.decode('utf-8', 'ignore')[:200]}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise IngestError(f"git cat-file timed out for {blob_oid[:12]}") from exc
    return out.stdout


def ls_tree(root: Path, sha: str) -> dict[str, str]:
    """Full path → blob OID manifest for a commit (fallback when no diff applies)."""
    out = _git(root, "ls-tree", "-r", "--full-tree", sha, timeout=120)
    manifest: dict[str, str] = {}
    for line in out.splitlines():
        if not line.strip():
            continue
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) >= 3 and parts[1] == "blob":
            manifest[path] = parts[2]
    return manifest


def _normalize_url(source_url: str) -> str:
    u = source_url.strip()
    if u.startswith(("http://", "https://", "git@", "ssh://")):
        return u
    return f"https://{u}"  # accept "github.com/org/repo"


def _git(root: Path, *args: str, timeout: int) -> str:
    """Run a read-only git command in ``root`` and return stripped stdout."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.CalledProcessError as exc:
        raise IngestError(
            f"git {args[0]} failed: {exc.stderr.decode('utf-8', 'ignore')[:200]}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise IngestError(f"git {args[0]} timed out") from exc
    return out.stdout.decode("utf-8", "ignore").strip()
