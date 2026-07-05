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
  needs_reingest?: boolean;
}

export interface VersionOut {
  id: string;
  ref_name: string;
  ref_type: string;
  commit_sha: string;
  status: string;
  file_count: number;
  chunk_count: number;
}

export interface FileChangeOut {
  path: string;
  status: string;
}

export interface CompareOut {
  added: FileChangeOut[];
  removed: FileChangeOut[];
  modified: FileChangeOut[];
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
  has_raw?: boolean;
}

// Direct URL to the original document bytes (PDF) for the visual viewer — loaded by the
// browser in an iframe, so it must be a plain GET URL, not a fetch.
export function sourceRawUrl(id: string, path: string): string {
  return `${API_BASE}/repos/${id}/source/raw?path=${encodeURIComponent(path)}`;
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

export async function createRepo(sourceUrl: string, ref?: string): Promise<IngestStarted> {
  const resp = await fetch(`${API_BASE}/repos`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ source_url: sourceUrl, ref: ref ?? null }),
  });
  return jsonOrThrow<IngestStarted>(resp);
}

// List a repo's indexed versions (branches/tags/commits), newest first.
export async function listVersions(id: string): Promise<VersionOut[]> {
  return jsonOrThrow(await fetch(`${API_BASE}/repos/${id}/versions`));
}

// Pull a ref's latest tip and incrementally re-index only what changed.
export async function updateRepo(id: string, ref?: string): Promise<IngestStarted> {
  const resp = await fetch(`${API_BASE}/repos/${id}/update`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ ref: ref ?? null }),
  });
  return jsonOrThrow<IngestStarted>(resp);
}

// Diff two indexed versions (by commit sha or ref name).
export async function compareVersions(
  id: string,
  base: string,
  head: string,
): Promise<CompareOut> {
  const q = new URLSearchParams({ base, head });
  return jsonOrThrow(await fetch(`${API_BASE}/repos/${id}/compare?${q.toString()}`));
}

export interface AuthoredFile {
  path: string;
  last_author: string | null;
  last_commit_sha: string | null;
  last_commit_at: string | null;
}

// Developer view: files a developer (partial name) last changed.
export async function searchDeveloper(id: string, author: string): Promise<AuthoredFile[]> {
  const q = new URLSearchParams({ author });
  return jsonOrThrow(await fetch(`${API_BASE}/repos/${id}/authored?${q.toString()}`));
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
  | { type: "route"; persona: string }
  | { type: "persona_active"; persona: string }
  | { type: "persona_done"; persona: string }
  | { type: "escalation"; mode: string; reason?: string }
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
