import { test, expect } from '@playwright/test'
import { existsSync, rmSync, readdirSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

/**
 * Regression coverage for three Express proxy bugs:
 *
 *   - MED #3: POST /api/memory/regenerate_markdown was not proxied at all.
 *   - MED #5: GET /api/ops/{name} was not proxied at all.
 *   - LOW #7: daemon-client collapsed every non-2xx daemon response to 502,
 *     hiding the real 404 / 409 / 503 status.
 *
 * All three are fixed in the same patch that added `DaemonHTTPError` +
 * `forwardDaemonError`. These tests lock in the behavior.
 */

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

const BASE = 'http://127.0.0.1:4001'
const DAEMON = 'http://127.0.0.1:4002'
const PROJECT = 'fix-proxy-smoke'
const IRIS_ROOT = process.env.IRIS_ROOT || resolve(__dirname, '..', '..')
const PROJECT_DIR = resolve(IRIS_ROOT, 'projects', PROJECT)
const MEMORY_DIR = resolve(PROJECT_DIR, 'memory')

async function cleanup(request: any) {
  await request.delete(`${BASE}/api/projects/${PROJECT}`).catch(() => {})
  if (existsSync(PROJECT_DIR))
    rmSync(PROJECT_DIR, { recursive: true, force: true })
}

test.describe.configure({ mode: 'serial' })

test.beforeAll(async ({ request }) => {
  await cleanup(request)
  const created = await request.post(`${BASE}/api/projects`, {
    data: { name: PROJECT },
  })
  expect(created.ok(), 'create project').toBeTruthy()
  const activate = await request.post(`${BASE}/api/projects/active`, {
    data: { name: PROJECT },
  })
  expect(activate.ok(), 'activate project').toBeTruthy()
})

test.afterAll(async ({ request }) => {
  await cleanup(request)
})

// --- MED #5: /api/ops/:name is proxied ------------------------------------

test('GET /api/ops/butter_bandpass via Express matches daemon signature', async ({
  request,
}) => {
  const expressRes = await request.get(`${BASE}/api/ops/butter_bandpass`)
  expect(expressRes.status()).toBe(200)
  const expressBody = await expressRes.json()

  const daemonRes = await request.get(`${DAEMON}/api/ops/butter_bandpass`)
  expect(daemonRes.status()).toBe(200)
  const daemonBody = await daemonRes.json()

  expect(expressBody).toEqual(daemonBody)
  expect(expressBody.name).toBe('butter_bandpass')
  expect(Array.isArray(expressBody.transitions)).toBe(true)
  expect(expressBody.transitions.length).toBeGreaterThan(0)
})

// --- LOW #7: status-mapping fix (multiple routes) -------------------------

test('GET /api/ops/nonexistent_op_xyz returns 404 (not 502) with error body', async ({
  request,
}) => {
  const res = await request.get(`${BASE}/api/ops/nonexistent_op_xyz`)
  expect(res.status()).toBe(404)
  const body = await res.json()
  // Daemon uses FastAPI HTTPException -> { detail: "..." }. Our forwarder
  // passes the body through verbatim.
  expect(body).toHaveProperty('detail')
  expect(String(body.detail)).toContain('nonexistent_op_xyz')
})

test('DELETE /api/projects/does-not-exist returns daemon status (not 502)', async ({
  request,
}) => {
  const res = await request.delete(`${BASE}/api/projects/does-not-exist`)
  // The daemon returns 404 for an unknown project; assert exact.
  expect(res.status()).toBe(404)
  const body = await res.json()
  expect(body).toHaveProperty('detail')
})

test('GET /api/memory/sessions/nonexistent returns daemon status (not 502)', async ({
  request,
}) => {
  const res = await request.get(`${BASE}/api/memory/sessions/nonexistent`)
  // With an active project, daemon raises 404 for the missing session.
  expect(res.status()).toBe(404)
  const body = await res.json()
  expect(body).toHaveProperty('detail')
  expect(String(body.detail).toLowerCase()).toContain('nonexistent')
})

test('PATCH /api/memory/tool_calls/bogus/output_artifact returns daemon status (not 502)', async ({
  request,
}) => {
  const res = await request.patch(
    `${BASE}/api/memory/tool_calls/bogus/output_artifact`,
    { data: { artifact_id: 'sha256:doesnotexist' } },
  )
  // Daemon returns 404 when the tool_call row doesn't exist.
  expect(res.status()).toBe(404)
  expect(res.status()).not.toBe(502)
  const body = await res.json()
  expect(body).toHaveProperty('detail')
})

// --- MED #3: /api/memory/regenerate_markdown is proxied -------------------

test('POST /api/memory/regenerate_markdown proxies through and writes files to disk', async ({
  request,
}) => {
  // Seed one committed memory entry so there's something to regenerate.
  const prop = await request.post(`${BASE}/api/memory/entries`, {
    data: {
      scope: 'project',
      memory_type: 'finding',
      text: 'proxy regression seed',
      importance: 5,
    },
  })
  expect(prop.ok(), 'propose entry').toBeTruthy()
  const id = (await prop.json()).data.memory_id as string

  const committed = await request.post(`${BASE}/api/memory/entries/commit`, {
    data: { ids: [id] },
  })
  expect(committed.ok(), 'commit entry').toBeTruthy()

  // Wipe the memory/ dir then trigger regeneration through Express.
  if (existsSync(MEMORY_DIR))
    rmSync(MEMORY_DIR, { recursive: true, force: true })

  const regen = await request.post(`${BASE}/api/memory/regenerate_markdown`, {
    data: {},
  })
  expect(regen.status()).toBe(200)
  expect(regen.status()).not.toBe(404) // <- the MED #3 regression
  const body = await regen.json()
  expect(body?.data?.ok).toBe(true)

  // Verify Markdown files exist on disk.
  expect(existsSync(MEMORY_DIR)).toBe(true)
  const files = readdirSync(MEMORY_DIR)
  expect(files.some((f) => f.endsWith('.md'))).toBe(true)
})
