import { test, expect } from '@playwright/test'
import { existsSync, rmSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

/**
 * Phase 12 boundary (REVAMP Task 12.4) — pending drafts count.
 *
 * Pure HTTP check: proposing three draft memories increments the count
 * endpoint, committing one decrements it.
 */
const PROJECT = 'phase12-smoke'
const IRIS_ROOT = process.env.IRIS_ROOT || resolve(__dirname, '..', '..')
const PROJECT_DIR = resolve(IRIS_ROOT, 'projects', PROJECT)
const BASE = 'http://localhost:4001'

test.beforeAll(async ({ request }) => {
  await request.delete(`${BASE}/api/projects/${PROJECT}`).catch(() => {})
  if (existsSync(PROJECT_DIR))
    rmSync(PROJECT_DIR, { recursive: true, force: true })
})

test('phase 12 — pending drafts count reflects propose + commit', async ({
  request,
}) => {
  await request.post(`${BASE}/api/projects`, { data: { name: PROJECT } })
  await request.post(`${BASE}/api/projects/active`, {
    data: { name: PROJECT },
  })

  const start = (await (await request.get(`${BASE}/api/memory/pending/count`)).json())
    .data.count as number
  expect(start).toBe(0)

  const ids: string[] = []
  for (const text of [
    'bandpass analysis yields 300Hz noise floor',
    'channel 742 shows bursting around 12 minutes',
    'saturation threshold retuned to 0.85',
  ]) {
    const res = await request.post(`${BASE}/api/memory/entries`, {
      data: { scope: 'project', memory_type: 'finding', text, importance: 6 },
    })
    ids.push((await res.json()).data.memory_id)
  }

  const after = (await (await request.get(`${BASE}/api/memory/pending/count`)).json())
    .data.count as number
  expect(after).toBe(3)

  // Commit one — count drops to 2.
  await request.post(`${BASE}/api/memory/entries/commit`, {
    data: { ids: [ids[0]] },
  })
  const afterCommit = (await (await request.get(`${BASE}/api/memory/pending/count`)).json())
    .data.count as number
  expect(afterCommit).toBe(2)

  await request.delete(`${BASE}/api/projects/${PROJECT}`)
})
