import { test, expect } from '@playwright/test'
import { existsSync, rmSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

/**
 * Regression E2E for the MemoryInspector/CurationRitual empty-list bug.
 *
 * Root cause: api.listMemoryEntries normalized `data.entries ?? data.rows`
 * but the daemon returns `{data: [...]}`. This spec proposes entries via
 * the API and asserts they render in the Memory and Curate tabs.
 */
const BASE = 'http://127.0.0.1:4001'
const PROJECT = 'fix-memory-ui-smoke'
const IRIS_ROOT = process.env.IRIS_ROOT || resolve(__dirname, '..', '..')
const PROJECT_DIR = resolve(IRIS_ROOT, 'projects', PROJECT)

async function cleanup(request: any) {
  await request.delete(`${BASE}/api/projects/${PROJECT}`).catch(() => {})
  if (existsSync(PROJECT_DIR))
    rmSync(PROJECT_DIR, { recursive: true, force: true })
}

async function propose(
  request: any,
  memory_type: string,
  text: string,
): Promise<string> {
  const res = await request.post(`${BASE}/api/memory/entries`, {
    data: { scope: 'project', memory_type, text, importance: 6 },
  })
  expect(res.ok()).toBeTruthy()
  const body = await res.json()
  return body?.data?.memory_id as string
}

async function pendingCount(request: any): Promise<number> {
  const res = await request.get(`${BASE}/api/memory/pending/count`)
  expect(res.ok()).toBeTruthy()
  return (await res.json()).data.count as number
}

test.describe.configure({ mode: 'serial' })

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

const ids: Record<string, string> = {}

test('propose 3 entries via API, commit 1 so it shows up on Findings tab', async ({
  request,
}) => {
  ids.finding1 = await propose(
    request,
    'finding',
    'unique-finding-ALPHA-visible-in-memory-tab',
  )
  ids.finding2 = await propose(
    request,
    'finding',
    'another pending finding beta',
  )
  ids.openQ = await propose(
    request,
    'open_question',
    'why does channel 7 drift?',
  )

  expect(await pendingCount(request)).toBe(3)

  // Commit finding1 so it becomes active and renders in the default Memory tab.
  const commit = await request.post(`${BASE}/api/memory/entries/commit`, {
    data: { ids: [ids.finding1] },
  })
  expect(commit.ok()).toBeTruthy()
  expect(await pendingCount(request)).toBe(2)
})

test('Memory Inspector renders committed findings (bug fix)', async ({
  page,
  request,
}) => {
  await request.post(`${BASE}/api/projects/active`, {
    data: { name: PROJECT },
  })
  await page.goto(`/project/${PROJECT}`)
  await expect(page.getByText(/loading project/i)).toBeHidden({
    timeout: 20_000,
  })

  const memoryTab = page.getByRole('tab', { name: 'Memory', exact: true })
  await memoryTab.waitFor({ state: 'visible', timeout: 20_000 })
  await memoryTab.click()

  // Findings sub-tab is the default. The committed entry must render.
  await expect(
    page.getByText(/unique-finding-ALPHA-visible-in-memory-tab/i).first(),
  ).toBeVisible({ timeout: 15_000 })
})

test('Curate tab shows correct pending count matching the API', async ({
  page,
  request,
}) => {
  const pending = await pendingCount(request)
  expect(pending).toBe(2)

  await page.goto(`/project/${PROJECT}`)
  await expect(page.getByText(/loading project/i)).toBeHidden({
    timeout: 20_000,
  })
  const curateTab = page.getByRole('tab', { name: 'Curate', exact: true })
  await curateTab.waitFor({ state: 'visible', timeout: 20_000 })
  await curateTab.click()

  // Header shows "<N> drafts" matching server truth (not 0).
  await expect(
    page.getByText(new RegExp(`^${pending} drafts?$`)).first(),
  ).toBeVisible({ timeout: 15_000 })

  // The draft entry text should also render.
  await expect(
    page.getByText(/another pending finding beta/i).first(),
  ).toBeVisible({ timeout: 15_000 })
})

test('after committing a draft, Curate list decrements', async ({
  page,
  request,
}) => {
  // Commit the remaining draft finding via API, then reload the Curate tab.
  const commit = await request.post(`${BASE}/api/memory/entries/commit`, {
    data: { ids: [ids.finding2] },
  })
  expect(commit.ok()).toBeTruthy()

  const pendingAfter = await pendingCount(request)
  expect(pendingAfter).toBe(1) // only the open_question is left

  await page.goto(`/project/${PROJECT}`)
  await expect(page.getByText(/loading project/i)).toBeHidden({
    timeout: 20_000,
  })
  const curateTab = page.getByRole('tab', { name: 'Curate', exact: true })
  await curateTab.waitFor({ state: 'visible', timeout: 20_000 })
  await curateTab.click()

  await expect(
    page.getByText(new RegExp(`^${pendingAfter} drafts?$`)).first(),
  ).toBeVisible({ timeout: 15_000 })

  // The previously-pending finding must no longer be listed as a draft.
  await expect(
    page.getByText(/another pending finding beta/i),
  ).toHaveCount(0, { timeout: 10_000 })
})
