"""In-memory store for notes, with a search backed by the ranker."""

from __future__ import annotations

from .config import MAX_RESULTS
from .models import Note
from .ranking import rank_notes


class NoteStore:
    """Holds notes in memory and answers add / get / all / search."""

    def __init__(self) -> None:
        self._notes: dict[int, Note] = {}

    def add(self, note: Note) -> None:
        self._notes[note.id] = note

    def get(self, note_id: int) -> Note | None:
        return self._notes.get(note_id)

    def all(self) -> list[Note]:
        return list(self._notes.values())

    def search(self, query: str) -> list[Note]:
        """Rank all notes against the query and return the top MAX_RESULTS."""
        return rank_notes(query, self.all())[:MAX_RESULTS]
