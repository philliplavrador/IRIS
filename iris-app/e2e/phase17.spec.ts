import { test, expect } from '@playwright/test'
import { existsSync, rmSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

/**
 * Phase 17 boundary (REVAMP Task 17.3) — retrieval metrics + v3 migration.
 *
 * A recall call against planted memories must produce a retrieval_events
 * row; /memory/metrics must expose it.
 */
const PROJECT = 'phase17-smoke'
const IRIS_ROOT = process.env.IRIS_ROOT || resolve(__dirname, '..', '..')
const PROJECT_DIR = resolve(IRIS_ROOT, 'projects', PROJECT)
const BASE = 'http://localhost:4001'

test.beforeAll(async ({ request }) => {
  await request.delete(`${BASE}/api/projects/${PROJECT}`).catch(() => {})
  if (existsSync(PROJECT_DIR))
    rmSync(PROJECT_DIR, { recursive: true, force: true })
})

test('phase 17 — recall updates metrics', async ({ request }) => {
  const created = await request.post(`${BASE}/api/projects`, {
    data: { name: PROJECT },
  })
  expect(created.ok()).toBeTruthy()
  await request.post(`${BASE}/api/projects/active`, {
    data: { name: PROJECT },
  })

  // Plant one draft memory and commit it.
  const proposed = await request.post(`${BASE}/api/memory/entries`, {
    data: {
      scope: 'project',
      memory_type: 'finding',
      text: 'bandpass filtered output is clean at 300 Hz',
      importance: 7,
    },
  })
  expect(proposed.ok()).toBeTruthy()
  const pid = (await proposed.json()).data?.memory_id
  const committed = await request.post(`${BASE}/api/memory/entries/commit`, {
    data: { ids: [pid] },
  })
  expect(committed.ok()).toBeTruthy()

  // Query — should hit and record a retrieval event.
  const recalled = await request.post(`${BASE}/api/memory/recall`, {
    data: { query: 'bandpass filtered output' },
  })
  expect(recalled.ok()).toBeTruthy()

  // Metrics endpoint now sees at least one retrieval.
  const metrics = await request.get(`${BASE}/api/memory/metrics`)
  expect(metrics.ok()).toBeTruthy()
  const data = (await metrics.json()).data
  expect(typeof data.usage_ratio).toBe('number')
  expect(data.retrieved_total).toBeGreaterThanOrEqual(1)

  await request.delete(`${BASE}/api/projects/${PROJECT}`)
})
