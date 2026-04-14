import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { api } from '../lib/api'

// Regression tests for the list-endpoint normalizers in lib/api.ts.
//
// The Python daemon wraps list responses as `{data: [...]}`. The frontend
// normalizers used to only check `{entries: ...}` / `{rows: ...}`, which made
// MemoryInspector and CurationRitual render as empty. These tests lock in
// the `data`-first precedence while keeping backward-compat for the legacy
// `entries` / `rows` shapes, bare arrays, and empty/missing payloads.

function mockFetchOnce(body: any, ok = true) {
  const res = {
    ok,
    status: ok ? 200 : 500,
    json: async () => body,
  } as unknown as Response
  return vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(res)
}

describe('api.listMemoryEntries normalizer', () => {
  beforeEach(() => { vi.restoreAllMocks() })
  afterEach(() => { vi.restoreAllMocks() })

  it('unwraps daemon {data: [...]} shape (the bug fix)', async () => {
    mockFetchOnce({ data: [{ id: 'm1' }, { id: 'm2' }] })
    const res = await api.listMemoryEntries()
    expect(res.entries).toEqual([{ id: 'm1' }, { id: 'm2' }])
  })

  it('still accepts legacy {entries: [...]} shape', async () => {
    mockFetchOnce({ entries: [{ id: 'L1' }] })
    const res = await api.listMemoryEntries()
    expect(res.entries).toEqual([{ id: 'L1' }])
  })

  it('still accepts legacy {rows: [...]} shape', async () => {
    mockFetchOnce({ rows: [{ id: 'R1' }] })
    const res = await api.listMemoryEntries()
    expect(res.entries).toEqual([{ id: 'R1' }])
  })

  it('accepts bare array shape', async () => {
    mockFetchOnce([{ id: 'A1' }])
    const res = await api.listMemoryEntries()
    expect(res.entries).toEqual([{ id: 'A1' }])
  })

  it('returns [] for empty / missing data', async () => {
    mockFetchOnce({})
    expect((await api.listMemoryEntries()).entries).toEqual([])
    mockFetchOnce({ data: [] })
    expect((await api.listMemoryEntries()).entries).toEqual([])
  })

  it('returns [] on HTTP error', async () => {
    mockFetchOnce({ error: 'boom' }, false)
    expect((await api.listMemoryEntries()).entries).toEqual([])
  })

  it('passes query string filters through to fetch', async () => {
    const spy = mockFetchOnce({ data: [] })
    await api.listMemoryEntries({ type: 'finding', status: 'draft', limit: 3 })
    const url = spy.mock.calls[0][0] as string
    expect(url).toContain('type=finding')
    expect(url).toContain('status=draft')
    expect(url).toContain('limit=3')
  })
})

describe('api.listArtifacts normalizer', () => {
  beforeEach(() => { vi.restoreAllMocks() })

  it('unwraps {data: [...]}', async () => {
    mockFetchOnce({ data: [{ id: 'a1' }] })
    expect((await api.listArtifacts()).artifacts).toEqual([{ id: 'a1' }])
  })
  it('accepts legacy {artifacts: [...]}', async () => {
    mockFetchOnce({ artifacts: [{ id: 'a2' }] })
    expect((await api.listArtifacts()).artifacts).toEqual([{ id: 'a2' }])
  })
  it('empty -> []', async () => {
    mockFetchOnce({})
    expect((await api.listArtifacts()).artifacts).toEqual([])
  })
})

describe('api.listDatasets normalizer', () => {
  beforeEach(() => { vi.restoreAllMocks() })

  it('unwraps daemon {data: [...]}', async () => {
    mockFetchOnce({ data: [{ id: 'd1' }] })
    expect((await api.listDatasets()).datasets).toEqual([{ id: 'd1' }])
  })
  it('accepts legacy {datasets: [...]}', async () => {
    mockFetchOnce({ datasets: [{ id: 'd2' }] })
    expect((await api.listDatasets()).datasets).toEqual([{ id: 'd2' }])
  })
  it('empty -> []', async () => {
    mockFetchOnce({})
    expect((await api.listDatasets()).datasets).toEqual([])
  })
})

describe('api.listDatasetVersions normalizer', () => {
  beforeEach(() => { vi.restoreAllMocks() })

  it('unwraps {data: [...]}', async () => {
    mockFetchOnce({ data: [{ id: 'v1' }] })
    expect((await api.listDatasetVersions('ds1')).versions).toEqual([{ id: 'v1' }])
  })
  it('accepts legacy {versions: [...]}', async () => {
    mockFetchOnce({ versions: [{ id: 'v2' }] })
    expect((await api.listDatasetVersions('ds1')).versions).toEqual([{ id: 'v2' }])
  })
})

describe('api.listRuns normalizer', () => {
  beforeEach(() => { vi.restoreAllMocks() })

  it('unwraps daemon {data: [...]} into {rows: [...]}', async () => {
    mockFetchOnce({ data: [{ id: 'r1' }] })
    const res = await api.listRuns('proj')
    expect(res.rows).toEqual([{ id: 'r1' }])
  })
  it('accepts legacy {rows: [...]}', async () => {
    mockFetchOnce({ rows: [{ id: 'r2' }] })
    const res = await api.listRuns('proj')
    expect(res.rows).toEqual([{ id: 'r2' }])
  })
  it('empty daemon response -> rows:[]', async () => {
    mockFetchOnce({ data: [] })
    expect((await api.listRuns('proj')).rows).toEqual([])
  })
})
