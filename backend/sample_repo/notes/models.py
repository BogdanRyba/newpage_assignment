"""Core data model for a note."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Note:
    """A single note: an id, a title, free-text body, and tags."""

    id: int
    title: str
    body: str
    tags: list[str] = field(default_factory=list)

    def text(self) -> str:
        """Full searchable text of the note (title + body + tags)."""
        return " ".join([self.title, self.body, *self.tags])
