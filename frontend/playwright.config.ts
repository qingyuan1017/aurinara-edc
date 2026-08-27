import { defineConfig, devices } from '@playwright/test'

/**
 * Playwright configuration for Clinical EDC System E2E tests.
 *
 * Runs against the Vite dev server at http://localhost:5173.
 * Expects the full stack (frontend + backend + database) to be running.
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false, // Clinical flows are sequential and stateful
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1, // Single worker for ordered clinical workflow tests
  reporter: [['html', { open: 'never' }], ['list']],
  timeout: 60_000, // Clinical flows may involve multiple page navigations

  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  /* Optionally start the Vite dev server before running tests */
  webServer: process.env.CI
    ? {
        command: 'npm run preview',
        port: 4173,
        reuseExistingServer: false,
      }
    : undefined,
})
