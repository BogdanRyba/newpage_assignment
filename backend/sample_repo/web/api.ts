// Minimal HTTP-ish layer over the notes service (TypeScript fixture).

export const DEFAULT_LIMIT = 20;

export interface NoteDTO {
  id: number;
  title: string;
  body: string;
  tags: string[];
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
