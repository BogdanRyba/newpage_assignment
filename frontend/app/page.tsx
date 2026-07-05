"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";

import {
  type Citation,
  type RepoOut,
  type SourceOut,
  type VersionOut,
  compareVersions,
  createRepo,
  getRepo,
  getSource,
  getSuggestions,
  listRepos,
  listVersions,
  searchDeveloper,
  sourceRawUrl,
  streamChat,
  streamIngest,
  updateRepo,
} from "./lib/api";
import { highlight } from "./lib/highlight";
import { renderMarkdown } from "./lib/markdown";
import { C, mono, sans } from "./theme";

type Phase = "ingest" | "indexing" | "workspace";

interface Step {
  label: string;
  detail?: string;
}

interface Msg {
  role: "user" | "assistant";
  text: string;
  citations: Citation[];
  streaming: boolean;
  noSources: boolean;
  steps: Step[];
}

const PHASE_ORDER = ["cloning", "parsing", "embedding", "building_index"];
const PHASE_LABELS = [
  "Cloning repository",
  "Parsing source files",
  "Embedding chunks",
  "Building hybrid index",
];

// Shown only until the LLM-generated, repo-specific suggestions arrive (or if they fail).
const FALLBACK_SUGGESTIONS = [
  "What does this repository do, and how is it organized?",
  "What are the main modules and how do they fit together?",
];

