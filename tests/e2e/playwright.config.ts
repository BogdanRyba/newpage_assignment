import { defineConfig } from "@playwright/test";

// Drives the real UI against the real backend + Gemini. baseURL points at the frontend service
// on the compose network; the in-container browser reaches the API via NEXT_PUBLIC_API_BASE
// (set to http://api:8000 by scripts/e2e.sh). Real ingest + LLM are slow → generous timeouts.
export default defineConfig({
  testDir: ".",
  timeout: 300_000,
  expect: { timeout: 30_000 },
  reporter: [["list"]],
  use: {
    baseURL: process.env.BASE_URL ?? "http://frontend:3000",
    headless: true,
    trace: "retain-on-failure",
  },
});
