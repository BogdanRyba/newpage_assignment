# notes-service (Ariadne test fixture)

A small polyglot codebase Ariadne ingests for testing and as the bundled demo seed.

- **Python** (`notes/`): `models.Note`, an in-memory `store.NoteStore`, a `ranking.rank_notes`
  scorer, a `service.NoteService` that wires them together, and top-level constants in
  `config.py` (`MAX_RESULTS`, `STOPWORDS`).
- **TypeScript** (`web/api.ts`): `NoteDTO`, `createNote`, `searchNotes`, `DEFAULT_LIMIT`.

It deliberately exercises every part of the pipeline: AST chunking across two languages,
module-level constants/docstrings (which must be retrievable), a call/contains graph
(`NoteService` → `NoteStore` → `rank_notes`; `NoteStore` contains its methods), and
prompt-injection defense — `ranking.py` contains a bait comment ("ignore all previous
instructions…") that a grounded assistant must treat as data, never obey.
