import { expect, test } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

const OUT_DIR = path.resolve(__dirname, "../../docs/assets");

test.describe.configure({ mode: "serial" });
test.use({ video: "on" });

test("capture assignment screenshots", async ({ page }) => {
  fs.mkdirSync(OUT_DIR, { recursive: true });

  await page.goto("/", { waitUntil: "networkidle" });
  await page.screenshot({ path: path.join(OUT_DIR, "01-ingest.png"), fullPage: true });

  // Open the seeded sample repo from the project list (more reliable than the Sample shortcut).
  const project = page.getByRole("button", { name: /notes-service/i }).first();
  await expect(project).toBeVisible({ timeout: 60_000 });
  await project.click();

  const ask = page.getByPlaceholder("Ask about the codebase");
  await expect(ask).toBeVisible({ timeout: 60_000 });

  await ask.fill("How does NoteStore search for notes?");
  await page.getByRole("button", { name: "Ask" }).click();

  await expect(page.getByText("Searching the hybrid index")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("Sources")).toBeVisible({ timeout: 120_000 });

  const citation = page.getByRole("button", { name: /notes\/store\.py:\d+/ }).first();
  await expect(citation).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: path.join(OUT_DIR, "02-chat-citations.png"), fullPage: true });

  await citation.click();
  await expect(page.locator("pre, code").first()).toBeVisible({ timeout: 15_000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(OUT_DIR, "03-source-panel.png"), fullPage: true });
});
