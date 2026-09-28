import { defineConfig } from "@playwright/test";

// Smoke test against the seeded backend (python -m backend.demo.seed --reset) and `npm run dev`.
// R10 must not be confirmed yet: the test uploads it.
export default defineConfig({
  testDir: "tests",
  timeout: 120_000,
  use: {
    baseURL: process.env.APP_URL ?? "http://localhost:5173",
    viewport: { width: 1366, height: 768 },
    launchOptions: process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {},
  },
});