export default function Page() {
  const [phase, setPhase] = useState<Phase>("ingest");
  const [repoUrl, setRepoUrl] = useState("github.com/you/ariadne");
  const [repoId, setRepoId] = useState("");
  const [repoMeta, setRepoMeta] = useState({
    name: "",
    sha: "",
    stats: "",
    needsReingest: false,
  });
  const [ix, setIx] = useState({ phase: "cloning", files: 0, chunks: 0, pct: 0 });
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [openFile, setOpenFile] = useState<SourceOut | null>(null);
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [error, setError] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const codeRef = useRef<HTMLDivElement>(null);

  // Fetch repo-specific, LLM-generated starter questions whenever we open a workspace.
  useEffect(() => {
    if (phase !== "workspace" || !repoId) return;
    setSuggestions([]);
    getSuggestions(repoId)
      .then(setSuggestions)
      .catch(() => setSuggestions([]));
  }, [phase, repoId]);

  const startIndex = useCallback(async () => {
    if (!repoUrl.trim()) return;
    setError("");
    try {
      const started = await createRepo(repoUrl.trim());
      setRepoId(started.repo_id);
      setRepoMeta((m) => ({ ...m, name: started.name }));
      setPhase("indexing");
      setIx({ phase: "cloning", files: 0, chunks: 0, pct: 0 });
      streamIngest(
        started.repo_id,
        (job) => {
          setIx({
            phase: job.phase ?? "cloning",
            files: job.files_done ?? 0,
            chunks: job.chunks_done ?? 0,
            pct: job.pct ?? 0,
          });
          if (job.error) setError(job.error);
        },
        async () => {
          const { repo } = await getRepo(started.repo_id);
          if (repo.status === "failed") {
            setError("Indexing failed. Check the repo URL and the worker logs.");
            setPhase("ingest");
            return;
          }
          setRepoMeta({
            name: repo.name,
            sha: repo.commit_sha ?? "",
            stats: `${repo.file_count} files · ${repo.chunk_count} chunks`,
            needsReingest: repo.needs_reingest ?? false,
          });
          setMessages([]);
          setOpenFile(null);
          setPhase("workspace");
        },
      );
    } catch (e) {
      setError((e as Error).message);
    }
  }, [repoUrl]);

  const openRepo = useCallback((repo: RepoOut) => {
    setRepoId(repo.id);
    setRepoMeta({
      name: repo.name,
      sha: repo.commit_sha ?? "",
      stats: `${repo.file_count} files · ${repo.chunk_count} chunks`,
      needsReingest: repo.needs_reingest ?? false,
    });
    setMessages([]);
    setOpenFile(null);
    setPhase("workspace");
  }, []);

  const openSample = useCallback(async () => {
    setError("");
    try {
      const repos = await listRepos();
      const ready = repos.find((r) => r.status === "ready");
      if (!ready) {
        setError("No indexed repo yet — index one above, or wait for the sample to finish seeding.");
        return;
      }
      openRepo(ready);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [openRepo]);

  const openCitation = useCallback(
    async (c: { path: string; start: number; end: number }) => {
      try {
        const src = await getSource(repoId, c.path, c.start, c.end);
        setOpenFile(src);
        setTimeout(() => {
          if (codeRef.current) codeRef.current.scrollTop = Math.max(0, (c.start - 4) * 22);
        }, 40);
      } catch {
        /* file may not be servable; ignore */
      }
    },
    [repoId],
  );

  const send = useCallback(
    async (raw?: string) => {
      const text = (raw ?? input).trim();
      if (!text || !repoId) return;
      setInput("");
      setMessages((m) => [
        ...m,
        { role: "user", text, citations: [], streaming: false, noSources: false, steps: [] },
        { role: "assistant", text: "", citations: [], streaming: true, noSources: false, steps: [] },
      ]);
      const update = (fn: (m: Msg) => Msg) =>
        setMessages((msgs) => {
          const copy = msgs.slice();
          copy[copy.length - 1] = fn(copy[copy.length - 1]);
          return copy;
        });
      let firstCite: Citation | undefined;
      try {
        await streamChat(
          repoId,
          text,
          (e) => {
            if (e.type === "session") setSessionId(e.session_id);
            else if (e.type === "route")
              update((m) => ({ ...m, steps: [...m.steps, { label: `Routing to ${e.persona}` }] }));
            else if (e.type === "persona_active")
              update((m) => ({ ...m, steps: [...m.steps, { label: `Consulting ${e.persona}` }] }));
            else if (e.type === "escalation")
              update((m) => ({
                ...m,
                steps: [...m.steps, { label: "Escalating to a human", detail: e.mode }],
              }));
            else if (e.type === "status")
              update((m) => ({ ...m, steps: [...m.steps, { label: e.label, detail: e.detail }] }));
            else if (e.type === "token") update((m) => ({ ...m, text: m.text + e.text }));
            else if (e.type === "citations") {
              firstCite = e.citations[0];
              update((m) => ({ ...m, citations: e.citations }));
            } else if (e.type === "no_sources") update((m) => ({ ...m, noSources: true }));
            else if (e.type === "done") update((m) => ({ ...m, streaming: false }));
          },
          sessionId,
        );
      } catch (err) {
        update((m) => ({ ...m, streaming: false, text: `⚠ ${(err as Error).message}` }));
      }
      if (firstCite) openCitation(firstCite);
    },
    [input, repoId, sessionId, openCitation],
  );

  if (phase === "ingest")
    return (
      <Ingest
        repoUrl={repoUrl}
        setRepoUrl={setRepoUrl}
        start={startIndex}
        openSample={openSample}
        openRepo={openRepo}
        error={error}
      />
    );
  if (phase === "indexing") return <Indexing name={repoMeta.name} ix={ix} error={error} />;

  return (
    <Workspace
      repoId={repoId}
      repoMeta={repoMeta}
      messages={messages}
      input={input}
      setInput={setInput}
      send={send}
      suggestions={suggestions}
      openFile={openFile}
      openCitation={openCitation}
      codeRef={codeRef}
      newRepo={() => {
        setPhase("ingest");
        setMessages([]);
        setOpenFile(null);
      }}
    />
  );
}

// ---------------- Ingest ----------------

function Ingest({
  repoUrl,
  setRepoUrl,
  start,
  openSample,
  openRepo,
  error,
}: {
  repoUrl: string;
  setRepoUrl: (s: string) => void;
  start: () => void;
  openSample: () => void;
  openRepo: (repo: RepoOut) => void;
  error: string;
}) {
  const [projects, setProjects] = useState<RepoOut[]>([]);
  useEffect(() => {
    listRepos()
      .then((rs) => setProjects(rs.filter((r) => r.status === "ready")))
      .catch(() => setProjects([]));
  }, []);

  return (
    <Centered>
      <div style={{ width: "100%", maxWidth: 540 }}>
        <Eyebrow>Code documentation assistant</Eyebrow>
        <div style={{ fontSize: 44, fontWeight: 600, letterSpacing: "-0.025em", marginTop: 18 }}>
          Ariadne
        </div>
        <div style={{ fontSize: 16, lineHeight: 1.6, color: C.muted, marginTop: 16, maxWidth: 440 }}>
          Ask questions about a codebase. Every answer cites the exact lines it came from.
        </div>
        <div
          style={{
            marginTop: 36,
            border: `1px solid ${C.line2}`,
            borderRadius: 8,
            background: C.panel,
            display: "flex",
            alignItems: "center",
            padding: "0 4px 0 16px",
            height: 52,
          }}
        >
          <span style={{ fontFamily: mono, fontSize: 12, color: C.faint2 }}>repo</span>
          <input
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && start()}
            placeholder="github.com/org/repo"
            spellCheck={false}
            style={{
              flex: 1,
              border: "none",
              outline: "none",
              background: "transparent",
              fontFamily: mono,
              fontSize: 14,
              color: C.ink,
              padding: "0 12px",
            }}
          />
          <button onClick={start} style={primaryBtn}>
            Index repository
          </button>
        </div>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginTop: 14,
          }}
        >
          <span style={{ fontSize: 13, color: C.faint }}>Point it at a public Git repo.</span>
          <button
            onClick={openSample}
            style={{
              border: "none",
              background: "none",
              cursor: "pointer",
              fontSize: 13,
              color: C.muted,
              display: "flex",
              gap: 8,
              alignItems: "center",
            }}
          >
            <span
              style={{
                fontFamily: mono,
                fontSize: 11,
                letterSpacing: ".12em",
                textTransform: "uppercase",
                color: C.faint2,
              }}
            >
              Sample
            </span>
            <span style={{ fontFamily: mono }}>ariadne-sample</span>
          </button>
        </div>
        {error && <div style={{ color: C.accent, fontSize: 13, marginTop: 14 }}>{error}</div>}

        {projects.length > 0 && (
          <div style={{ marginTop: 40 }}>
            <Label>Your projects</Label>
            <div
              className="ar-scroll"
              style={{
                marginTop: 12,
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
                gap: 12,
                maxHeight: 260,
                overflowY: "auto",
              }}
            >
              {projects.map((p) => (
                <button
                  key={p.id}
                  onClick={() => openRepo(p)}
                  style={{
                    textAlign: "left",
                    border: `1px solid ${C.line2}`,
                    borderRadius: 8,
                    background: C.panel,
                    padding: "12px 14px",
                    cursor: "pointer",
                  }}
                >
                  <div style={{ fontFamily: mono, fontSize: 13, color: C.ink }}>{p.name}</div>
                  <div style={{ fontSize: 12, color: C.faint, marginTop: 4 }}>
                    {p.file_count} files · {p.chunk_count} chunks
                  </div>
                  {p.needs_reingest && (
                    <div style={{ fontFamily: mono, fontSize: 10.5, color: C.accent, marginTop: 6 }}>
                      Re-index required
                    </div>
                  )}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </Centered>
  );
}

// ---------------- Indexing ----------------

function Indexing({
  name,
  ix,
  error,
}: {
  name: string;
  ix: { phase: string; files: number; chunks: number; pct: number };
  error: string;
}) {
  const step = ix.pct >= 100 ? 4 : Math.max(0, PHASE_ORDER.indexOf(ix.phase));
  const counts = ["", `${ix.files} files`, `${ix.chunks} chunks`, ""];
  return (
    <Centered>
      <div style={{ width: "100%", maxWidth: 440 }}>
        <Eyebrow>Indexing</Eyebrow>
        <div style={{ fontFamily: mono, fontSize: 18, marginTop: 12 }}>{name}</div>
        <div style={{ marginTop: 32, display: "flex", flexDirection: "column", gap: 2 }}>
          {PHASE_LABELS.map((label, i) => {
            const done = i < step;
            const active = i === step;
            return (
              <div
                key={label}
                style={{ display: "flex", alignItems: "center", gap: 14, padding: "11px 0" }}
              >
                <span
                  style={{
                    width: 9,
                    height: 9,
                    borderRadius: "50%",
                    flex: "none",
                    background: done || active ? C.accent : "transparent",
                    border: done || active ? "none" : `1px solid #D8D2C8`,
                    animation: active ? "ar-pulse 1.1s ease-in-out infinite" : undefined,
                  }}
                />
                <span
                  style={{
                    flex: 1,
                    fontSize: 14.5,
                    color: done ? C.muted : active ? C.ink : C.faint2,
                  }}
                >
                  {label}
                </span>
                <span style={{ fontFamily: mono, fontSize: 12.5, color: C.faint }}>{counts[i]}</span>
              </div>
            );
          })}
        </div>
        <div
          style={{
            marginTop: 26,
            height: 2,
            background: C.line,
            borderRadius: 2,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              height: "100%",
              background: C.accent,
              width: `${ix.pct}%`,
              transition: "width .12s linear",
            }}
          />
        </div>
        {error && <div style={{ color: C.accent, fontSize: 13, marginTop: 18 }}>{error}</div>}
      </div>
    </Centered>
  );
}

// ---------------- Workspace ----------------

function Workspace(props: {
  repoId: string;
  repoMeta: { name: string; sha: string; stats: string; needsReingest?: boolean };
  messages: Msg[];
  input: string;
  setInput: (s: string) => void;
  send: (raw?: string) => void;
  suggestions: string[];
  openFile: SourceOut | null;
  openCitation: (c: { path: string; start: number; end: number }) => void;
  codeRef: React.RefObject<HTMLDivElement>;
  newRepo: () => void;
}) {
  const {
    repoId,
    repoMeta,
    messages,
    input,
    setInput,
    send,
    suggestions,
    openFile,
    openCitation,
    codeRef,
    newRepo,
  } = props;
  const scrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages]);

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column", background: C.bg }}>
      <div
        style={{
          height: 53,
          flex: "none",
          borderBottom: `1px solid ${C.line}`,
          display: "flex",
          alignItems: "center",
          padding: "0 18px",
          gap: 16,
          background: C.panelAlt,
        }}
      >
        <span style={{ fontSize: 15, fontWeight: 600 }}>Ariadne</span>
        <span style={{ width: 1, height: 18, background: C.line2 }} />
        <span style={{ fontFamily: mono, fontSize: 13 }}>{repoMeta.name}</span>
        {repoMeta.sha && (
          <span style={{ fontFamily: mono, fontSize: 12, color: C.faint2 }}>{repoMeta.sha}</span>
        )}
        <span style={{ fontSize: 12.5, color: C.faint }}>{repoMeta.stats}</span>
        <VersionBar
          repoId={repoId}
          needsReingest={repoMeta.needsReingest}
          openCitation={openCitation}
        />
        <div style={{ flex: 1 }} />
        <button onClick={newRepo} style={ghostBtn}>
          New repository
        </button>
      </div>

      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        {/* chat */}
        <div
          style={{
            flex: "0 0 49%",
            display: "flex",
            flexDirection: "column",
            borderRight: `1px solid ${C.line}`,
            minWidth: 0,
          }}
        >
          <div
            ref={scrollRef}
            className="ar-scroll"
            style={{ flex: 1, overflowY: "auto", padding: "30px 36px 16px" }}
          >
            <div style={{ maxWidth: 680, margin: "0 auto" }}>
              {messages.length === 0 && (
                <div style={{ color: C.faint, fontSize: 14, marginTop: 20 }}>
                  Ask a question about <b>{repoMeta.name}</b>. Answers are grounded in the indexed
                  code and cite the exact lines.
                </div>
              )}
              {messages.map((m, i) => (
                <MessageView key={i} m={m} onCite={openCitation} />
              ))}
            </div>
          </div>

          <div
            style={{
              flex: "none",
              borderTop: `1px solid ${C.line}`,
              padding: "14px 36px 18px",
              background: C.panelAlt,
            }}
          >
            <div style={{ maxWidth: 680, margin: "0 auto" }}>
              <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
                {(suggestions.length ? suggestions : FALLBACK_SUGGESTIONS).map((s) => (
                  <button key={s} onClick={() => send(s)} style={chip}>
                    {s}
                  </button>
                ))}
              </div>
              <div
                style={{
                  display: "flex",
                  alignItems: "flex-end",
                  gap: 10,
                  border: `1px solid ${C.line2}`,
                  borderRadius: 10,
                  background: C.panel,
                  padding: "10px 10px 10px 16px",
                }}
              >
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      send();
                    }
                  }}
                  rows={1}
                  placeholder="Ask about the codebase"
                  spellCheck={false}
                  style={{
                    flex: 1,
                    border: "none",
                    outline: "none",
                    resize: "none",
                    background: "transparent",
                    fontFamily: sans,
                    fontSize: 15,
                    lineHeight: 1.5,
                    color: C.ink,
                    maxHeight: 120,
                  }}
                />
                <button onClick={() => send()} style={{ ...primaryBtn, height: 36, padding: "0 16px" }}>
                  Ask
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* source */}
        <div style={{ flex: "1 1 0", minWidth: 0, display: "flex", flexDirection: "column", background: C.panel }}>
          {openFile ? (
            <SourcePanel key={openFile.path} repoId={repoId} file={openFile} codeRef={codeRef} />
          ) : (
            <EmptySource />
          )}
        </div>
      </div>
    </div>
  );
}

