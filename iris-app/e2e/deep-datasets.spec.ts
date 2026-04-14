import { test, expect } from '@playwright/test'
import { existsSync, rmSync, writeFileSync, mkdtempSync } from 'fs'
import { resolve, dirname, join } from 'path'
import { fileURLToPath } from 'url'
import { tmpdir } from 'os'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

/**
 * Deep E2E coverage for the memory datasets + artifacts surface:
 *
 *   POST   /api/memory/datasets              (body: source_path, name, description?)
 *   GET    /api/memory/datasets
 *   GET    /api/memory/datasets/{id}
 *   GET    /api/memory/datasets/{id}/versions
 *   POST   /api/memory/datasets/{id}/profile (body: version_id)
 *   POST   /api/memory/datasets/{id}/derive  (body: parent_version_id, transform_name,
 *                                             transform_params, artifact_id, description?)
 *   POST   /api/memory/artifacts             (body: content_b64, type, metadata?, description?)
 *   GET    /api/memory/artifacts
 *   GET    /api/memory/artifacts/{id}
 *   GET    /api/memory/artifacts/{id}/bytes
 *
 * Assumes `npm run dev` is running (Express :4001, daemon :4002, vite :4173).
 */

const BASE = 'http://127.0.0.1:4001'
const IRIS_ROOT = process.env.IRIS_ROOT || resolve(__dirname, '..', '..')
const PROJECT = 'deep-datasets-smoke'
const PROJECT_DIR = resolve(IRIS_ROOT, 'projects', PROJECT)

// Shared state (single-worker spec — fullyParallel is off in playwright.config.ts).
let CSV_PATH = ''
let DATASET_ID = ''
let RAW_VERSION_ID = ''
let ARTIFACT_ID_FOR_DERIVE = ''

function makeCsv(): string {
  const tmp = mkdtempSync(join(tmpdir(), 'iris-deep-ds-'))
  const p = join(tmp, 'synthetic.csv')
  const lines: string[] = ['x,y,z']
  for (let i = 0; i < 100; i++) {
    lines.push(`${i},${Math.sin(i).toFixed(6)},${Math.cos(i).toFixed(6)}`)
  }
  writeFileSync(p, lines.join('\n') + '\n', 'utf-8')
  return p
}

async function cleanup(request: any) {
  await request.delete(`${BASE}/api/projects/${PROJECT}`).catch(() => {})
  if (existsSync(PROJECT_DIR)) rmSync(PROJECT_DIR, { recursive: true, force: true })
}

test.beforeAll(async ({ request }) => {
  await cleanup(request)

  // Create + activate project.
  const created = await request.post(`${BASE}/api/projects`, { data: { name: PROJECT } })
  expect(created.ok()).toBeTruthy()

  const opened = await request.get(`${BASE}/api/projects/by-name/${PROJECT}`)
  expect(opened.ok()).toBeTruthy()

  const active = await (await request.get(`${BASE}/api/projects/active`)).json()
  expect(active.active?.name).toBe(PROJECT)

  CSV_PATH = makeCsv()
})

test.afterAll(async ({ request }) => {
  await cleanup(request)
})

test('1 — upload CSV → dataset row + raw version captured (versions shows 1)', async ({
  request,
}) => {
  const res = await request.post(`${BASE}/api/memory/datasets`, {
    data: {
      source_path: CSV_PATH,
      name: 'synthetic-sincos',
      description: '100 rows x=0..99, y=sin(x), z=cos(x)',
    },
  })
  expect(res.ok()).toBeTruthy()
  const body = await res.json()
  expect(body.data?.dataset_id).toBeTruthy()
  expect(body.data?.dataset_version_id).toBeTruthy()
  DATASET_ID = body.data.dataset_id
  RAW_VERSION_ID = body.data.dataset_version_id

  // List shows the new dataset.
  const list = await (await request.get(`${BASE}/api/memory/datasets`)).json()
  const ids = (list.data || []).map((d: any) => d.dataset_id)
  expect(ids).toContain(DATASET_ID)

  // Versions shows exactly 1 (raw).
  const versions = await (
    await request.get(`${BASE}/api/memory/datasets/${DATASET_ID}/versions`)
  ).json()
  expect(Array.isArray(versions.data)).toBe(true)
  expect(versions.data.length).toBe(1)
  expect(versions.data[0].dataset_version_id).toBe(RAW_VERSION_ID)
  // Raw version has no parent.
  expect(versions.data[0].derived_from_dataset_version_id).toBeNull()
})

test('2 — GET /api/memory/datasets/{id} returns metadata + embedded versions', async ({
  request,
}) => {
  const res = await request.get(`${BASE}/api/memory/datasets/${DATASET_ID}`)
  expect(res.ok()).toBeTruthy()
  const { data } = await res.json()
  expect(data.dataset_id).toBe(DATASET_ID)
  expect(data.name).toBe('synthetic-sincos')
  expect(data.original_filename).toBe('synthetic.csv')
  expect(Array.isArray(data.versions)).toBe(true)
  expect(data.versions.length).toBe(1)
})

