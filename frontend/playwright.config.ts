import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 120_000,
  use: { baseURL: process.env.MADOSHO_UI_URL ?? "http://127.0.0.1:8080" },
  reporter: "list",
});
