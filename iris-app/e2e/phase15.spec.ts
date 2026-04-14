import { test, expect } from '@playwright/test'
import { existsSync, rmSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

/**
 * Phase 15 boundary (REVAMP Task 15.4) — generated-op pipeline.
 *
 * Exercises /memory/operations/propose → /memory/operations/{id}/validate
 * with a trivial op that doubles its input.
 */
const PROJECT = 'phase15-smoke'
const IRIS_ROOT = process.env.IRIS_ROOT || resolve(__dirname, '..', '..')
const PROJECT_DIR = resolve(IRIS_ROOT, 'projects', PROJECT)
const BASE = 'http://localhost:4001'

test.beforeAll(async ({ request }) => {
  await request.delete(`${BASE}/api/projects/${PROJECT}`).catch(() => {})
  if (existsSync(PROJECT_DIR))
    rmSync(PROJECT_DIR, { recursive: true, force: true })
})

test('phase 15 — propose + validate generated op', async ({ request }) => {
  const created = await request.post(`${BASE}/api/projects`, {
    data: { name: PROJECT },
  })
  expect(created.ok()).toBeTruthy()
  await request.post(`${BASE}/api/projects/active`, {
    data: { name: PROJECT },
  })

  const proposed = await request.post(
    `${BASE}/api/memory/operations/propose`,
    {
      data: {
        name: 'doubler',
        version: '0.1.0',
        description: 'Double the input',
        code: 'def run(x):\n    return x * 2\n',
        signature_json: { input: 'number', output: 'number' },
      },
    },
  )
  expect(proposed.ok()).toBeTruthy()
  const proposedBody = await proposed.json()
  const opId = proposedBody.data?.op_id
  expect(typeof opId).toBe('string')

  // Proposed op file landed on disk.
  expect(
    existsSync(resolve(PROJECT_DIR, 'ops', 'doubler', 'v0.1.0', 'op.py')),
  ).toBeTruthy()

  const validated = await request.post(
    `${BASE}/api/memory/operations/${opId}/validate`,
    { data: { sample_input: 3 } },
  )
  expect(validated.ok()).toBeTruthy()
  const result = (await validated.json()).data
  expect(result).toBeTruthy()

  await request.delete(`${BASE}/api/projects/${PROJECT}`)
})
