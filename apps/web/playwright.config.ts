import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

const apiDirectory = path.resolve(__dirname, "../api");
const python = process.env.PYTHON || (process.platform === "win32"
  ? path.join(apiDirectory, ".venv", "Scripts", "python.exe")
  : "python");

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: { timeout: 8_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["html", { open: "never" }], ["github"]] : "list",
  use: {
    baseURL: "http://localhost:3100",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: process.env.PW_EXTERNAL === "1" ? undefined : [
    {
      command: `"${python}" -m alembic upgrade head && "${python}" -m app.seed && "${python}" -m uvicorn app.main:app --host 127.0.0.1 --port 8100`,
      cwd: apiDirectory,
      url: "http://127.0.0.1:8100/health",
      reuseExistingServer: process.env.PW_REUSE === "1",
      timeout: 120_000,
      gracefulShutdown: { signal: "SIGINT", timeout: 2_000 },
      env: {
        DATABASE_URL: "sqlite+aiosqlite:///./playwright.db",
        JWT_SECRET: "playwright-only-secret-not-for-production",
        CORS_ORIGINS: "http://localhost:3100",
        LLM_PROVIDER: "mock",
        XIANYU_RUNTIME_MODE: "embedded",
      },
    },
    {
      command: "pnpm dev --hostname 127.0.0.1 --port 3100",
      cwd: __dirname,
      url: "http://localhost:3100/login",
      reuseExistingServer: process.env.PW_REUSE === "1",
      timeout: 120_000,
      gracefulShutdown: { signal: "SIGINT", timeout: 2_000 },
      env: { NEXT_PUBLIC_API_URL: "http://localhost:8100" },
    },
  ],
});
