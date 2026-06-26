"""Walk filtering contract — deny-list, .gitignore, size cap, binary skip.

If the walker indexes vendored/binary/secret files, the index fills with noise and
retrieval quality drops — so these exclusions must hold.
"""

from __future__ import annotations

from pathlib import Path

from app.ingestion.walk import MAX_BYTES, walk


def _make_repo(root: Path) -> None:
    (root / "keep.py").write_text("def f():\n    return 1\n")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "dep.js").write_text("module.exports = 1;\n")
    (root / "yarn.lock").write_text("# lockfile\n")
    (root / "big.txt").write_text("x" * (MAX_BYTES + 10))
    (root / "image.png").write_bytes(b"\x89PNG\x00\x00binary")
    (root / "bin.dat").write_bytes(b"head\x00\x00tail")
    (root / ".gitignore").write_text("secret.py\n")
    (root / "secret.py").write_text("API_KEY = 'nope'\n")


def test_walk_keeps_only_real_source(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    paths = {sf.path for sf in walk(tmp_path)}
    assert "keep.py" in paths
    assert "node_modules/dep.js" not in paths  # deny dir
    assert "yarn.lock" not in paths  # deny ext
    assert "big.txt" not in paths  # size cap
    assert "image.png" not in paths and "bin.dat" not in paths  # binary
    assert "secret.py" not in paths  # gitignored


def test_walk_populates_hash_and_size(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("print('hi')\n")
    files = list(walk(tmp_path))
    assert len(files) == 1
    sf = files[0]
    assert sf.size == len("print('hi')\n")
    assert len(sf.sha256) == 64  # sha256 hex
    assert sf.text.startswith("print")


def test_empty_repo_yields_nothing(tmp_path: Path) -> None:
    assert list(walk(tmp_path)) == []
