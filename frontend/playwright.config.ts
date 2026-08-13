import { defineConfig, devices } from "@playwright/test";

const pythonExecutable = process.env.ATHAR_PYTHON || "python3";
const baseURL = process.env.PLAYWRIGHT_BASE_URL || "http://127.0.0.1:3000";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  // The smoke suite shares one Flask data process. More than two browser
  // workers can cold-build several Quran/waqf payloads at once and create
  // false timeouts locally, even though CI already runs with two.
  workers: 2,
  reporter: process.env.CI ? [["line"], ["html", {open: "never"}]] : "line",
  use: {
    baseURL,
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
      url: `${baseURL}/read?surah=2&ayah=255`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        ...process.env,
        PORT: new URL(baseURL).port || "3000",
        ATHAR_API_ORIGIN: "http://127.0.0.1:5001",
        NEXT_PUBLIC_LEGACY_APP_ORIGIN: "http://127.0.0.1:5001",
        NEXT_PUBLIC_SITE_URL: baseURL,
      },
    },
  ],
});
