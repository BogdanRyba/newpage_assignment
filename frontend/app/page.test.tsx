import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Page from "./page";

// Mock the IO boundary; the real React render runs (this is what catches render-time bugs like a
// prop that was never threaded through — e.g. `suggestions is not defined` crashing the workspace).
const listRepos = vi.fn();
const getSuggestions = vi.fn();
const streamChat = vi.fn();
const getSource = vi.fn();
const listVersions = vi.fn();
const updateRepo = vi.fn();
const compareVersions = vi.fn();
const searchDeveloper = vi.fn();
vi.mock("./lib/api", () => ({
  listRepos: (...a: unknown[]) => listRepos(...a),
  getSuggestions: (...a: unknown[]) => getSuggestions(...a),
  streamChat: (...a: unknown[]) => streamChat(...a),
  getSource: (...a: unknown[]) => getSource(...a),
  listVersions: (...a: unknown[]) => listVersions(...a),
  updateRepo: (...a: unknown[]) => updateRepo(...a),
  compareVersions: (...a: unknown[]) => compareVersions(...a),
  searchDeveloper: (...a: unknown[]) => searchDeveloper(...a),
  sourceRawUrl: (id: string, path: string) =>
    `/api/repos/${id}/source/raw?path=${encodeURIComponent(path)}`,
  getRepo: vi.fn(),
  createRepo: vi.fn(),
  streamIngest: vi.fn(() => () => {}),
}));

const READY_REPO = {
  id: "r1",
  name: "notes-service",
  source_url: null,
  status: "ready",
  commit_sha: "abc1234",
  file_count: 8,
  chunk_count: 45,
};

