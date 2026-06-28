import { expect, test } from "@playwright/test";

// Real end-to-end: drive the actual browser UI against the real backend + Gemini, ingesting a
// public repo and asserting the streamed answer RENDERS. This is the test that catches the class
// of bug unit/integration tests missed — the chat SSE parser failing in the browser so the answer
// never appeared. If the SSE pipeline (status → tokens → citations → done) doesn't reach the DOM,
// the "Sources" section + citation never show and this fails.

const REPO_URL = "https://github.com/qxresearch/qxresearch-event-1";

test("ingest a real repo, ask a question, and render the streamed answer with citations", async ({
  page,
}) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });

  // --- Ingest screen: point at the repo and index it ---
  await page.getByPlaceholder("github.com/org/repo").fill(REPO_URL);
  await page.getByRole("button", { name: "Index repository" }).click();

  // --- Indexing → workspace (real clone + embed; can take a couple of minutes) ---
  const ask = page.getByPlaceholder("Ask about the codebase");
  await expect(ask).toBeVisible({ timeout: 240_000 });

  // The workspace header shows a non-zero file count (ingest actually counted files).
  await expect(page.getByText(/[1-9]\d*\s+files\s+·/)).toBeVisible();

  // --- Ask a specific question that the model can ground in a file (so it cites) ---
  await ask.fill("How does measure_noise affect generate_numbers in FreshProject.py?");
  await page.getByRole("button", { name: "Ask" }).click();

  // Each assertion proves a slice of the SSE→DOM pipeline that was broken (parser never fired):
  // 1) status events → the live "thinking" trace renders
  await expect(page.getByText("Searching the hybrid index")).toBeVisible({ timeout: 30_000 });
  // 2) token events → the answer prose actually renders (non-empty), not just a cursor
  await expect
    .poll(async () => (await page.getByTestId("daedalus-answer").last().innerText()).trim().length, {
      timeout: 150_000,
    })
    .toBeGreaterThan(40);
  // 3) citations event → renderSegments turned [n] into a clickable `file:line` citation button
  await expect(page.getByRole("button", { name: /\.py:\d+/ }).first()).toBeVisible({
    timeout: 30_000,
  });
});
