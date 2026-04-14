import { test, expect } from '@playwright/test'
import { existsSync, rmSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

/**
 * Phase 2 boundary smoke test (REVAMP Task 2.5).
 *
 * Goal: a chat turn in a fresh project must open a memory-layer session
 * (writing exactly one `session_started` event). A second conversation —
 * simulated by ending the first session and starting another — must write a
 * second `session_started` event. Uses the HTTP surface directly rather than
 * driving the UI so the test does not depend on the Claude Max subscription.
 *
 *   1. Create "phase2-smoke".
 *   2. Activate it.
 *   3. POST /memory/sessions/start — expect one `session_started` event.
 *   4. POST /memory/sessions/<id>/end.
 *   5. POST /memory/sessions/start again — expect a second `session_started`.
 *   6. Delete the project.
 *
 * Assumes `npm run dev` is running (server :4001, daemon :4002, vite :4173).
 */
const PROJECT = 'phase2-smoke'
const IRIS_ROOT = process.env.IRIS_ROOT || resolve(__dirname, '..', '..')
const PROJECT_DIR = resolve(IRIS_ROOT, 'projects', PROJECT)
const BASE = 'http://localhost:4001'

test.beforeAll(async ({ request }) => {
  await request.delete(`${BASE}/api/projects/${PROJECT}`).catch(() => {})
  if (existsSync(PROJECT_DIR)) rmSync(PROJECT_DIR, { recursive: true, force: true })
})

test('phase 2 — session lifecycle writes session_started events', async ({ request }) => {
  // Step 1 — create + open.
  const created = await request.post(`${BASE}/api/projects`, { data: { name: PROJECT } })
  expect(created.ok()).toBeTruthy()

  const activated = await request.post(`${BASE}/api/projects/active`, { data: { name: PROJECT } })
  expect(activated.ok()).toBeTruthy()

  // Step 2 — open first memory session.
  const start1 = await request.post(`${BASE}/api/memory/sessions/start`, {
    data: {
      model_provider: 'anthropic',
      model_name: 'claude-sonnet-4-5',
      system_prompt: 'phase2 smoke test session 1',
    },
  })
  expect(start1.ok()).toBeTruthy()
  const body1 = await start1.json()
  const sid1 = body1.data?.session_id
  expect(typeof sid1).toBe('string')

  // Assert exactly one session_started event.
  const afterStart1 = await request.get(`${BASE}/api/memory/events?type=session_started`)
  expect(afterStart1.ok()).toBeTruthy()
  const events1 = (await afterStart1.json()).data
  expect(events1).toHaveLength(1)
  expect(events1[0].session_id).toBe(sid1)

  // Step 3 — end session 1.
  const end1 = await request.post(
    `${BASE}/api/memory/sessions/${encodeURIComponent(sid1)}/end`,
    { data: { summary: 'phase2 smoke — session 1 done' } },
  )
  expect(end1.ok()).toBeTruthy()

  // Step 4 — open second memory session. This is the "restart daemon + new
  // conversation" analog: from the memory layer's POV, what matters is that
  // a fresh start_session call writes another session_started event.
  const start2 = await request.post(`${BASE}/api/memory/sessions/start`, {
    data: {
      model_provider: 'anthropic',
      model_name: 'claude-sonnet-4-5',
      system_prompt: 'phase2 smoke test session 2',
    },
  })
  expect(start2.ok()).toBeTruthy()
  const sid2 = (await start2.json()).data?.session_id
  expect(typeof sid2).toBe('string')
  expect(sid2).not.toBe(sid1)

  // Assert a second session_started event now exists.
  const afterStart2 = await request.get(`${BASE}/api/memory/events?type=session_started`)
  const events2 = (await afterStart2.json()).data
  expect(events2).toHaveLength(2)
  const sids = events2.map((e: any) => e.session_id).sort()
  expect(sids).toEqual([sid1, sid2].sort())

  // Step 5 — delete project (cleans the db + project dir).
  const deleted = await request.delete(`${BASE}/api/projects/${PROJECT}`)
  expect(deleted.ok()).toBeTruthy()
  expect(existsSync(PROJECT_DIR)).toBeFalsy()
})
