import { test, expect } from '@playwright/test'
import { existsSync, rmSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

/**
 * Phase 1 boundary smoke test (REVAMP Task 1.10).
 *
 * Walks the project lifecycle end-to-end through the new Express -> daemon
 * proxy stack:
 *   1. Visit the projects page.
 *   2. Create "phase1-smoke".
 *   3. Open it (activates as a side-effect).
 *   4. Assert `projects/phase1-smoke/iris.sqlite` exists on disk.
 *   5. Delete the project via the canonical DELETE endpoint.
 *
 * Assumes `npm run dev` is running (server :4001, daemon :4002, vite :4173).
 */
const PROJECT = 'phase1-smoke'
const IRIS_ROOT = process.env.IRIS_ROOT || resolve(__dirname, '..', '..')
const PROJECT_DIR = resolve(IRIS_ROOT, 'projects', PROJECT)

test.beforeAll(async ({ request }) => {
  // Belt-and-braces cleanup in case a previous run died mid-flight.
  await request.delete(`http://localhost:4001/api/projects/${PROJECT}`).catch(() => {})
  if (existsSync(PROJECT_DIR)) rmSync(PROJECT_DIR, { recursive: true, force: true })
})

test('phase 1 — create / open / verify db / delete', async ({ page, request }) => {
  // Step 1 — projects page renders.
  await page.goto('/')
  await expect(page.getByRole('heading', { name: /projects/i })).toBeVisible()

  // Step 2 — create via canonical POST /api/projects.
  const created = await request.post('http://localhost:4001/api/projects', {
    data: { name: PROJECT },
  })
  expect(created.ok()).toBeTruthy()
  const createdInfo = await created.json()
  expect(createdInfo.name).toBe(PROJECT)

  // Step 3 — open (activates).
  const opened = await request.get(`http://localhost:4001/api/projects/by-name/${PROJECT}`)
  expect(opened.ok()).toBeTruthy()

  // Step 4 — `iris.sqlite` exists on disk.
  expect(existsSync(resolve(PROJECT_DIR, 'iris.sqlite'))).toBeTruthy()

  // Active project round-trip.
  const active = await request.get('http://localhost:4001/api/projects/active')
  expect(active.ok()).toBeTruthy()
  const activeBody = await active.json()
  expect(activeBody.active?.name).toBe(PROJECT)

  // Step 5 — delete via canonical DELETE.
  const deleted = await request.delete(`http://localhost:4001/api/projects/${PROJECT}`)
  expect(deleted.ok()).toBeTruthy()
  expect(existsSync(PROJECT_DIR)).toBeFalsy()
})
