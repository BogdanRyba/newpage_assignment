"""Recursive splitter contract — block coverage, line ranges, overlap, empties."""

from __future__ import annotations

from app.domain.chunking.fallback import recursive_split


def test_empty_source_yields_no_blocks() -> None:
    assert recursive_split("") == []
    # splitlines() drops a pure-newline string to empty lines → still no real content
    assert recursive_split("\n\n\n") == [] or all(
        b.text.strip() == "" for b in recursive_split("\n\n\n")
    )


def test_single_small_file_is_one_block_covering_all_lines() -> None:
    src = "line1\nline2\nline3"
    blocks = recursive_split(src, size=1000, overlap=50)
    assert len(blocks) == 1
    assert blocks[0].start_line == 1
    assert blocks[0].end_line == 3
    assert "line1" in blocks[0].text and "line3" in blocks[0].text


def test_large_file_splits_into_multiple_overlapping_blocks() -> None:
    src = "\n".join(f"row_{i:03d}_padding_text" for i in range(60))
    blocks = recursive_split(src, size=200, overlap=60)
    assert len(blocks) > 1
    # contiguous coverage: every line 1..60 is in at least one block
    covered = set()
    for b in blocks:
        assert b.start_line >= 1 and b.end_line <= 60
        covered.update(range(b.start_line, b.end_line + 1))
    assert covered == set(range(1, 61))
    # overlap: consecutive blocks share at least one line
    for a, b in zip(blocks, blocks[1:], strict=False):
        assert b.start_line <= a.end_line
