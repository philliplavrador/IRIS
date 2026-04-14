import { defineConfig } from '@playwright/test'

/**
 * Playwright config for IRIS phase-boundary E2E specs.
 *
 * Tests assume `npm run dev` is already running (Vite on 4173, Express on
 * 4001, Python daemon on 4002). Each phase boundary contributes one spec
 * under `e2e/` — see REVAMP.md.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: 'http://localhost:4173',
    headless: true,
    trace: 'retain-on-failure',
  },
})
