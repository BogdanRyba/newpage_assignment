// API client for the Ariadne backend. SSE is consumed two ways: EventSource for the
// GET ingest-progress stream, and fetch+ReadableStream for the POST chat stream.

import { API_BASE } from "../theme";

export interface RepoOut {
  id: string;
  name: string;
  source_url: string | null;
  status: string;
  commit_sha: string | null;
  file_count: number;
  chunk_count: number;
}

export interface JobOut {
  id: string;
  status: string;
  phase: string;
  files_done: number;
  chunks_done: number;
  pct: number;
  error: string | null;
}

export interface IngestStarted {
  repo_id: string;
  job_id: string;
  name: string;
  status: string;
}

export interface SourceLine {
  n: number;
  text: string;
}

export interface SourceOut {
  path: string;
  lang: string;
  total_lines: number;
  highlight_start: number | null;
  highlight_end: number | null;
  lines: SourceLine[];
}

export interface Citation {
  n: number;
  path: string;
  start: number;
  end: number;
  symbol: string | null;
  label: string;
}

async function jsonOrThrow<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body?.error?.message ?? `request failed (${resp.status})`);
  }
  return resp.json() as Promise<T>;
}

export async function createRepo(sourceUrl: string): Promise<IngestStarted> {
  const resp = await fetch(`${API_BASE}/repos`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ source_url: sourceUrl }),
  });
  return jsonOrThrow<IngestStarted>(resp);
}

export async function getRepo(id: string): Promise<{ repo: RepoOut; job: JobOut | null }> {
  return jsonOrThrow(await fetch(`${API_BASE}/repos/${id}`));
}

export async function listRepos(): Promise<RepoOut[]> {
  return jsonOrThrow(await fetch(`${API_BASE}/repos`));
}

export async function getSource(
  id: string,
  path: string,
  start?: number,
  end?: number,
): Promise<SourceOut> {
  const q = new URLSearchParams({ path });
  if (start) q.set("start", String(start));
  if (end) q.set("end", String(end));
  return jsonOrThrow(await fetch(`${API_BASE}/repos/${id}/source?${q.toString()}`));
}

// Subscribe to ingest progress (GET SSE). Returns an unsubscribe fn.
export function streamIngest(
  id: string,
  onProgress: (job: Partial<JobOut> & { type?: string }) => void,
  onDone: () => void,
): () => void {
  const es = new EventSource(`${API_BASE}/repos/${id}/ingest/stream`);
  es.addEventListener("progress", (e) => onProgress(JSON.parse((e as MessageEvent).data)));
  es.addEventListener("done", () => {
    es.close();
    onDone();
  });
  es.onerror = () => es.close();
  return () => es.close();
}

export type ChatEvent =
  | { type: "session"; session_id: string }
  | { type: "status"; label: string; detail?: string }
  | { type: "token"; text: string }
  | { type: "citations"; citations: Citation[] }
  | { type: "no_sources"; reason?: string }
  | { type: "done" };

// LLM-generated starter questions grounded in the repo's files/symbols.
export async function getSuggestions(id: string): Promise<string[]> {
  const { suggestions } = await jsonOrThrow<{ suggestions: string[] }>(
    await fetch(`${API_BASE}/repos/${id}/suggestions`),
  );
  return suggestions;
}

// POST chat with an SSE response body, parsed from the fetch stream.
export async function streamChat(
  id: string,
  message: string,
  onEvent: (e: ChatEvent) => void,
  sessionId?: string,
): Promise<void> {
  const resp = await fetch(`${API_BASE}/repos/${id}/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId ?? null }),
  });
  if (!resp.ok || !resp.body) throw new Error(`chat failed (${resp.status})`);

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // sse_starlette delimits events with CRLF (`\r\n\r\n`), so split on either CRLF or LF —
    // splitting on "\n\n" alone never matches and no event is ever parsed (the chat hangs).
    const frames = buffer.split(/\r?\n\r?\n/);
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const dataLine = frame.split(/\r?\n/).find((l) => l.startsWith("data:"));
      if (!dataLine) continue;
      try {
        onEvent(JSON.parse(dataLine.slice(5).trim()) as ChatEvent);
      } catch {
        /* ignore keep-alive / partial */
      }
    }
  }
}
