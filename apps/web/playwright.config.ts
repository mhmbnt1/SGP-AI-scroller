import { defineConfig, devices } from "@playwright/test";

// The API + worker are started by scripts/e2e.sh (or must already be running on :8000 in test mode).
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  retries: 0,
  reporter: [["list"], ["json", { outputFile: "../../reports/web-e2e.json" }]],
  use: { baseURL: "http://localhost:3000", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
  webServer: {
    command: "pnpm dev",
    url: "http://localhost:3000",
    reuseExistingServer: true,
    timeout: 120_000,
    env: { API_INTERNAL_URL: process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000" },
  },
});
