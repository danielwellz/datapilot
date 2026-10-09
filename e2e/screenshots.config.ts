import { defineConfig, devices } from '@playwright/test';

// Captures the README's screenshots from a stack that is already up,
// ideally `make demo scale=full` so the numbers look like real data.
export default defineConfig({
  testDir: 'screenshots',
  retries: 0,
  reporter: 'list',
  timeout: 120_000,
  use: {
    baseURL: process.env['E2E_BASE_URL'] ?? 'http://localhost:8080',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
        // Charts draw their final frame at once instead of animating.
        reducedMotion: 'reduce',
      },
    },
  ],
});
