import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/setupTests.ts",
    // Unit tests live under src/. The Playwright e2e specs in tests/e2e/ are run by
    // `playwright test`, not Vitest — excluding them keeps `npm test` from trying to
    // collect a @playwright/test spec (which throws at collection time).
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
