import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Renders components in jsdom so tests exercise the real render path (catches undefined refs,
// missing props, broken render logic) — the IO boundary (./lib/api) is mocked per test.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
  },
});
