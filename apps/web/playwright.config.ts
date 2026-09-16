/**
 * B-17: one end-to-end smoke over the MVP workflow loop (PROMPT.md §13),
 * run against a *seeded stack the caller provides* — the compose deployment
 * (`docker compose up -d --build`) with the demo fixture loaded. Playwright
 * does not start or seed the stack: a test that boots its own database would
 * verify a different deployment than the one users run.
 *
 *   npm run test:e2e                       # against http://127.0.0.1:8000
 *   SPAGO_BASE_URL=http://host:port npm run test:e2e
 */
import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.SPAGO_BASE_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL,
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
