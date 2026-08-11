import { defineConfig, devices } from "@playwright/test";

const pythonExecutable = process.env.ATHAR_PYTHON || "python3";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI ? [["line"], ["html", {open: "never"}]] : "line",
  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {name: "desktop", use: {...devices["Desktop Chrome"]}},
    {name: "mobile", use: {...devices["Pixel 7"]}},
  ],
  webServer: [
    {
      command: `${pythonExecutable} app.py`,
      cwd: "..",
      url: "http://127.0.0.1:5001/api/surahs",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        ...process.env,
        ENABLE_EDITOR: "0",
      },
    },
    {
      command: "npm run start",
      cwd: ".",
      url: "http://127.0.0.1:3000/read?surah=2&ayah=255",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        ...process.env,
        ATHAR_API_ORIGIN: "http://127.0.0.1:5001",
        NEXT_PUBLIC_LEGACY_APP_ORIGIN: "http://127.0.0.1:5001",
        NEXT_PUBLIC_SITE_URL: "http://127.0.0.1:3000",
      },
    },
  ],
});
