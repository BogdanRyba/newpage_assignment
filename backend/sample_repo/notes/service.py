"""Application service wiring the store and ranking together."""

from __future__ import annotations

from .models import Note
from .store import NoteStore


class NoteService:
    """High-level API used by the web layer: create notes and search them."""

    def __init__(self) -> None:
        self._store = NoteStore()
        self._next_id = 1

    def create(self, title: str, body: str, tags: list[str] | None = None) -> Note:
        note = Note(id=self._next_id, title=title, body=body, tags=tags or [])
        self._store.add(note)
        self._next_id += 1
        return note

    def search(self, query: str) -> list[Note]:
        return self._store.search(query)
