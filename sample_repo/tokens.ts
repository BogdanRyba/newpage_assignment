// A minimal tokenizer, used as TypeScript fixture data for chunking/retrieval.

export interface Token {
  kind: "word" | "number" | "symbol";
  value: string;
}

/** Split a line of text into typed tokens. */
export function tokenize(line: string): Token[] {
  const tokens: Token[] = [];
  for (const raw of line.split(/\s+/)) {
    if (raw.length === 0) continue;
    tokens.push({ kind: classify(raw), value: raw });
  }
  return tokens;
}

function classify(raw: string): Token["kind"] {
  if (/^\d+$/.test(raw)) return "number";
  if (/^[A-Za-z]+$/.test(raw)) return "word";
  return "symbol";
}
