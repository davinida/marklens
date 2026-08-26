import { defineConfig } from "@playwright/test";

const configuredPort = process.env.MARKLENS_E2E_PORT ?? "3107";
if (!/^\d{2,5}$/.test(configuredPort)) {
  throw new Error("MARKLENS_E2E_PORT must be a valid TCP port");
}
const port = Number(configuredPort);
if (port < 1024 || port > 65_535) {
  throw new Error("MARKLENS_E2E_PORT must be between 1024 and 65535");
}

const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "./e2e",
  outputDir: "test-results",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  timeout: 30_000,
  reporter: process.env.CI
    ? [["github"], ["html", { open: "never" }]]
    : [["line"], ["html", { open: "never" }]],
  use: {
    baseURL,
    actionTimeout: 10_000,
    navigationTimeout: 30_000,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure",
  },
  webServer: {
    command: `node node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port ${port}`,
    url: baseURL,
    reuseExistingServer: process.env.MARKLENS_E2E_REUSE_SERVER === "1",
    timeout: 120_000,
    env: {
      MARKLENS_TURNSTILE_DEV_BYPASS: "1",
    },
  },
  projects: [
    {
      name: "chromium-320x568",
      use: {
        browserName: "chromium",
        viewport: { width: 320, height: 568 },
        isMobile: true,
        hasTouch: true,
      },
    },
    {
      name: "chromium-667x375",
      use: {
        browserName: "chromium",
        viewport: { width: 667, height: 375 },
        isMobile: true,
        hasTouch: true,
      },
    },
    {
      name: "chromium-desktop",
      use: { browserName: "chromium", viewport: { width: 1280, height: 800 } },
    },
  ],
});