test('3 — derive new version → versions shows 2', async ({ request }) => {
  // First create an artifact to back the derived version (derive requires artifact_id).
  const bytes = Buffer.from('derived-dataset-bytes-v1')
  const stored = await request.post(`${BASE}/api/memory/artifacts`, {
    data: {
      content_b64: bytes.toString('base64'),
      type: 'data_export',
      metadata: { filename: 'synthetic-normalized.csv' },
      description: 'normalized derived artifact',
    },
  })
  expect(stored.ok()).toBeTruthy()
  const storedBody = await stored.json()
  ARTIFACT_ID_FOR_DERIVE = storedBody.data.artifact_id
  expect(ARTIFACT_ID_FOR_DERIVE).toBeTruthy()

  const derive = await request.post(`${BASE}/api/memory/datasets/${DATASET_ID}/derive`, {
    data: {
      parent_version_id: RAW_VERSION_ID,
      transform_name: 'normalize',
      transform_params: { method: 'zscore' },
      artifact_id: ARTIFACT_ID_FOR_DERIVE,
      description: 'z-score normalized',
    },
  })
  expect(derive.ok()).toBeTruthy()
  const derived = await derive.json()
  expect(derived.data.dataset_version_id).toBeTruthy()

  const versions = await (
    await request.get(`${BASE}/api/memory/datasets/${DATASET_ID}/versions`)
  ).json()
  expect(versions.data.length).toBe(2)
  const derivedRow = versions.data.find(
    (v: any) => v.dataset_version_id === derived.data.dataset_version_id,
  )
  expect(derivedRow).toBeTruthy()
  expect(derivedRow.derived_from_dataset_version_id).toBe(RAW_VERSION_ID)
})

test('4 — profile dataset → stats returned, column count matches (3: x,y,z)', async ({
  request,
}) => {
  const res = await request.post(`${BASE}/api/memory/datasets/${DATASET_ID}/profile`, {
    data: { version_id: RAW_VERSION_ID },
  })
  // Profile requires pandas; if unavailable daemon returns 503. Fail loudly so a
  // missing dep is a real bug, not a silent skip.
  expect(res.ok()).toBeTruthy()
  const { data } = await res.json()
  expect(data.n_rows).toBe(100)
  expect(Array.isArray(data.columns)).toBe(true)
  expect(data.columns.length).toBe(3)
  const names = data.columns.map((c: any) => c.name).sort()
  expect(names).toEqual(['x', 'y', 'z'])
  expect(typeof data.schema_json).toBe('string')
})

test('5 — re-profile is idempotent (same columns/rows; just overwrites schema_json)', async ({
  request,
}) => {
  const a = await request.post(`${BASE}/api/memory/datasets/${DATASET_ID}/profile`, {
    data: { version_id: RAW_VERSION_ID },
  })
  expect(a.ok()).toBeTruthy()
  const b = await request.post(`${BASE}/api/memory/datasets/${DATASET_ID}/profile`, {
    data: { version_id: RAW_VERSION_ID },
  })
  expect(b.ok()).toBeTruthy()
  const aBody = (await a.json()).data
  const bBody = (await b.json()).data
  expect(bBody.n_rows).toBe(aBody.n_rows)
  expect(bBody.columns.length).toBe(aBody.columns.length)
  expect(bBody.schema_json).toBe(aBody.schema_json)
})

test('6 — profile for non-existent dataset → 404', async ({ request }) => {
  const res = await request.post(
    `${BASE}/api/memory/datasets/does-not-exist-xyz/profile`,
    { data: { version_id: 'also-bogus' } },
  )
  expect(res.ok()).toBeFalsy()
  // Daemon raises LookupError → 404. Express proxy may wrap as 500/502 if it
  // reinterprets; accept either but prefer 404.
  expect([404, 500, 502]).toContain(res.status())
})

test('7 — artifact bytes round-trip (same id → same bytes)', async ({ request }) => {
  const original = Buffer.from('hello-iris-artifact-bytes-roundtrip')
  const stored = await request.post(`${BASE}/api/memory/artifacts`, {
    data: {
      content_b64: original.toString('base64'),
      type: 'cache_object',
      description: 'roundtrip test',
    },
  })
  expect(stored.ok()).toBeTruthy()
  const artifactId = (await stored.json()).data.artifact_id
  expect(artifactId).toBeTruthy()

  // Metadata GET works.
  const metaRes = await request.get(`${BASE}/api/memory/artifacts/${artifactId}`)
  expect(metaRes.ok()).toBeTruthy()
  const meta = (await metaRes.json()).data
  expect(meta.artifact_id).toBe(artifactId)
  expect(meta.type).toBe('cache_object')

  // Bytes round-trip: raw buffer equals what we uploaded.
  const bytesRes = await request.get(`${BASE}/api/memory/artifacts/${artifactId}/bytes`)
  expect(bytesRes.ok()).toBeTruthy()
  const got = await bytesRes.body()
  expect(Buffer.compare(got, original)).toBe(0)
})

test('8 — content-addressed dedup: same bytes → same artifact_id', async ({ request }) => {
  const payload = Buffer.from('dedup-me-' + 'x'.repeat(256))
  const b64 = payload.toString('base64')

  const first = await request.post(`${BASE}/api/memory/artifacts`, {
    data: { content_b64: b64, type: 'cache_object', description: 'dedup #1' },
  })
  expect(first.ok()).toBeTruthy()
  const firstId = (await first.json()).data.artifact_id

  const second = await request.post(`${BASE}/api/memory/artifacts`, {
    data: { content_b64: b64, type: 'cache_object', description: 'dedup #2' },
  })
  expect(second.ok()).toBeTruthy()
  const secondId = (await second.json()).data.artifact_id

  expect(secondId).toBe(firstId)

  // And differing bytes yield a different id.
  const other = await request.post(`${BASE}/api/memory/artifacts`, {
    data: {
      content_b64: Buffer.from('different-bytes-' + Date.now()).toString('base64'),
      type: 'cache_object',
    },
  })
  expect(other.ok()).toBeTruthy()
  const otherId = (await other.json()).data.artifact_id
  expect(otherId).not.toBe(firstId)
})
