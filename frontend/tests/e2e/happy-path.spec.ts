import { test, expect } from "@playwright/test";
import { fileURLToPath } from "node:url";
import path from "node:path";

const PDF = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "fixtures", "contract.pdf");

test("create → upload → indexed → query → citation → detail", async ({ page }) => {
  const name = `e2e-${Date.now()}`;
  await page.goto("/");
  await page.getByPlaceholder(/corpus name/i).fill(name);
  await page.getByRole("button", { name: /create/i }).click();
  await page.getByRole("link", { name }).click();

  await page.getByLabel(/upload/i).setInputFiles(PDF);
  await expect(page.getByText("indexed")).toBeVisible({ timeout: 90_000 });  // worker indexes it

  await page.getByRole("link", { name: /playground/i }).click();
  await page.getByLabel(/corpus/i).selectOption(name);
  await page.getByPlaceholder(/ask/i).fill("termination notice period");
  await page.getByRole("button", { name: /ask/i }).click();

  const citation = page.getByRole("link", { name: /p\.\d+/ }).first();
  await expect(citation).toBeVisible({ timeout: 30_000 });
  await citation.click();
  await expect(page.getByText(/extracted/i)).toBeVisible();   // landed on document detail
});
