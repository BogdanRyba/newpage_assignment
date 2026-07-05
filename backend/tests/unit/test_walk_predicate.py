"""The deny predicate + bytes→SourceFile builder, extracted so the git-incremental
ingest path applies the SAME rules as the filesystem walk (binary, oversize, deny-list).
"""

from __future__ import annotations

from app.ingestion.walk import MAX_BYTES, path_denied, source_file_from_bytes


def test_path_denied_blocks_vendored_dirs_and_binary_extensions() -> None:
    assert path_denied("node_modules/react/index.js") is True
    assert path_denied(".git/config") is True
    assert path_denied("assets/logo.png") is True
    assert path_denied("poetry.lock") is True


def test_path_denied_allows_source_files() -> None:
    assert path_denied("app/main.py") is False
    assert path_denied("src/components/Button.tsx") is False


def test_source_file_from_bytes_builds_text_file_with_hash() -> None:
    sf = source_file_from_bytes("a.py", b"print('hi')\n")
    assert sf is not None
    assert sf.path == "a.py"
    assert sf.text == "print('hi')\n"
    assert len(sf.sha256) == 64
    assert sf.size == len(b"print('hi')\n")


def test_source_file_from_bytes_skips_binary_and_oversize() -> None:
    assert source_file_from_bytes("x.dat", b"\x00\x01\x02binary") is None  # null byte → binary
    assert source_file_from_bytes("big.py", b"x" * (MAX_BYTES + 1)) is None  # over size cap
