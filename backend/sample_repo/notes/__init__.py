"""A tiny notes service — Ariadne's polyglot test fixture."""

from .models import Note
from .service import NoteService

__all__ = ["Note", "NoteService"]
