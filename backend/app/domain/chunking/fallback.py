"""Language-agnostic recursive splitter.

Used when no tree-sitter grammar matches the file, or to split an oversized symbol.
Splits on line boundaries into ~`size`-char blocks with a small overlap so a span
crossing a boundary stays retrievable from at least one block.
"""

from __future__ import annotations

from pydantic import BaseModel


class Block(BaseModel):
    text: str
    start_line: int  # 1-based, inclusive
    end_line: int


def recursive_split(source: str, *, size: int = 1500, overlap: int = 150) -> list[Block]:
    lines = source.splitlines()
    if not lines:
        return []

    blocks: list[Block] = []
    i = 0
    n = len(lines)
    while i < n:
        start = i
        char_count = 0
        j = i
        while j < n and char_count < size:
            char_count += len(lines[j]) + 1
            j += 1
        text = "\n".join(lines[start:j])
        blocks.append(Block(text=text, start_line=start + 1, end_line=j))
        if j >= n:
            break
        # back up enough lines to cover ~`overlap` chars of context
        back = 0
        carried = 0
        while j - back - 1 > start and carried < overlap:
            back += 1
            carried += len(lines[j - back]) + 1
        i = j - back
    return blocks
