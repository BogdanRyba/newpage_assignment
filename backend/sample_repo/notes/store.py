"""In-memory store for notes, with a search backed by a ranking strategy."""

from __future__ import annotations

from .config import MAX_RESULTS
from .models import Note
from .ranking import OverlapRanker, Ranker


class NoteStore:
    """Holds notes in memory and answers add / get / all / search.

    `search` delegates to an injected `Ranker` strategy (overlap ranking by default), so the
    store depends on the ranking *abstraction*, not a specific scoring rule.
    """

    def __init__(self, ranker: Ranker | None = None) -> None:
        self._notes: dict[int, Note] = {}
        self._ranker: Ranker = ranker or OverlapRanker()

    def add(self, note: Note) -> None:
        self._notes[note.id] = note

    def get(self, note_id: int) -> Note | None:
        return self._notes.get(note_id)

    def all(self) -> list[Note]:
        return list(self._notes.values())

    def search(self, query: str) -> list[Note]:
        """Rank all notes with the configured strategy and return the top MAX_RESULTS."""
        return self._ranker.rank(query, self.all())[:MAX_RESULTS]
