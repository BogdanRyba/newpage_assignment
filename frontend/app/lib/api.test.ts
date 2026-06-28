import { afterEach, describe, expect, it, vi } from "vitest";

import { type ChatEvent, streamChat } from "./api";

// A ReadableStream that emits the given string chunks as UTF-8 bytes, then closes.
function byteStream(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  let i = 0;
  return new ReadableStream({
    pull(controller) {
      if (i < chunks.length) controller.enqueue(enc.encode(chunks[i++]));
      else controller.close();
    },
  });
}

describe("streamChat SSE parsing", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("parses CRLF-delimited events (sse_starlette format) across mid-frame chunk splits", async () => {
    // sse_starlette delimits with \r\n\r\n. Regression: splitting on "\n\n" matched nothing,
    // so onEvent never fired and the chat rendered no answer. One chunk splits a frame mid-way
    // to also exercise the buffering across reads.
    const chunks = [
      'event: session\r\ndata: {"type":"session","session_id":"s1"}\r\n\r\n',
      'event: status\r\ndata: {"type":"sta',
      'tus","label":"Searching"}\r\n\r\nevent: token\r\ndata: {"type":"token","text":"hi "}\r\n\r\n',
      'event: citations\r\ndata: {"type":"citations","citations":[{"n":1,"path":"a.py","start":1,"end":2,"symbol":"f","label":"a.py:1-2"}]}\r\n\r\n',
      'event: done\r\ndata: {"type":"done"}\r\n\r\n',
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, body: byteStream(chunks) })),
    );

    const events: ChatEvent[] = [];
    await streamChat("r1", "question", (e) => events.push(e));

    expect(events.map((e) => e.type)).toEqual([
      "session",
      "status",
      "token",
      "citations",
      "done",
    ]);
    expect(events.find((e) => e.type === "token")).toMatchObject({ text: "hi " });
    expect(events.find((e) => e.type === "citations")).toMatchObject({
      citations: [expect.objectContaining({ path: "a.py", label: "a.py:1-2" })],
    });
  });

  it("throws on a non-ok response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, status: 500, body: null })),
    );
    await expect(streamChat("r1", "q", () => {})).rejects.toThrow(/chat failed/);
  });
});
