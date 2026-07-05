"""parse_diff_raw: turn `git diff --raw -M --no-abbrev` output into DiffEntry rows.

This is the pure parser at the heart of incremental ingest — given the delta between
two commits it tells us exactly which blobs to (re-)index. Parsing is isolated from git
so it is deterministic and unit-testable. The empty-tree base (first ingest) yields all
files as additions through the same machinery.
"""

from __future__ import annotations

from app.ingestion.clone import EMPTY_TREE_SHA, parse_diff_raw, parse_git_log

_A = "0" * 40
_B1 = "a" * 40
_B2 = "b" * 40
_B3 = "c" * 40


def test_parses_added_modified_deleted() -> None:
    out = "\n".join(
        [
            f":000000 100644 {_A} {_B1} A\tnew.py",
            f":100644 100644 {_B1} {_B2} M\tchanged.py",
            f":100644 000000 {_B3} {_A} D\tgone.py",
        ]
    )
    entries = {e.path: e for e in parse_diff_raw(out)}

    assert entries["new.py"].status == "A"
    assert entries["new.py"].dst_blob == _B1
    assert entries["new.py"].src_blob is None  # added → no source blob

    assert entries["changed.py"].status == "M"
    assert entries["changed.py"].src_blob == _B1
    assert entries["changed.py"].dst_blob == _B2

    assert entries["gone.py"].status == "D"
    assert entries["gone.py"].src_blob == _B3
    assert entries["gone.py"].dst_blob is None


def test_parses_rename_with_old_and_new_path() -> None:
    out = f":100644 100644 {_B1} {_B1} R100\told/name.py\tnew/name.py"
    [e] = parse_diff_raw(out)
    assert e.status == "R"
    assert e.old_path == "old/name.py"
    assert e.path == "new/name.py"
    # Pure rename: content unchanged → src and dst blob match (zero re-embedding).
    assert e.src_blob == e.dst_blob == _B1


def test_ignores_blank_lines_and_empty_output() -> None:
    assert parse_diff_raw("") == []
    assert parse_diff_raw("\n  \n") == []


def test_empty_tree_sha_is_the_canonical_constant() -> None:
    # git's well-known empty tree object — diffing against it makes first ingest
    # an all-"A" delta, reusing the same code path as incremental.
    assert EMPTY_TREE_SHA == "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def test_parse_git_log_extracts_commit_fields() -> None:
    out = "\x1f".join(
        ["a" * 40, "Ada Lovelace", "ada@x.io", "2024-01-02T03:04:05+00:00", "fix bug"]
    )
    out += "\n" + "\x1f".join([_B1, "Alan T", "alan@x.io", "2023-12-01T00:00:00+00:00", "init"])
    commits = parse_git_log(out)
    assert [c.author for c in commits] == ["Ada Lovelace", "Alan T"]
    assert commits[0].sha == "a" * 40
    assert commits[0].subject == "fix bug"
    assert commits[0].committed_at == "2024-01-02T03:04:05+00:00"


def test_parse_git_log_tolerates_blank_and_malformed_lines() -> None:
    assert parse_git_log("") == []
    assert parse_git_log("\n  \n") == []
    assert parse_git_log("not-enough-fields") == []  # no separators → skipped