// Version selector + Update + Compare (clickable diff) + developer search, wired to the backend.
interface PanelRow {
  path: string;
  tag: string;
}

function VersionBar({
  repoId,
  needsReingest,
  openCitation,
}: {
  repoId: string;
  needsReingest?: boolean;
  openCitation: (c: { path: string; start: number; end: number }) => void;
}) {
  const [versions, setVersions] = useState<VersionOut[]>([]);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [dev, setDev] = useState("");
  const [panel, setPanel] = useState<{ title: string; rows: PanelRow[] } | null>(null);

  useEffect(() => {
    listVersions(repoId)
      .then(setVersions)
      .catch(() => setVersions([]));
  }, [repoId]);

  const update = async () => {
    setBusy(true);
    setNote("");
    try {
      await updateRepo(repoId);
      setNote("Update queued — indexing changed files");
      setTimeout(() => {
        listVersions(repoId)
          .then(setVersions)
          .catch(() => {});
      }, 1500);
    } catch (e) {
      setNote((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const compare = async () => {
    if (versions.length < 2) return;
    setNote("");
    try {
      const diff = await compareVersions(repoId, versions[1].ref_name, versions[0].ref_name);
      const rows: PanelRow[] = [
        ...diff.added.map((c) => ({ path: c.path, tag: "added" })),
        ...diff.modified.map((c) => ({ path: c.path, tag: "modified" })),
        ...diff.removed.map((c) => ({ path: c.path, tag: "removed" })),
      ];
      setPanel({ title: `${versions[1].ref_name} … ${versions[0].ref_name}`, rows });
    } catch (e) {
      setNote((e as Error).message);
    }
  };

  const findDev = async () => {
    if (!dev.trim()) return;
    setNote("");
    try {
      const files = await searchDeveloper(repoId, dev.trim());
      setPanel({
        title: `Files changed by “${dev.trim()}”`,
        rows: files.map((f) => ({ path: f.path, tag: f.last_commit_sha?.slice(0, 8) ?? "" })),
      });
    } catch (e) {
      setNote((e as Error).message);
    }
  };

  const openRow = (path: string) => {
    openCitation({ path, start: 1, end: 1 });
    setPanel(null);
  };

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, position: "relative" }}>
      {versions.length > 0 && (
        <select
          aria-label="version"
          defaultValue={versions[0].id}
          style={{
            fontFamily: mono,
            fontSize: 12,
            color: C.ink,
            background: C.panel,
            border: `1px solid ${C.line2}`,
            borderRadius: 5,
            padding: "3px 6px",
          }}
        >
          {versions.map((v) => (
            <option key={v.id} value={v.id}>
              {v.ref_name} · {v.commit_sha.slice(0, 8)} ({v.status})
            </option>
          ))}
        </select>
      )}
      <button onClick={update} disabled={busy} style={ghostBtn}>
        {busy ? "Updating…" : "Update"}
      </button>
      {versions.length >= 2 && (
        <button onClick={compare} style={ghostBtn}>
          Compare
        </button>
      )}
      <input
        value={dev}
        onChange={(e) => setDev(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && findDev()}
        aria-label="developer"
        placeholder="developer…"
        spellCheck={false}
        style={{
          fontFamily: mono,
          fontSize: 12,
          width: 110,
          border: `1px solid ${C.line2}`,
          borderRadius: 5,
          padding: "3px 6px",
          outline: "none",
          background: C.panel,
          color: C.ink,
        }}
      />
      {needsReingest && (
        <span style={{ fontFamily: mono, fontSize: 11, color: C.accent }}>Re-index required</span>
      )}
      {note && <span style={{ fontSize: 11, color: C.faint }}>{note}</span>}

      {panel && (
        <div
          style={{
            position: "absolute",
            top: 36,
            left: 0,
            zIndex: 20,
            minWidth: 320,
            maxHeight: 320,
            overflowY: "auto",
            background: C.panel,
            border: `1px solid ${C.line2}`,
            borderRadius: 8,
            boxShadow: "0 8px 24px rgba(0,0,0,0.12)",
            padding: 10,
          }}
          className="ar-scroll"
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 6,
            }}
          >
            <span style={{ fontFamily: mono, fontSize: 11.5, color: C.muted }}>{panel.title}</span>
            <button
              onClick={() => setPanel(null)}
              style={{ border: "none", background: "none", cursor: "pointer", color: C.faint }}
            >
              ✕
            </button>
          </div>
          {panel.rows.length === 0 ? (
            <div style={{ fontSize: 12, color: C.faint, padding: "6px 4px" }}>No files.</div>
          ) : (
            panel.rows.map((r, i) => (
              <button
                key={`${r.path}-${i}`}
                onClick={() => openRow(r.path)}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  gap: 12,
                  width: "100%",
                  textAlign: "left",
                  border: "none",
                  background: "none",
                  cursor: "pointer",
                  padding: "4px 4px",
                  fontFamily: mono,
                  fontSize: 12,
                  color: C.ink,
                }}
              >
                <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{r.path}</span>
                <span style={{ color: C.faint2 }}>{r.tag}</span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

function MessageView({
  m,
  onCite,
}: {
  m: Msg;
  onCite: (c: { path: string; start: number; end: number }) => void;
}) {
  if (m.role === "user")
    return (
      <div style={{ marginBottom: 30 }}>
        <Label>Question</Label>
        <div style={{ fontSize: 16.5, lineHeight: 1.5, fontWeight: 500 }}>{m.text}</div>
      </div>
    );

  return (
    <div style={{ marginBottom: 38 }}>
      <Label>Daedalus</Label>
      {m.steps.length > 0 && (
        <div style={{ margin: "2px 0 14px", fontFamily: mono, fontSize: 12.5, lineHeight: 1.85 }}>
          {m.steps.map((s, i) => {
            const active = m.streaming && !m.text && i === m.steps.length - 1;
            return (
              <div key={i} style={{ display: "flex", gap: 8, color: active ? C.accent : C.faint }}>
                <span>{active ? "▸" : "·"}</span>
                <span>
                  {s.label}
                  {s.detail && <span style={{ color: C.faint2 }}> · {s.detail}</span>}
                </span>
              </div>
            );
          })}
        </div>
      )}
      <div
        style={{ fontSize: 15, lineHeight: 1.68, color: "#38332D" }}
        data-testid="daedalus-answer"
      >
        {renderMarkdown(m.text, { citations: m.citations, onCite })}
        {m.streaming && (m.text.length > 0 || m.steps.length === 0) && (
          <span
            style={{
              display: "inline-block",
              width: 7,
              height: 15,
              background: C.accent,
              verticalAlign: -2,
              marginLeft: 2,
              animation: "ar-blink 1s step-end infinite",
            }}
          />
        )}
      </div>
      {!m.streaming && m.citations.length > 0 && (
        <div style={{ marginTop: 18, borderTop: `1px solid ${C.line}`, paddingTop: 14 }}>
          <Label>Sources</Label>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {m.citations.map((c) => (
              <button
                key={c.n}
                onClick={() => onCite(c)}
                style={{
                  border: "none",
                  background: "none",
                  cursor: "pointer",
                  textAlign: "left",
                  display: "flex",
                  alignItems: "baseline",
                  gap: 11,
                  padding: "6px 8px",
                  margin: "0 -8px",
                  borderRadius: 5,
                }}
              >
                <span style={{ fontFamily: mono, fontSize: 11.5, color: C.accent }}>[{c.n}]</span>
                <span style={{ fontFamily: mono, fontSize: 12.5, color: C.muted }}>{c.label}</span>
              </button>
            ))}
          </div>
        </div>
      )}
      {!m.streaming && m.noSources && (
        <div style={{ marginTop: 14, fontFamily: mono, fontSize: 12, color: C.faint2 }}>
          No matching sources in this repository.
        </div>
      )}
    </div>
  );
}

function SourcePanel({
  repoId,
  file,
  codeRef,
}: {
  repoId: string;
  file: SourceOut;
  codeRef: React.RefObject<HTMLDivElement>;
}) {
  const dir = file.path.split("/").slice(0, -1).join("/");
  const base = file.path.split("/").pop();
  const hs = file.highlight_start ?? 0;
  const he = file.highlight_end ?? 0;
  // Three rendering modes by file type:
  //  - markdown: rendered "preview" (default) ⇄ raw "source"
  //  - PDF with stored bytes: visual "document" (default) ⇄ extracted "text"
  //  - everything else: source lines only, no toggle
  const isMarkdown = /\.(md|markdown|mdx)$/i.test(file.path);
  const isPdf = /\.pdf$/i.test(file.path) && Boolean(file.has_raw);
  const [view, setView] = useState<"source" | "preview" | "document">(
    isMarkdown ? "preview" : isPdf ? "document" : "source",
  );
  const docText = file.lines.map((l) => l.text).join("\n");
  const badge = isPdf ? "PDF" : isMarkdown ? "MARKDOWN" : file.lang.toUpperCase();
  return (
    <>
      <div
        style={{
          flex: "none",
          height: 47,
          borderBottom: `1px solid ${C.line}`,
          display: "flex",
          alignItems: "center",
          padding: "0 20px",
          gap: 8,
        }}
      >
        {dir && <span style={{ fontFamily: mono, fontSize: 12.5, color: C.faint }}>{dir}/</span>}
        <span style={{ fontFamily: mono, fontSize: 12.5 }}>{base}</span>
        <div style={{ flex: 1 }} />
        {isMarkdown && (
          <div style={segGroup}>
            <button onClick={() => setView("preview")} style={segBtn(view === "preview")}>
              Preview
            </button>
            <button onClick={() => setView("source")} style={segBtn(view === "source")}>
              Source
            </button>
          </div>
        )}
        {isPdf && (
          <div style={segGroup}>
            <button onClick={() => setView("document")} style={segBtn(view === "document")}>
              Document
            </button>
            <button onClick={() => setView("source")} style={segBtn(view === "source")}>
              Text
            </button>
          </div>
        )}
        {view === "source" && hs > 0 && (
          <span style={{ fontFamily: mono, fontSize: 11, color: C.accent }}>
            L{hs}
            {he !== hs ? `–${he}` : ""}
          </span>
        )}
        <span
          style={{
            fontFamily: mono,
            fontSize: 10,
            letterSpacing: ".12em",
            color: "#C2BBAF",
            border: `1px solid ${C.line}`,
            padding: "2px 6px",
            borderRadius: 4,
          }}
        >
          {badge}
        </span>
      </div>
      {view === "document" && isPdf ? (
        <iframe
          title={file.path}
          src={sourceRawUrl(repoId, file.path)}
          style={{ flex: 1, width: "100%", border: "none", background: C.panelAlt }}
          data-testid="doc-pdf"
        />
      ) : view === "preview" && isMarkdown ? (
        <div className="ar-scroll" style={{ flex: 1, overflow: "auto", padding: "28px 36px 60px" }}>
          <div
            style={{ maxWidth: 720, fontSize: 15, lineHeight: 1.7, color: "#38332D" }}
            data-testid="doc-preview"
          >
            {renderMarkdown(docText, { docMode: true })}
          </div>
        </div>
      ) : (
        <div ref={codeRef} className="ar-scroll" style={{ flex: 1, overflow: "auto", padding: "10px 0 60px" }}>
          {file.lines.map((line) => {
          const hot = line.n >= hs && line.n <= he && hs > 0;
          return (
            <div
              key={line.n}
              style={{
                display: "flex",
                background: hot ? "color-mix(in srgb, var(--accent,#A4471F) 9%, transparent)" : undefined,
                boxShadow: hot ? "inset 2px 0 0 var(--accent,#A4471F)" : undefined,
              }}
            >
              <span
                style={{
                  flex: "none",
                  width: 56,
                  textAlign: "right",
                  paddingRight: 18,
                  fontFamily: mono,
                  fontSize: 12.5,
                  lineHeight: "22px",
                  color: hot ? C.accent : "#C2BBAF",
                  userSelect: "none",
                }}
              >
                {line.n}
              </span>
              <code
                dangerouslySetInnerHTML={{ __html: highlight(line.text, file.lang) }}
                style={{
                  flex: 1,
                  whiteSpace: "pre",
                  fontFamily: mono,
                  fontSize: 13,
                  lineHeight: "22px",
                  color: "#46423D",
                  paddingRight: 28,
                }}
              />
            </div>
          );
          })}
        </div>
      )}
    </>
  );
}

function EmptySource() {
  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: C.faint2,
        fontSize: 13.5,
      }}
    >
      Select a citation to view its source.
    </div>
  );
}

// ---------------- shared bits ----------------

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        // minHeight (not height) + overflow so a tall body (e.g. a big project grid) scrolls
        // instead of pushing the header/button off-screen and out of reach.
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 40,
        overflowY: "auto",
        fontFamily: sans,
        background: C.bg,
        color: C.ink,
      }}
    >
      {children}
    </div>
  );
}

