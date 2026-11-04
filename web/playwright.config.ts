import { defineConfig, devices } from '@playwright/test'

if (process.env.TEXA_E2E_TEST_DSN !== '1') {
  throw new Error('E2E is restricted to the isolated test database. Set TEXA_E2E_TEST_DSN=1 only for that environment.')
}

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: [['list']],
  outputDir: '../.runtime/e2e-artifacts',
  use: {
    baseURL: process.env.TEXA_E2E_BASE_URL ?? 'http://127.0.0.1:15174',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    ...devices['Desktop Chrome'],
  },
  webServer: [
    {
      command: 'uv run --directory ../backend uvicorn tests.e2e_server:app --host 127.0.0.1 --port 18001',
      url: 'http://127.0.0.1:18001/api/bootstrap',
      env: {
        TEXA_E2E_TEST_DSN: '1',
        TEXA_SHARED_DEMO: '1',
        TEXA_ADMIN_TOKEN: 'e2e-only-admin-token-not-a-secret-12345',
        TEXA_COOKIE_SECURE: '0',
      },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1',
      url: process.env.TEXA_E2E_BASE_URL ?? 'http://127.0.0.1:15174',
      env: { TEXA_WEB_PORT: '15174', TEXA_API_TARGET: 'http://127.0.0.1:18001' },
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
})
