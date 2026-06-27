// Minimal HTTP-ish layer over the notes service (TypeScript fixture).

export const DEFAULT_LIMIT = 20;

export interface NoteDTO {
  id: number;
  title: string;
  body: string;
  tags: string[];
}

/** A note paired with its relevance score — interface inheritance (`extends`). */
export interface ScoredNote extends NoteDTO {
  score: number;
}

/** Strategy interface: score a note against the query's terms. */
export interface Ranker {
  score(note: NoteDTO, terms: string[]): number;
}

/** Counts how many query terms appear in the note's title or body. */
export class OverlapRanker implements Ranker {
  score(note: NoteDTO, terms: string[]): number {
    const haystack = `${note.title} ${note.body}`.toLowerCase();
    return terms.filter((t) => haystack.includes(t)).length;
  }
}

/** Overlap ranking, but terms matched in the title count double. */
export class TitleBoostRanker implements Ranker {
  score(note: NoteDTO, terms: string[]): number {
    const title = note.title.toLowerCase();
    const body = note.body.toLowerCase();
    const base = terms.filter((t) => title.includes(t) || body.includes(t)).length;
    const titleHits = terms.filter((t) => title.includes(t)).length;
    return base + titleHits;
  }
}

/** Build a NoteDTO from raw request input. */
export function createNote(id: number, title: string, body: string, tags: string[]): NoteDTO {
  return { id, title, body, tags };
}

/** Filter notes whose title or body contains the query, capped at `limit`. */
export function searchNotes(
  notes: NoteDTO[],
  query: string,
  limit: number = DEFAULT_LIMIT,
): NoteDTO[] {
  const q = query.toLowerCase();
  const hits = notes.filter(
    (n) => n.title.toLowerCase().includes(q) || n.body.toLowerCase().includes(q),
  );
  return hits.slice(0, limit);
}
