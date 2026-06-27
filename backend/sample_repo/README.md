# notes-service (Ariadne test fixture)

A small polyglot codebase Ariadne ingests for testing and as the bundled demo seed.

- **Python** (`notes/`): `models.Note`, an in-memory `store.NoteStore`, a `ranking` module with
  an abstract `Ranker` strategy and two concrete subclasses (`OverlapRanker`, `TitleBoostRanker`)
  plus the `rank_notes` helper, a `service.NoteService` that wires them together, and top-level
  constants in `config.py` (`MAX_RESULTS`, `STOPWORDS`).
- **TypeScript** (`web/api.ts`): `NoteDTO`, a `ScoredNote` interface that `extends` it, a `Ranker`
  interface with two classes that `implement` it (`OverlapRanker`, `TitleBoostRanker`),
  `createNote`, `searchNotes`, `DEFAULT_LIMIT`.

It deliberately exercises every part of the pipeline: AST chunking across two languages,
module-level constants/docstrings (which must be retrievable), **polymorphism / inheritance**
(an abstract base with sibling subclasses in Python; interface `extends` + class `implements` in
TypeScript — the graph models these as `EXTENDS`/`IMPLEMENTS` edges), a call/contains graph
(`NoteService` → `NoteStore` → `Ranker`; `NoteStore` contains its methods), and prompt-injection
defense — `ranking.py` contains a bait comment ("ignore all previous instructions…") that a
grounded assistant must treat as data, never obey.

The `Ranker`/`OverlapRanker` names appear in **both** languages on purpose: it proves the graph
keeps inheritance edges language-scoped (a Python class never links to a same-named TS symbol).
