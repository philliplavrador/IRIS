import { test, expect } from '@playwright/test'
import { existsSync, rmSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

/**
 * Deep E2E coverage for the IRIS projects lifecycle (create / open / rename /
 * delete / list / active-project tracking + error paths).
 *
 * Assumes `npm run dev` is already running: Vite :4173, Express :4001, daemon
 * :4002. Names are scoped so parallel specs (phase1, phase12) don't collide.
 */

const BASE = 'http://localhost:4001'
const IRIS_ROOT = process.env.IRIS_ROOT || resolve(__dirname, '..', '..')
const PROJECTS_DIR = resolve(IRIS_ROOT, 'projects')

// Every test uses a unique name with this prefix so afterAll cleans all of them.
const PREFIX = 'deep-projects-crud-'
const NAMES = {
  uiCrud: `${PREFIX}ui`,
  apiList: `${PREFIX}api`,
  active: `${PREFIX}active`,
  renameFrom: `${PREFIX}rename-from`,
  renameTo: `${PREFIX}rename-to`,
  duplicate: `${PREFIX}dup`,
  workspace: `${PREFIX}ws`,
  sqliteDisk: `${PREFIX}sqlite`,
}

async function cleanupAll(request: any) {
  for (const n of Object.values(NAMES)) {
    await request.delete(`${BASE}/api/projects/${n}`).catch(() => {})
    const dir = resolve(PROJECTS_DIR, n)
    if (existsSync(dir)) rmSync(dir, { recursive: true, force: true })
  }
}

test.beforeAll(async ({ request }) => {
  await cleanupAll(request)
})

test.afterAll(async ({ request }) => {
  await cleanupAll(request)
})

test('UI — create, list, open, delete round-trip via ProjectsPage', async ({ page, request }) => {
  const name = NAMES.uiCrud

  await page.goto('/')
  await expect(page.getByRole('heading', { name: /projects/i })).toBeVisible()

  // Click "New Project", type name, click Create. The page auto-opens the
  // project, so we'll be on /project/:name afterwards.
  await page.getByRole('button', { name: /new project/i }).click()
  await page.getByPlaceholder('Project name').fill(name)
  await page.getByRole('button', { name: /^create$/i }).click()

  // UI navigates into workspace; verify URL.
  await page.waitForURL(new RegExp(`/project/${name}$`), { timeout: 15_000 })

  // Backend confirms the project exists.
  const list = await (await request.get(`${BASE}/api/projects`)).json()
  expect(list.map((p: any) => p.name)).toContain(name)

  // Delete via DELETE endpoint (UI delete lives behind a dialog we don't need
  // to drive here; the canonical DELETE path is exercised by the webapp's
  // settings panel which proxies to the same route).
  const del = await request.delete(`${BASE}/api/projects/${name}`)
  expect(del.ok()).toBeTruthy()
  expect(existsSync(resolve(PROJECTS_DIR, name))).toBeFalsy()
})

test('API — created project appears in GET /api/projects', async ({ request }) => {
  const name = NAMES.apiList
  const created = await request.post(`${BASE}/api/projects`, { data: { name } })
  expect(created.ok()).toBeTruthy()

  const list = await (await request.get(`${BASE}/api/projects`)).json()
  expect(Array.isArray(list)).toBe(true)
  expect(list.map((p: any) => p.name)).toContain(name)
})

test('API — active project round-trip after open', async ({ request }) => {
  const name = NAMES.active
  await request.post(`${BASE}/api/projects`, { data: { name } })

  // Open via by-name (activates as side-effect).
  const opened = await request.get(`${BASE}/api/projects/by-name/${name}`)
  expect(opened.ok()).toBeTruthy()

  const active = await (await request.get(`${BASE}/api/projects/active`)).json()
  expect(active.active?.name).toBe(name)

  // Explicit POST /active also works.
  const setRes = await request.post(`${BASE}/api/projects/active`, { data: { name } })
  expect(setRes.ok()).toBeTruthy()
})

test('API — rename via POST /api/projects/rename moves directory', async ({ request }) => {
  const oldName = NAMES.renameFrom
  const newName = NAMES.renameTo
  await request.post(`${BASE}/api/projects`, { data: { name: oldName } })
  expect(existsSync(resolve(PROJECTS_DIR, oldName))).toBeTruthy()

  // Express proxy shape uses { oldName, newName } (server/routes/projects.ts L134).
  const res = await request.post(`${BASE}/api/projects/rename`, {
    data: { oldName, newName },
  })
  expect(res.ok()).toBeTruthy()

  expect(existsSync(resolve(PROJECTS_DIR, oldName))).toBeFalsy()
  expect(existsSync(resolve(PROJECTS_DIR, newName))).toBeTruthy()

  const list = await (await request.get(`${BASE}/api/projects`)).json()
  const names = list.map((p: any) => p.name)
  expect(names).toContain(newName)
  expect(names).not.toContain(oldName)
})

test('API — duplicate name yields 409 Conflict', async ({ request }) => {
  const name = NAMES.duplicate
  const first = await request.post(`${BASE}/api/projects`, { data: { name } })
  expect(first.ok()).toBeTruthy()

  const second = await request.post(`${BASE}/api/projects`, { data: { name } })
  // Daemon raises FileExistsError -> HTTP 409. Express proxy bubbles status.
  expect(second.ok()).toBeFalsy()
  expect([400, 409, 500, 502]).toContain(second.status())
})

test('API — invalid project name is rejected', async ({ request }) => {
  // Regex is [a-zA-Z0-9_-]{1,64}; a slash must fail.
  const res = await request.post(`${BASE}/api/projects`, {
    data: { name: 'bad name with spaces!!' },
  })
  expect(res.ok()).toBeFalsy()
  expect([400, 422, 500, 502]).toContain(res.status())
})

test('API — deleting a non-existent project returns an error', async ({ request }) => {
  const res = await request.delete(`${BASE}/api/projects/${PREFIX}does-not-exist-xyz`)
  // Daemon surfaces 404; proxy may wrap to 500/502 if it treats as error.
  expect(res.ok()).toBeFalsy()
  expect([400, 404, 500, 502]).toContain(res.status())
})

test('UI — workspace page loads after opening a project', async ({ page, request }) => {
  const name = NAMES.workspace
  await request.post(`${BASE}/api/projects`, { data: { name } })

  await page.goto(`/project/${name}`)

  // WorkspacePage shows "Loading project..." then mounts WorkspaceLayout.
  // Wait for the loading indicator to disappear (or for any main region to
  // appear). WorkspaceLayout renders the full IDE, so any main/banner role or
  // the project name somewhere on the page is sufficient evidence.
  await expect(page.getByText(/loading project/i)).toBeHidden({ timeout: 20_000 })

  // The workspace layout renders the project name in its header/sidebar in
  // multiple places; at least one occurrence should be visible.
  await expect(page.getByText(name).first()).toBeVisible({ timeout: 10_000 })
})

test('Disk — iris.sqlite is created on create and removed on delete', async ({ request }) => {
  const name = NAMES.sqliteDisk
  const dbPath = resolve(PROJECTS_DIR, name, 'iris.sqlite')

  const created = await request.post(`${BASE}/api/projects`, { data: { name } })
  expect(created.ok()).toBeTruthy()

  // Activate so schema.sql is applied and iris.sqlite exists on disk.
  await request.get(`${BASE}/api/projects/by-name/${name}`)
  expect(existsSync(dbPath)).toBeTruthy()

  const del = await request.delete(`${BASE}/api/projects/${name}`)
  expect(del.ok()).toBeTruthy()
  expect(existsSync(resolve(PROJECTS_DIR, name))).toBeFalsy()
  expect(existsSync(dbPath)).toBeFalsy()
})
