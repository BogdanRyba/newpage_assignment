// Tiny block + inline markdown renderer shared by the chat answer and the document
// preview pane. Hand-rolled (not react-markdown) because answer citations must become
// clickable `file:line` buttons wired to onCite, and the set of constructs we render is
// small and known. SAFETY: everything goes through React as text, so it is escaped — we
// never use dangerouslySetInnerHTML, so raw HTML in a doc can't inject. In `docMode` a
// conservative allowlist of layout-only HTML tags is stripped for legibility.

import React from "react";

import type { Citation } from "./api";
import { C, mono } from "../theme";

export interface MarkdownOpts {
  // When provided, `[n]` / `[n, m]` tokens resolve to clickable citation buttons.
  citations?: Citation[];
  onCite?: (c: { path: string; start: number; end: number }) => void;
  // Document-preview mode: render `[text](url)` links and strip benign HTML tags.
  docMode?: boolean;
}

type Block =
  | { type: "h"; level: number; text: string }
  | { type: "p"; text: string }
  | { type: "code"; text: string }
  | { type: "list"; ordered: boolean; items: string[] };

const LIST_RE = /^\s*([-*+]|\d+\.)\s+/;
const HEADING_RE = /^(#{1,6})\s+(.*)$/;
const FENCE_RE = /^\s*```/;
// Layout-only tags we drop in docMode; <br> becomes a space. Anything else stays literal
// (and React-escaped). Deliberately narrow — no script/style/event-handler interpretation.
const BENIGN_HTML = /<\/?(?:p|a|div|span|center|img|sub|sup|kbd|b|i|em|strong|h[1-6])\b[^>]*>/gi;

function stripHtml(s: string): string {
  return s.replace(/<br\s*\/?>/gi, " ").replace(BENIGN_HTML, "");
}

function parseBlocks(text: string): Block[] {
  const lines = text.split("\n");
  const blocks: Block[] = [];
  let para: string[] = [];
  const flush = () => {
    if (para.length) blocks.push({ type: "p", text: para.join(" ") });
    para = [];
  };
  for (let i = 0; i < lines.length; ) {
    const line = lines[i];
    if (FENCE_RE.test(line)) {
      flush();
      const code: string[] = [];
      i++;
      while (i < lines.length && !FENCE_RE.test(lines[i])) {
        code.push(lines[i]);
        i++;
      }
      i++; // consume the closing fence (if any)
      blocks.push({ type: "code", text: code.join("\n") });
      continue;
    }
    if (/^\s*$/.test(line)) {
      flush();
      i++;
      continue;
    }
    const h = line.match(HEADING_RE);
    if (h) {
      flush();
      blocks.push({ type: "h", level: h[1].length, text: h[2] });
      i++;
      continue;
    }
    if (LIST_RE.test(line)) {
      flush();
      const ordered = /^\s*\d+\.\s+/.test(line);
      const items: string[] = [];
      while (i < lines.length && LIST_RE.test(lines[i])) {
        items.push(lines[i].replace(LIST_RE, ""));
        i++;
      }
      blocks.push({ type: "list", ordered, items });
      continue;
    }
    para.push(line);
    i++;
  }
  flush();
  return blocks;
}

function renderInline(raw: string, opts: MarkdownOpts, keyPrefix: string): React.ReactNode[] {
  const text = opts.docMode ? stripHtml(raw) : raw;
  const byN = new Map((opts.citations ?? []).map((c) => [c.n, c]));
  const parts: React.ReactNode[] = [];
  // Order matters: links before citations so `[text](url)` isn't misread as `[n]`.
  const re =
    /(\[[^\]\n]+\]\((?:https?:\/\/|\/|\.)[^)\s]+\)|\*\*[^*\n]+\*\*|`[^`]+`|\[\d+(?:\s*,\s*\d+)*\])/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  const k = () => `${keyPrefix}-${i++}`;
  while ((m = re.exec(text))) {
    if (m.index > last) parts.push(<span key={k()}>{text.slice(last, m.index)}</span>);
    const tok = m[0];
    if (tok.startsWith("[") && tok.includes("](")) {
      const split = tok.indexOf("](");
      const label = tok.slice(1, split);
      const href = tok.slice(split + 2, -1);
      parts.push(
        <a
          key={k()}
          href={href}
          target="_blank"
          rel="noreferrer noopener"
          style={{ color: C.accent, textDecoration: "underline" }}
        >
          {label}
        </a>,
      );
    } else if (tok.startsWith("**")) {
      parts.push(
        <strong key={k()} style={{ fontWeight: 600, color: C.ink }}>
          {tok.slice(2, -2)}
        </strong>,
      );
    } else if (tok[0] === "`") {
      parts.push(
        <code key={k()} style={codeChip}>
          {tok.slice(1, -1)}
        </code>,
      );
    } else {
      const nums = tok
        .slice(1, -1)
        .split(",")
        .map((s) => parseInt(s.trim(), 10))
        .filter((n) => !Number.isNaN(n));
      const found = nums.map((n) => byN.get(n)).filter((c): c is Citation => Boolean(c));
      if (found.length && opts.onCite) {
        const onCite = opts.onCite;
        found.forEach((c) =>
          parts.push(
            <button key={k()} onClick={() => onCite(c)} style={citeBtnStyle}>
              {c.path.split("/").pop()}:{c.start}
            </button>,
          ),
        );
      } else parts.push(<span key={k()}>{tok}</span>);
    }
    last = re.lastIndex;
  }
  if (last < text.length) parts.push(<span key={k()}>{text.slice(last)}</span>);
  return parts;
}

