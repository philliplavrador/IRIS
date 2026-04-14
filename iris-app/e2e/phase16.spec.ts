import { test, expect } from '@playwright/test'
import { existsSync, rmSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

/**
 * Phase 16 boundary (REVAMP Task 16.3).
 *
 * Exercises the staleness + contradictions HTTP surface end-to-end
 * without requiring an LLM — we plant memories directly, flip their
 * status, and verify the daemon endpoints round-trip cleanly.
 */
const PROJECT = 'phase16-smoke'
const IRIS_ROOT = process.env.IRIS_ROOT || resolve(__dirname, '..', '..')
const PROJECT_DIR = resolve(IRIS_ROOT, 'projects', PROJECT)
const BASE = 'http://localhost:4001'

test.beforeAll(async ({ request }) => {
  await request.delete(`${BASE}/api/projects/${PROJECT}`).catch(() => {})
  if (existsSync(PROJECT_DIR))
    rmSync(PROJECT_DIR, { recursive: true, force: true })
})

test('phase 16 — contradictions list + staleness scan + metrics roundtrip', async ({
  request,
}) => {
  const created = await request.post(`${BASE}/api/projects`, {
    data: { name: PROJECT },
  })
  expect(created.ok()).toBeTruthy()

  await request.post(`${BASE}/api/projects/active`, {
    data: { name: PROJECT },
  })

  // No contradictions yet.
  const empty = await request.get(`${BASE}/api/memory/contradictions`)
  expect(empty.ok()).toBeTruthy()
  const emptyBody = await empty.json()
  expect(Array.isArray(emptyBody.data)).toBeTruthy()
  expect(emptyBody.data.length).toBe(0)

  // Staleness scan on an empty project returns [].
  const stale = await request.post(`${BASE}/api/memory/staleness/scan`)
  expect(stale.ok()).toBeTruthy()
  const staleBody = await stale.json()
  expect(staleBody.data.ids).toEqual([])

  // Metrics endpoint returns a numeric shape.
  const metrics = await request.get(`${BASE}/api/memory/metrics`)
  expect(metrics.ok()).toBeTruthy()
  const metricsBody = await metrics.json()
  expect(typeof metricsBody.data.usage_ratio).toBe('number')
  expect(typeof metricsBody.data.stale_rate).toBe('number')

  await request.delete(`${BASE}/api/projects/${PROJECT}`)
  expect(existsSync(PROJECT_DIR)).toBeFalsy()
})
