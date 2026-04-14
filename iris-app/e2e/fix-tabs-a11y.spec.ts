import { test, expect } from '@playwright/test'
import { existsSync, rmSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

/**
 * A11y regression guard — custom <Tabs> implementation exposes proper ARIA:
 *   - TabsList → role="tablist"
 *   - TabsTrigger → role="tab", aria-selected, data-state, aria-controls, id
 *   - TabsContent → role="tabpanel", id, aria-labelledby, hidden-when-inactive
 *   - Arrow / Home / End keyboard navigation.
 *
 * Assumes dev stack is already running (Vite :4173, Express :4001, daemon
 * :4002). Uses HTTP to create a throwaway project so the workspace is
 * reachable.
 */
const PROJECT = 'fix-tabs-smoke'
const IRIS_ROOT = process.env.IRIS_ROOT || resolve(__dirname, '..', '..')
const PROJECT_DIR = resolve(IRIS_ROOT, 'projects', PROJECT)
const BASE = 'http://localhost:4001'
const EXPECTED_TAB_COUNT = 8

test.beforeAll(async ({ request }) => {
  await request.delete(`${BASE}/api/projects/${PROJECT}`).catch(() => {})
  if (existsSync(PROJECT_DIR)) rmSync(PROJECT_DIR, { recursive: true, force: true })
  const created = await request.post(`${BASE}/api/projects`, { data: { name: PROJECT } })
  expect(created.ok()).toBeTruthy()
  await request.post(`${BASE}/api/projects/active`, { data: { name: PROJECT } })
})

test.afterAll(async ({ request }) => {
  await request.delete(`${BASE}/api/projects/${PROJECT}`).catch(() => {})
  if (existsSync(PROJECT_DIR)) rmSync(PROJECT_DIR, { recursive: true, force: true })
})

test('workspace tabs expose tablist + tab roles and aria-selected', async ({ page }) => {
  await page.goto(`/project/${PROJECT}`)

  // Tablist resolves. (WorkspaceTabs is the outer workspace tablist; some
  // inner panels — MemoryInspector — render their own nested Tabs, so we
  // scope explicitly by tab count to identify the workspace tablist.)
  const tablist = page.getByRole('tablist').filter({ has: page.getByRole('tab', { name: /plots/i }) })
  await expect(tablist).toBeVisible()

  // 8 workspace tabs.
  const tabs = tablist.getByRole('tab')
  await expect(tabs).toHaveCount(EXPECTED_TAB_COUNT)

  // Exactly one is initially selected.
  const selected = tablist.locator('[role="tab"][aria-selected="true"]')
  await expect(selected).toHaveCount(1)

  // Click Memory tab → becomes selected, panel is tabpanel.
  const memoryTab = tablist.getByRole('tab', { name: /memory/i })
  await memoryTab.click()
  await expect(memoryTab).toHaveAttribute('aria-selected', 'true')
  await expect(memoryTab).toHaveAttribute('data-state', 'active')

  const panelId = await memoryTab.getAttribute('aria-controls')
  expect(panelId).toBe('panel-memory')
  const panel = page.locator(`#${panelId}`)
  await expect(panel).toBeVisible()
  await expect(panel).toHaveAttribute('role', 'tabpanel')
  await expect(panel).toHaveAttribute('aria-labelledby', 'tab-memory')

  // Only one aria-selected=true at a time.
  await expect(tablist.locator('[role="tab"][aria-selected="true"]')).toHaveCount(1)
})

test('arrow + End keyboard navigation moves selection', async ({ page }) => {
  await page.goto(`/project/${PROJECT}`)

  // Start on Plots (default tab).
  const plotsTab = page.getByRole('tab', { name: /plots/i })
  await plotsTab.focus()
  await expect(plotsTab).toBeFocused()

  // ArrowRight → next tab (Report) becomes selected.
  await page.keyboard.press('ArrowRight')
  const reportTab = page.getByRole('tab', { name: /report/i })
  await expect(reportTab).toHaveAttribute('aria-selected', 'true')

  // End → last tab (Runs) selected.
  await page.keyboard.press('End')
  const runsTab = page.getByRole('tab', { name: /runs/i })
  await expect(runsTab).toHaveAttribute('aria-selected', 'true')

  // Home → back to first (Plots).
  await page.keyboard.press('Home')
  await expect(plotsTab).toHaveAttribute('aria-selected', 'true')

  // ArrowLeft wraps to last (Runs).
  await page.keyboard.press('ArrowLeft')
  await expect(runsTab).toHaveAttribute('aria-selected', 'true')
})
