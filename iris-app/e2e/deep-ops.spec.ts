import { test, expect } from '@playwright/test'
import { existsSync, rmSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

/**
 * Deep E2E coverage for the IRIS ops + runs surface.
 *
 * Covers:
 *   - /api/ops (registry listing + single-op detail)
 *   - /api/memory/operations propose/validate/search/executions
 *   - /api/memory/runs start/complete/fail + lineage DAG
 *
 * Assumes `npm run dev` is live: Vite :4173, Express :4001, daemon :4002.
 */

const BASE = 'http://127.0.0.1:4001'
const IRIS_ROOT = process.env.IRIS_ROOT || resolve(__dirname, '..', '..')
const PROJECT = 'deep-ops-smoke'
const PROJECT_DIR = resolve(IRIS_ROOT, 'projects', PROJECT)

// All 17 hardcoded ops registered in src/iris/engine/factory.py. The two
// binary function-ops (spike_curate, x_corr) now surface via TYPE_TRANSITIONS
// too; their right-operand type rides along on the `right_input_type` field.
const HARDCODED_OPS = [
  'butter_bandpass',
  'notch_filter',
  'saturation_mask',
  'sliding_rms',
  'constant_rms',
  'spike_pca',
  'spike_curate',
  'baseline_correction',
  'rt_detect',
  'sigmoid',
  'rt_thresh',
  'gcamp_sim',
  'x_corr',
  'spectrogram',
  'freq_traces',
  'amp_gain_correction',
  'saturation_survey',
]
const EXPECTED_OP_COUNT = 17

async function cleanup(request: any) {
  await request.delete(`${BASE}/api/projects/${PROJECT}`).catch(() => {})
  if (existsSync(PROJECT_DIR)) rmSync(PROJECT_DIR, { recursive: true, force: true })
}

async function startSession(request: any): Promise<string> {
  const res = await request.post(`${BASE}/api/memory/sessions/start`, {
    data: {
      model_provider: 'anthropic',
      model_name: 'claude-opus-4-6',
      system_prompt: 'e2e deep-ops',
    },
  })
  expect(res.ok()).toBeTruthy()
  const body = await res.json()
  const sessionId = body.data?.session_id ?? body.session_id ?? body.data?.id
  expect(typeof sessionId).toBe('string')
  return sessionId as string
}

test.describe.configure({ mode: 'serial' })

test.beforeAll(async ({ request }) => {
  await cleanup(request)
  const created = await request.post(`${BASE}/api/projects`, { data: { name: PROJECT } })
  expect(created.ok()).toBeTruthy()
  const activated = await request.post(`${BASE}/api/projects/active`, {
    data: { name: PROJECT },
  })
  expect(activated.ok()).toBeTruthy()
})

test.afterAll(async ({ request }) => {
  await cleanup(request)
})

test('GET /api/ops — lists the 17 hardcoded ops with type transitions', async ({ request }) => {
  const res = await request.get(`${BASE}/api/ops`)
  expect(res.ok()).toBeTruthy()
  const rows = await res.json()
  expect(Array.isArray(rows)).toBe(true)

  const names = new Set(rows.map((r: any) => r.name))
  for (const op of HARDCODED_OPS) {
    expect(names.has(op), `missing op: ${op}`).toBe(true)
  }
  // Count lock-in: exactly the documented 17 distinct op names.
  expect(names.size).toBe(EXPECTED_OP_COUNT)
  // Every transition row should carry both input/output type.
  for (const row of rows) {
    expect(typeof row.input_type).toBe('string')
    expect(typeof row.output_type).toBe('string')
    expect(['unary', 'binary']).toContain(row.kind)
  }

  // Binary ops surface their right operand.
  const spikeCurate = rows.find((r: any) => r.name === 'spike_curate')
  expect(spikeCurate).toBeTruthy()
  expect(spikeCurate.kind).toBe('binary')
  expect(spikeCurate.input_type).toBe('SpikePCA')
  expect(spikeCurate.right_input_type).toBe('CATrace')
  expect(spikeCurate.output_type).toBe('SpikeTrain')

  const xCorr = rows.find((r: any) => r.name === 'x_corr')
  expect(xCorr).toBeTruthy()
  expect(xCorr.kind).toBe('binary')
  expect(xCorr.input_type).toBe('CATrace')
  expect(xCorr.right_input_type).toBe('SimCalciumBank')
  expect(xCorr.output_type).toBe('CorrelationResult')
})

test('GET /api/ops — signature rows for butter_bandpass expose both MEATrace + MEABank transitions', async ({
  request,
}) => {
  // Express proxies /api/ops but not /api/ops/{name}. Verify the signature
  // surface via the listing endpoint (still covers the "signature for a known
  // op" contract the task asks for).
  const rows = await (await request.get(`${BASE}/api/ops`)).json()
  const bbRows = rows.filter((r: any) => r.name === 'butter_bandpass')
  expect(bbRows.length).toBeGreaterThanOrEqual(2)
  const inputs = new Set(bbRows.map((r: any) => r.input_type))
  expect(inputs.has('MEATrace')).toBe(true)
  expect(inputs.has('MEABank')).toBe(true)
  for (const row of bbRows) {
    expect(typeof row.input_type).toBe('string')
    expect(typeof row.output_type).toBe('string')
  }

  // A bogus op name must not appear.
  const bogus = rows.find((r: any) => r.name === 'this_op_does_not_exist')
  expect(bogus).toBeUndefined()
})

test('POST /api/memory/operations/propose — new project-scoped op appears in project list', async ({
  request,
}) => {
  const res = await request.post(`${BASE}/api/memory/operations/propose`, {
    data: {
      name: 'doubler',
      version: '0.1.0',
      description: 'Double the input',
      code: 'def run(x):\n    return x * 2\n',
      signature_json: { input: 'number', output: 'number' },
    },
  })
  expect(res.ok()).toBeTruthy()
  const body = await res.json()
  const opId = body.data?.op_id
  expect(typeof opId).toBe('string')

  // Source landed on disk under the project.
  expect(existsSync(resolve(PROJECT_DIR, 'ops', 'doubler', 'v0.1.0', 'op.py'))).toBe(true)

  // Listed in the project-scoped catalog. Propose lands as draft, not active,
  // so query with status=draft.
  const listRes = await request.get(
    `${BASE}/api/memory/operations?scope=project&status=draft`,
  )
  expect(listRes.ok()).toBeTruthy()
  const listBody = await listRes.json()
  const names = (listBody.data ?? []).map((op: any) => op.name)
  expect(names).toContain('doubler')

  // Single-op fetch should also work.
  const one = await request.get(`${BASE}/api/memory/operations/${opId}`)
  expect(one.ok()).toBeTruthy()
  const oneBody = await one.json()
  expect(oneBody.data?.name).toBe('doubler')
})

test('POST /api/memory/operations/{id}/validate — passes for trivial op, rejects broken syntax', async ({
  request,
}) => {
  // 1) Trivial op — validates cleanly.
  const goodProp = await request.post(`${BASE}/api/memory/operations/propose`, {
    data: {
      name: 'validator_good',
      version: '0.1.0',
      description: 'trivial',
      code: 'def run(x):\n    return x + 1\n',
      signature_json: { input: 'number', output: 'number' },
    },
  })
  expect(goodProp.ok()).toBeTruthy()
  const goodId = (await goodProp.json()).data.op_id

  const goodVal = await request.post(
    `${BASE}/api/memory/operations/${goodId}/validate`,
    { data: { sample_input: { x: 3 } } },
  )
  expect(goodVal.ok()).toBeTruthy()
  // After the ValidationResult serialization fix, the response body carries
  // the sandbox verdict directly — not just the DB row mutation.
  const goodValBody = (await goodVal.json()).data
  expect(goodValBody).toBeTruthy()
  expect(Object.keys(goodValBody).length).toBeGreaterThan(0)
  expect(goodValBody.ok).toBe(true)
  expect(goodValBody.stage).toBe('done')
  expect(goodValBody.error).toBeNull()
  const goodRow = await request.get(`${BASE}/api/memory/operations/${goodId}`)
  const goodData = (await goodRow.json()).data
  expect(goodData.validation_status).toBe('validated')

  // 2) Broken op — static stage fails, returns ok=false cleanly (HTTP 200).
  const badProp = await request.post(`${BASE}/api/memory/operations/propose`, {
    data: {
      name: 'validator_bad',
      version: '0.1.0',
      description: 'syntax error',
      code: 'def run(x):\n    retur x + 1\n', // typo: retur
      signature_json: {},
    },
  })
  expect(badProp.ok()).toBeTruthy()
  const badId = (await badProp.json()).data.op_id

  const badVal = await request.post(
    `${BASE}/api/memory/operations/${badId}/validate`,
    { data: {} },
  )
  expect(badVal.ok()).toBeTruthy()
  const badValBody = (await badVal.json()).data
  expect(badValBody).toBeTruthy()
  expect(Object.keys(badValBody).length).toBeGreaterThan(0)
  expect(badValBody.ok).toBe(false)
  expect(badValBody.stage).toBe('static')
  expect(typeof badValBody.error).toBe('string')
  expect(badValBody.error).toContain('SyntaxError')
  const badRow = await request.get(`${BASE}/api/memory/operations/${badId}`)
  const badData = (await badRow.json()).data
  expect(badData.validation_status).toBe('rejected')
})

test('GET /api/memory/operations/search — FTS returns a proposed op', async ({ request }) => {
  // Propose an op with a distinctive token we can search for.
  const proposed = await request.post(`${BASE}/api/memory/operations/propose`, {
    data: {
      name: 'searchable_unicorn_op',
      version: '0.1.0',
      description: 'unicornish frobnicator for discovery',
      code: 'def run(x):\n    return x\n',
      signature_json: {},
    },
  })
  expect(proposed.ok()).toBeTruthy()

  const res = await request.get(
    `${BASE}/api/memory/operations/search?q=unicorn&scope=project&limit=10`,
  )
  expect(res.ok()).toBeTruthy()
  const hits = (await res.json()).data ?? []
  const names = hits.map((h: any) => h.name)
  expect(names).toContain('searchable_unicorn_op')
})

test('POST /api/memory/runs start+complete — status transitions to completed', async ({
  request,
}) => {
  const sessionId = await startSession(request)

  const started = await request.post(`${BASE}/api/memory/runs/start`, {
    data: {
      session_id: sessionId,
      operation_type: 'analysis',
      parameters: { foo: 'bar' },
    },
  })
  expect(started.ok()).toBeTruthy()
  const runId = (await started.json()).data.run_id
  expect(typeof runId).toBe('string')

  const completed = await request.post(`${BASE}/api/memory/runs/${runId}/complete`, {
    data: { findings_text: 'ok', execution_time_ms: 42 },
  })
  expect(completed.ok()).toBeTruthy()

  const list = await request.get(`${BASE}/api/memory/runs?session_id=${sessionId}`)
  expect(list.ok()).toBeTruthy()
  const rows = (await list.json()).data ?? []
  const row = rows.find((r: any) => r.run_id === runId)
  expect(row).toBeTruthy()
  expect(row.status).toBe('completed')
})

test('POST /api/memory/runs start+fail — status transitions to failed with error', async ({
  request,
}) => {
  const sessionId = await startSession(request)

  const started = await request.post(`${BASE}/api/memory/runs/start`, {
    data: { session_id: sessionId, operation_type: 'analysis' },
  })
  expect(started.ok()).toBeTruthy()
  const runId = (await started.json()).data.run_id

  const failed = await request.post(`${BASE}/api/memory/runs/${runId}/fail`, {
    data: { error_text: 'kaboom: simulated failure' },
  })
  expect(failed.ok()).toBeTruthy()

  const list = await request.get(`${BASE}/api/memory/runs?session_id=${sessionId}`)
  const rows = (await list.json()).data ?? []
  const row = rows.find((r: any) => r.run_id === runId)
  expect(row).toBeTruthy()
  expect(row.status).toBe('failed')
  expect(row.error_text ?? row.error ?? '').toContain('kaboom')
})

test('GET /api/memory/runs/{id}/lineage — returns ancestors + descendants with i/o metadata', async ({
  request,
}) => {
  const sessionId = await startSession(request)

  // Parent run with input_versions representing an input dataset version.
  const parent = await request.post(`${BASE}/api/memory/runs/start`, {
    data: {
      session_id: sessionId,
      operation_type: 'ingest',
      input_versions: ['ds-v1'],
      parameters: {},
    },
  })
  expect(parent.ok()).toBeTruthy()
  const parentId = (await parent.json()).data.run_id

  await request.post(`${BASE}/api/memory/runs/${parentId}/complete`, {
    data: { output_data_hash: 'sha256:parentout' },
  })

  // Child run links via parent_run_id and consumes parent's output.
  const child = await request.post(`${BASE}/api/memory/runs/start`, {
    data: {
      session_id: sessionId,
      operation_type: 'transform',
      parent_run_id: parentId,
      input_versions: ['sha256:parentout'],
    },
  })
  expect(child.ok()).toBeTruthy()
  const childId = (await child.json()).data.run_id
  await request.post(`${BASE}/api/memory/runs/${childId}/complete`, {
    data: { output_data_hash: 'sha256:childout' },
  })

  // Lineage from child — ancestors should include parent.
  const lineageRes = await request.get(`${BASE}/api/memory/runs/${childId}/lineage`)
  expect(lineageRes.ok()).toBeTruthy()
  const lineage = (await lineageRes.json()).data
  expect(Array.isArray(lineage.ancestors)).toBe(true)
  expect(Array.isArray(lineage.descendants)).toBe(true)

  const ancestorIds = lineage.ancestors.map((r: any) => r.run_id)
  expect(ancestorIds).toContain(parentId)

  // At least one ancestor should expose the input_versions carrying the
  // upstream dataset id, and an output_data_hash for downstream linkage.
  const parentRow = lineage.ancestors.find((r: any) => r.run_id === parentId)
  expect(parentRow).toBeTruthy()
  expect(parentRow.input_versions).toEqual(expect.arrayContaining(['ds-v1']))
  expect(parentRow.output_data_hash).toBe('sha256:parentout')

  // And the descendants list from the parent should include the child.
  const lineageParent = await request.get(
    `${BASE}/api/memory/runs/${parentId}/lineage`,
  )
  const descIds = ((await lineageParent.json()).data.descendants ?? []).map(
    (r: any) => r.run_id,
  )
  expect(descIds).toContain(childId)
})
