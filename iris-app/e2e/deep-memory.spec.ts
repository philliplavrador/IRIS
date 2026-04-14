import { test, expect } from '@playwright/test'
import { existsSync, rmSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

/**
 * Deep E2E coverage for the memory layer (propose → commit/discard/supersede,
 * markdown regeneration, contradictions, staleness, curation UI).
 *
 * Uses 127.0.0.1 explicitly — on Windows, localhost sometimes resolves to ::1
 * first and the Express server binds to IPv4 only.
 */
const BASE = 'http://127.0.0.1:4001'
const DAEMON = 'http://127.0.0.1:4002'
const PROJECT = 'deep-memory-smoke'
const IRIS_ROOT = process.env.IRIS_ROOT || resolve(__dirname, '..', '..')
const PROJECT_DIR = resolve(IRIS_ROOT, 'projects', PROJECT)
const MEMORY_DIR = resolve(PROJECT_DIR, 'memory')

async function cleanup(request: any) {
  await request.delete(`${BASE}/api/projects/${PROJECT}`).catch(() => {})
  if (existsSync(PROJECT_DIR))
    rmSync(PROJECT_DIR, { recursive: true, force: true })
}

async function propose(
  request: any,
  memory_type: string,
  text: string,
  importance = 6,
): Promise<string> {
  const res = await request.post(`${BASE}/api/memory/entries`, {
    data: { scope: 'project', memory_type, text, importance },
  })
  expect(res.ok(), `propose ${memory_type} should succeed`).toBeTruthy()
  const body = await res.json()
  const id = body?.data?.memory_id
  expect(typeof id).toBe('string')
  return id as string
}

async function pendingCount(request: any): Promise<number> {
  const res = await request.get(`${BASE}/api/memory/pending/count`)
  expect(res.ok()).toBeTruthy()
  return (await res.json()).data.count as number
}

test.beforeAll(async ({ request }) => {
  await cleanup(request)
  const created = await request.post(`${BASE}/api/projects`, {
    data: { name: PROJECT },
  })
  expect(created.ok()).toBeTruthy()
  await request.post(`${BASE}/api/projects/active`, {
    data: { name: PROJECT },
  })
})

test.afterAll(async ({ request }) => {
  await cleanup(request)
})

// Module-scoped IDs — tests are serial by default in a single spec, and we
// rely on test order here (spec describes the propose→commit→discard→supersede
// flow as a narrative).
const ids: Record<string, string> = {}

test.describe.configure({ mode: 'serial' })

test('1. propose 5 entries of different types → pending count = 5', async ({
  request,
}) => {
  const start = await pendingCount(request)
  expect(start).toBe(0)

  ids.finding = await propose(request, 'finding', 'bandpass reveals 120Hz hum')
  ids.decision = await propose(
    request,
    'decision',
    'use 4th-order Butterworth by default',
  )
  ids.open_q = await propose(
    request,
    'open_question',
    'why does ch 17 saturate intermittently?',
  )
  ids.caveat = await propose(
    request,
    'caveat',
    'sampling rate drifts by ~0.2% between sessions',
  )
  ids.preference = await propose(
    request,
    'preference',
    'prefer PNG over SVG for report figures',
  )

  expect(await pendingCount(request)).toBe(5)
})

test('2. commit 2 → pending=3, those rows now status=committed/active', async ({
  request,
}) => {
  const toCommit = [ids.finding, ids.decision]
  const res = await request.post(`${BASE}/api/memory/entries/commit`, {
    data: { ids: toCommit },
  })
  expect(res.ok()).toBeTruthy()
  const body = await res.json()
  expect(body?.data?.committed).toEqual(toCommit)

  expect(await pendingCount(request)).toBe(3)

  // Verify status flipped (post-commit status per memory_entries.commit_pending
  // is 'active' in the new layer, not literally 'committed').
  for (const id of toCommit) {
    const r = await request.get(`${BASE}/api/memory/entries/${id}`)
    expect(r.ok()).toBeTruthy()
    const row = (await r.json()).data
    expect(row.status).not.toBe('draft')
    expect(['active', 'committed']).toContain(row.status)
  }
})

test('3. discard 1 → pending=2, row is gone (hard delete)', async ({
  request,
}) => {
  const res = await request.post(`${BASE}/api/memory/entries/discard`, {
    data: { ids: [ids.preference] },
  })
  expect(res.ok()).toBeTruthy()
  const body = await res.json()
  expect(body?.data?.discarded).toEqual([ids.preference])

  expect(await pendingCount(request)).toBe(2)

  // discard_pending is a hard delete — fetching now returns the daemon's
  // real 404 (LOW #7 fix: Express no longer collapses daemon errors to 502).
  const getRes = await request.get(
    `${BASE}/api/memory/entries/${ids.preference}`,
  )
  expect(getRes.ok()).toBeFalsy()
  expect(getRes.status()).toBe(404)
})

test('4. supersede: new→old link present on old row', async ({ request }) => {
  // Commit the old one first so it's not a draft.
  await request.post(`${BASE}/api/memory/entries/commit`, {
    data: { ids: [ids.caveat] },
  })

  // Propose a replacement and commit it.
  const newId = await propose(
    request,
    'caveat',
    'sampling rate drifts up to ~0.5% across sessions (revised)',
  )
  await request.post(`${BASE}/api/memory/entries/commit`, {
    data: { ids: [newId] },
  })

  const sup = await request.post(`${BASE}/api/memory/entries/supersede`, {
    data: { old_id: ids.caveat, new_id: newId },
  })
  expect(sup.ok()).toBeTruthy()
  const supBody = await sup.json()
  expect(supBody?.data?.old_id).toBe(ids.caveat)
  expect(supBody?.data?.new_id).toBe(newId)

  const oldRowRes = await request.get(
    `${BASE}/api/memory/entries/${ids.caveat}`,
  )
  expect(oldRowRes.ok()).toBeTruthy()
  const oldRow = (await oldRowRes.json()).data
  expect(oldRow.superseded_by).toBe(newId)
  expect(oldRow.status).toBe('superseded')

  ids.caveatNew = newId
})

test('5. regenerate_markdown writes memory/*.md files on disk', async ({
  request,
}) => {
  // BUG: Express proxy does not expose /api/memory/regenerate_markdown
  // (server/routes/memory.ts has no handler). Hit the daemon directly to
  // still exercise the documented endpoint contract.
  const res = await request.post(
    `${DAEMON}/api/memory/regenerate_markdown`,
  )
  expect(res.ok()).toBeTruthy()
  const body = await res.json()
  expect(body?.data?.ok).toBe(true)

  expect(existsSync(MEMORY_DIR)).toBeTruthy()
  // At least one .md file should exist under projects/<name>/memory/.
  const fs = await import('fs')
  const mdFiles = fs
    .readdirSync(MEMORY_DIR)
    .filter((f) => f.endsWith('.md'))
  expect(mdFiles.length).toBeGreaterThan(0)
})

test('6. contradictions list returns array', async ({ request }) => {
  const res = await request.get(`${BASE}/api/memory/contradictions`)
  expect(res.ok()).toBeTruthy()
  const body = await res.json()
  expect(Array.isArray(body.data)).toBe(true)
})

test('7. staleness scan returns data without error', async ({ request }) => {
  const res = await request.post(`${BASE}/api/memory/staleness/scan`)
  expect(res.ok()).toBeTruthy()
  const body = await res.json()
  expect(Array.isArray(body?.data?.ids)).toBe(true)
})

test('8. UI — Memory tab renders entry text', async ({ page, request }) => {
  // Make sure at least one ACTIVE finding exists (test 2 committed one) and
  // that the workspace has time to load. We also re-activate the project just
  // in case another suite grabbed it.
  await request.post(`${BASE}/api/projects/active`, {
    data: { name: PROJECT },
  })

  await page.goto(`/project/${PROJECT}`)
  await expect(page.getByText(/loading project/i)).toBeHidden({
    timeout: 20_000,
  })

  // Click the Memory tab (labelled "Memory" per WorkspaceTabs.tsx).
  // Radix Tabs triggers surface as role=button in the a11y tree under this
  // theme's shadcn wrapper. Match on visible tab label.
  const memoryTab = page.getByRole('tab', { name: 'Memory', exact: true })
  await memoryTab.waitFor({ state: 'visible', timeout: 20_000 })
  await memoryTab.click()

  // Post-fix: api.listMemoryEntries normalizes `data.data ?? data.entries
  // ?? data.rows`, so the committed finding from test 2 must be visible on
  // the Findings sub-tab (the default).
  await expect(
    page.getByRole('tab', { name: 'Findings', exact: true }),
  ).toBeVisible({ timeout: 20_000 })

  await expect(
    page.getByText(/bandpass reveals 120Hz hum/i).first(),
  ).toBeVisible({ timeout: 15_000 })
})

test('9. UI — Curate tab shows pending count (draft list)', async ({
  page,
  request,
}) => {
  // Snapshot server-truth pending count; Curation lists draft entries.
  const pending = await pendingCount(request)

  await page.goto(`/project/${PROJECT}`)
  await expect(page.getByText(/loading project/i)).toBeHidden({
    timeout: 20_000,
  })
  const curateTab = page.getByRole('tab', { name: 'Curate', exact: true })
  await curateTab.waitFor({ state: 'visible', timeout: 20_000 })
  await curateTab.click()

  // Post-fix: CurationRitual header should render "<server pending> drafts".
  await expect(
    page.getByText(new RegExp(`^${pending} drafts?$`)).first(),
  ).toBeVisible({ timeout: 15_000 })
})