function Eyebrow({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontFamily: mono,
        fontSize: 11,
        letterSpacing: ".22em",
        textTransform: "uppercase",
        color: C.faint,
      }}
    >
      {children}
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontFamily: mono,
        fontSize: 10.5,
        letterSpacing: ".16em",
        textTransform: "uppercase",
        color: C.faint2,
        marginBottom: 9,
      }}
    >
      {children}
    </div>
  );
}

const primaryBtn: React.CSSProperties = {
  border: "none",
  background: C.ink,
  color: "#FBF9F5",
  fontFamily: sans,
  fontSize: 14,
  fontWeight: 500,
  height: 44,
  padding: "0 20px",
  borderRadius: 6,
  cursor: "pointer",
};

const ghostBtn: React.CSSProperties = {
  border: `1px solid ${C.line2}`,
  background: C.panel,
  color: C.muted,
  fontFamily: sans,
  fontSize: 13,
  height: 32,
  padding: "0 13px",
  borderRadius: 6,
  cursor: "pointer",
};

const chip: React.CSSProperties = {
  border: `1px solid #E5E0D7`,
  background: C.panel,
  color: C.muted,
  fontFamily: sans,
  fontSize: 12.5,
  padding: "6px 11px",
  borderRadius: 6,
  cursor: "pointer",
};

const segGroup: React.CSSProperties = {
  display: "flex",
  border: `1px solid ${C.line2}`,
  borderRadius: 6,
  overflow: "hidden",
  background: C.panel,
};

const segBtn = (active: boolean): React.CSSProperties => ({
  border: "none",
  background: active ? C.ink : "transparent",
  color: active ? "#FBF9F5" : C.muted,
  fontFamily: sans,
  fontSize: 11.5,
  fontWeight: 500,
  padding: "4px 11px",
  cursor: "pointer",
});