export function renderMarkdown(text: string, opts: MarkdownOpts = {}): React.ReactNode[] {
  return parseBlocks(text).map((b, bi) => {
    if (b.type === "h")
      return (
        <div
          key={bi}
          style={{
            fontSize: b.level <= 1 ? 19 : b.level === 2 ? 16.5 : 15,
            fontWeight: 600,
            color: C.ink,
            margin: bi === 0 ? "0 0 8px" : "20px 0 8px",
          }}
        >
          {renderInline(b.text, opts, `h${bi}`)}
        </div>
      );
    if (b.type === "code")
      return (
        <pre key={bi} style={preStyle}>
          <code style={{ fontFamily: mono, fontSize: 12.5 }}>{b.text}</code>
        </pre>
      );
    if (b.type === "list") {
      const Tag = b.ordered ? "ol" : "ul";
      return (
        <Tag key={bi} style={listStyle}>
          {b.items.map((it, ii) => (
            <li key={ii} style={{ paddingLeft: 4 }}>
              {renderInline(it, opts, `l${bi}-${ii}`)}
            </li>
          ))}
        </Tag>
      );
    }
    return (
      <p key={bi} style={{ margin: bi === 0 ? 0 : "12px 0 0" }}>
        {renderInline(b.text, opts, `p${bi}`)}
      </p>
    );
  });
}

const codeChip: React.CSSProperties = {
  fontFamily: mono,
  fontSize: 13,
  background: "#F1EDE6",
  padding: "1px 5px",
  borderRadius: 4,
  color: "#5A463C",
};

const citeBtnStyle: React.CSSProperties = {
  border: "none",
  background: "none",
  cursor: "pointer",
  fontFamily: mono,
  fontSize: 11.5,
  color: C.accent,
  padding: "0 1px",
  verticalAlign: "baseline",
};

const listStyle: React.CSSProperties = {
  margin: "10px 0 0",
  paddingLeft: 22,
  display: "flex",
  flexDirection: "column",
  gap: 6,
};

const preStyle: React.CSSProperties = {
  margin: "12px 0 0",
  padding: "12px 14px",
  background: "#F4F0E9",
  borderRadius: 6,
  overflowX: "auto",
  whiteSpace: "pre",
};
