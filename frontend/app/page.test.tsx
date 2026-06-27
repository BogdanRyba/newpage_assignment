import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Page from "./page";

// Mock the IO boundary; the real React render runs (this is what catches render-time bugs like a
// prop that was never threaded through — e.g. `suggestions is not defined` crashing the workspace).
const listRepos = vi.fn();
const getSuggestions = vi.fn();
vi.mock("./lib/api", () => ({
  listRepos: (...a: unknown[]) => listRepos(...a),
  getSuggestions: (...a: unknown[]) => getSuggestions(...a),
  getRepo: vi.fn(),
  getSource: vi.fn(),
  createRepo: vi.fn(),
  streamChat: vi.fn(),
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
});