describe("workspace render", () => {
  beforeEach(() => {
    listRepos.mockResolvedValue([READY_REPO]);
    getSuggestions.mockResolvedValue([
      "How does NoteStore search for notes?",
      "What does the Ranker score?",
    ]);
    streamChat.mockReset();
    listVersions.mockReset();
    listVersions.mockResolvedValue([]);
    updateRepo.mockReset();
    updateRepo.mockResolvedValue({ repo_id: "r1", job_id: "j1", name: "notes-service", status: "queued" });
    searchDeveloper.mockReset();
    searchDeveloper.mockResolvedValue([]);
    // openCitation auto-fires on the first citation; keep it inert for the render test.
    getSource.mockRejectedValue(new Error("source unavailable in test"));
  });

  it("renders the repo-specific suggestion chips after opening a repo", async () => {
    render(<Page />);
    // "use sample" → opens the ready repo → transitions to the workspace and fetches suggestions.
    fireEvent.click(screen.getByText("ariadne-sample").closest("button")!);

    // The LLM-generated chips must render. Regression: `suggestions` was never passed into
    // <Workspace>, so this render threw a ReferenceError and the screen crashed.
    expect(await screen.findByText("How does NoteStore search for notes?")).toBeInTheDocument();
    expect(screen.getByText("What does the Ranker score?")).toBeInTheDocument();
    await waitFor(() => expect(getSuggestions).toHaveBeenCalledWith("r1"));
  });

  it("falls back to a generic chip if no suggestions come back", async () => {
    getSuggestions.mockResolvedValue([]);
    render(<Page />);
    fireEvent.click(screen.getByText("ariadne-sample").closest("button")!);
    // Empty suggestions → the generic fallback chip renders; the workspace doesn't crash.
    expect(
      await screen.findByText("What does this repository do, and how is it organized?"),
    ).toBeInTheDocument();
  });

  it("renders markdown structure in the answer instead of raw * / ** markers", async () => {
    // Drive a streamed answer that contains bold + a bullet list + a citation. Regression:
    // the renderer only handled [n] citations, so `*` and `**` leaked through as literal text.
    streamChat.mockImplementation(
      async (_id: string, _text: string, onEvent: (e: unknown) => void) => {
        onEvent({
          type: "token",
          text: "It exposes **two** entrypoints:\n\n* The CLI runner [1]\n* The HTTP server",
        });
        onEvent({
          type: "citations",
          citations: [
            { n: 1, path: "app/main.py", start: 10, end: 12, symbol: null, label: "app/main.py:10-12" },
          ],
        });
        onEvent({ type: "done" });
      },
    );

    render(<Page />);
    fireEvent.click(screen.getByText("ariadne-sample").closest("button")!);
    const ask = await screen.findByPlaceholderText("Ask about the codebase");
    fireEvent.change(ask, { target: { value: "What are the entrypoints?" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    const answer = await screen.findByTestId("daedalus-answer");

    // Bold renders as <strong> with no surrounding asterisks.
    const strong = await within(answer).findByText("two");
    expect(strong.tagName).toBe("STRONG");

    // Bullet lines become real list items, not a run-on paragraph with leading "*".
    const items = within(answer).getAllByRole("listitem");
    expect(items.map((li) => li.textContent)).toEqual(["The CLI runner main.py:10", "The HTTP server"]);

    // The citation inside a list item is still a clickable file:line button (basename only).
    expect(within(answer).getByRole("button", { name: "main.py:10" })).toBeInTheDocument();

    // No raw markdown markers survive in the rendered prose.
    expect(answer.textContent).not.toMatch(/\*\*|(^|\s)\*\s/);
  });

  it("offers a Preview/Source toggle for a markdown source and renders both views", async () => {
    // A markdown citation opens the source panel. Regression target: .md files used to render
    // only as raw lines with no way to read them as rendered docs.
    getSource.mockReset();
    getSource.mockResolvedValue({
      path: "README.md",
      lang: "text",
      total_lines: 2,
      highlight_start: 1,
      highlight_end: 1,
      lines: [
        { n: 1, text: "# Project" },
        { n: 2, text: "- a bullet item" },
      ],
    });
    streamChat.mockImplementation(
      async (_id: string, _text: string, onEvent: (e: unknown) => void) => {
        onEvent({ type: "token", text: "See the readme [1]." });
        onEvent({
          type: "citations",
          citations: [
            { n: 1, path: "README.md", start: 1, end: 1, symbol: null, label: "README.md:1" },
          ],
        });
        onEvent({ type: "done" });
      },
    );

    render(<Page />);
    fireEvent.click(screen.getByText("ariadne-sample").closest("button")!);
    const ask = await screen.findByPlaceholderText("Ask about the codebase");
    fireEvent.change(ask, { target: { value: "What's in the readme?" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    // Markdown defaults to the rendered preview: the "#"/"-" markers become a heading + list item.
    const preview = await screen.findByTestId("doc-preview");
    expect(within(preview).getByText("Project").parentElement?.tagName).toBe("DIV");
    expect(within(preview).getByRole("listitem").textContent).toBe("a bullet item");
    expect(preview.textContent).not.toMatch(/^#|(^|\s)- /);

    // Flipping to Source shows the raw markdown line instead.
    fireEvent.click(screen.getByRole("button", { name: "Source" }));
    expect(screen.queryByTestId("doc-preview")).toBeNull();
    expect(screen.getByText("# Project")).toBeInTheDocument();
  });

  it("renders a PDF citation as a visual document with a Document/Text toggle", async () => {
    getSource.mockReset();
    getSource.mockResolvedValue({
      path: "docs/spec.pdf",
      lang: "text",
      total_lines: 1,
      highlight_start: 1,
      highlight_end: 1,
      lines: [{ n: 1, text: "Architecture overview" }],
      has_raw: true,
    });
    streamChat.mockImplementation(
      async (_id: string, _text: string, onEvent: (e: unknown) => void) => {
        onEvent({ type: "token", text: "See the spec [1]." });
        onEvent({
          type: "citations",
          citations: [
            { n: 1, path: "docs/spec.pdf", start: 1, end: 1, symbol: null, label: "docs/spec.pdf:1" },
          ],
        });
        onEvent({ type: "done" });
      },
    );

    render(<Page />);
    fireEvent.click(screen.getByText("ariadne-sample").closest("button")!);
    const ask = await screen.findByPlaceholderText("Ask about the codebase");
    fireEvent.change(ask, { target: { value: "What's the architecture?" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    // Defaults to the visual document view: an iframe pointed at the raw-bytes endpoint.
    const frame = await screen.findByTestId("doc-pdf");
    expect(frame.getAttribute("src")).toContain("/repos/r1/source/raw");
    expect(frame.getAttribute("src")).toContain("path=docs%2Fspec.pdf");

    // Switching to Text shows the extracted prose instead of the embedded document.
    fireEvent.click(screen.getByRole("button", { name: "Text" }));
    expect(screen.queryByTestId("doc-pdf")).toBeNull();
    expect(screen.getByText("Architecture overview")).toBeInTheDocument();
  });

  it("surfaces orchestrator persona routing in the thinking trace", async () => {
    // The coordinator/orchestrator emits route + persona_active events; the UI shows which
    // specialist is consulted, then renders the grounded answer as usual.
    streamChat.mockImplementation(
      async (_id: string, _text: string, onEvent: (e: unknown) => void) => {
        onEvent({ type: "route", persona: "dev_search" });
        onEvent({ type: "persona_active", persona: "dev_search" });
        onEvent({ type: "token", text: "Ada Lovelace last changed it [1]." });
        onEvent({
          type: "citations",
          citations: [
            { n: 1, path: "store.py", start: 1, end: 2, symbol: null, label: "store.py:1-2" },
          ],
        });
        onEvent({ type: "done" });
      },
    );

    render(<Page />);
    fireEvent.click(screen.getByText("ariadne-sample").closest("button")!);
    const ask = await screen.findByPlaceholderText("Ask about the codebase");
    fireEvent.change(ask, { target: { value: "who wrote store.py?" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    // The persona the orchestrator consulted is visible in the trace.
    expect(await screen.findByText("Consulting dev_search")).toBeInTheDocument();
    // The grounded answer still renders.
    const answer = await screen.findByTestId("daedalus-answer");
    expect(answer.textContent).toContain("Ada Lovelace");
  });

  it("shows a project dashboard and opens a project on click", async () => {
    render(<Page />);
    // The home screen lists indexed projects as cards.
    expect(await screen.findByText("Your projects")).toBeInTheDocument();
    const card = (await screen.findAllByText("notes-service"))[0].closest("button")!;
    fireEvent.click(card);
    // Clicking a card opens its workspace.
    expect(await screen.findByPlaceholderText("Ask about the codebase")).toBeInTheDocument();
  });

  it("lists indexed versions and triggers an incremental update", async () => {
    listVersions.mockResolvedValue([
      { id: "v2", ref_name: "dev", ref_type: "branch", commit_sha: "deadbeefcafe",
        status: "ready", file_count: 9, chunk_count: 50 },
      { id: "v1", ref_name: "main", ref_type: "branch", commit_sha: "abc1234567ef",
        status: "ready", file_count: 8, chunk_count: 45 },
    ]);

    render(<Page />);
    fireEvent.click(screen.getByText("ariadne-sample").closest("button")!);
    await screen.findByPlaceholderText("Ask about the codebase");

    // Both indexed versions are listed in the selector.
    const select = (await screen.findByLabelText("version")) as HTMLSelectElement;
    expect(within(select).getByText(/dev · deadbeef/)).toBeInTheDocument();
    expect(within(select).getByText(/main · abc12345/)).toBeInTheDocument();

    // The Update button kicks off an incremental re-index.
    fireEvent.click(screen.getByRole("button", { name: "Update" }));
    await waitFor(() => expect(updateRepo).toHaveBeenCalledWith("r1"));

    // Compare diffs the two newest versions and lists the changed files (clickable).
    compareVersions.mockResolvedValue({
      added: [{ path: "new.py", status: "added" }],
      removed: [],
      modified: [{ path: "store.py", status: "modified" }],
    });
    fireEvent.click(screen.getByRole("button", { name: "Compare" }));
    expect(compareVersions).toHaveBeenCalledWith("r1", "main", "dev");
    // The changed files appear in the diff panel with their change tag.
    expect(await screen.findByText("new.py")).toBeInTheDocument();
    expect(screen.getByText("store.py")).toBeInTheDocument();
    expect(screen.getByText("added")).toBeInTheDocument();
  });

  it("searches files by developer and opens one in the source panel", async () => {
    listVersions.mockResolvedValue([
      { id: "v1", ref_name: "main", ref_type: "branch", commit_sha: "abc1234567ef",
        status: "ready", file_count: 8, chunk_count: 45 },
    ]);
    searchDeveloper.mockResolvedValue([
      { path: "store.py", last_author: "Ada", last_commit_sha: "deadbeef00", last_commit_at: "" },
    ]);
    getSource.mockResolvedValue({
      path: "store.py", lang: "python", total_lines: 1, highlight_start: 1, highlight_end: 1,
      lines: [{ n: 1, text: "x = 1" }],
    });

    render(<Page />);
    fireEvent.click(screen.getByText("ariadne-sample").closest("button")!);
    const devInput = await screen.findByLabelText("developer");
    fireEvent.change(devInput, { target: { value: "Ada" } });
    fireEvent.keyDown(devInput, { key: "Enter" });

    await waitFor(() => expect(searchDeveloper).toHaveBeenCalledWith("r1", "Ada"));
    const row = await screen.findByText("store.py");
    fireEvent.click(row);
    await waitFor(() => expect(getSource).toHaveBeenCalledWith("r1", "store.py", 1, 1));
  });
});
