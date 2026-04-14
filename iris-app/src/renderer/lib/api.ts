import type { ProjectInfo, PlotSidecar, UploadResult } from '../types'

const BASE = ''

export const api = {
  // Agent
  sendMessage: (prompt: string, projectName?: string) =>
    fetch(`${BASE}/api/agent/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt, projectName })
    }),

  abortAgent: () =>
    fetch(`${BASE}/api/agent/abort`, { method: 'POST' }),

  // -- Canonical project lifecycle (REVAMP Task 1.10) ------------------
  // Names mirror the six daemon endpoints so the frontend, Express proxy,
  // and Python daemon agree. `projectList`/`projectOpen`/etc. are kept as
  // aliases for components that have not migrated yet.

  listProjects: async (): Promise<ProjectInfo[]> => {
    const res = await fetch(`${BASE}/api/projects`)
    return res.json()
  },

  createProject: async (name: string, description?: string): Promise<ProjectInfo | null> => {
    const res = await fetch(`${BASE}/api/projects`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, description }),
    })
    if (!res.ok) return null
    return res.json()
  },

  openProject: async (name: string): Promise<ProjectInfo | null> => {
    // Activates as a side-effect (matches daemon GET /projects/{name} behaviour).
    const res = await fetch(`${BASE}/api/projects/by-name/${encodeURIComponent(name)}`)
    if (!res.ok) return null
    return res.json()
  },

  deleteProject: async (name: string): Promise<boolean> => {
    const res = await fetch(`${BASE}/api/projects/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    })
    return res.ok
  },

  getActiveProject: async (): Promise<ProjectInfo | null> => {
    const res = await fetch(`${BASE}/api/projects/active`)
    if (!res.ok) return null
    const data = (await res.json()) as { active: ProjectInfo | null }
    return data.active
  },

  setActiveProject: async (name: string): Promise<ProjectInfo | null> => {
    const res = await fetch(`${BASE}/api/projects/active`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })
    if (!res.ok) return null
    const data = (await res.json()) as { active: ProjectInfo | null }
    return data.active
  },

  // -- Legacy aliases (kept until callers migrate) ---------------------

  projectList: async (): Promise<ProjectInfo[]> => {
    const res = await fetch(`${BASE}/api/projects`)
    return res.json()
  },

  projectOpen: async (name: string): Promise<boolean> => {
    const res = await fetch(`${BASE}/api/projects/open`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name })
    })
    return res.ok
  },

  projectCreate: async (name: string, description?: string): Promise<boolean> => {
    const res = await fetch(`${BASE}/api/projects/create`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, description })
    })
    return res.ok
  },

  projectInfo: async (name?: string): Promise<{ description: string; agent_notes: string } | null> => {
    const params = name ? `?name=${encodeURIComponent(name)}` : ''
    const res = await fetch(`${BASE}/api/projects/info${params}`)
    const data = await res.json()
    return data.info
  },

  projectRename: async (oldName: string, newName: string): Promise<boolean> => {
    const res = await fetch(`${BASE}/api/projects/rename`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ oldName, newName })
    })
    return res.ok
  },

  projectDelete: async (name: string): Promise<boolean> => {
    const res = await fetch(`${BASE}/api/projects/delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name })
    })
    return res.ok
  },

  projectUpload: async (name: string, files: FileList): Promise<UploadResult> => {
    const form = new FormData()
    for (let i = 0; i < files.length; i++) form.append('files', files[i])
    const res = await fetch(`${BASE}/api/projects/upload?name=${encodeURIComponent(name)}`, {
      method: 'POST',
      body: form,
    })
    const data = await res.json()
    return { count: data.count ?? 0, profiles: data.profiles ?? [] }
  },

  // Profile annotations (per-field confirm/edit)
  proposeProfileAnnotation: async (
    project: string,
    session_id: string,
    field_path: string,
    annotation: string,
  ): Promise<number> => {
    const res = await fetch(`${BASE}/api/memory/propose_profile_annotation`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, session_id, field_path, annotation }),
    })
    const data = await res.json()
    return data.pending_id
  },

  commitSessionWrites: async (
    project: string,
    session_id: string,
    approve_ids?: number[],
  ): Promise<{ committed: number; by_kind: Record<string, number> }> => {
    const res = await fetch(`${BASE}/api/memory/commit_session_writes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, session_id, approve_ids, finalize_digest: false }),
    })
    return res.json()
  },

  projectFiles: async (name: string): Promise<{ name: string; path: string; type: 'file' | 'dir'; size: number }[]> => {
    const res = await fetch(`${BASE}/api/projects/files?name=${encodeURIComponent(name)}`)
    return res.json()
  },

  // Global agent rules
  agentRules: async (): Promise<string> => {
    const res = await fetch(`${BASE}/api/agent-rules`)
    const data = await res.json()
    return data.rules || ''
  },

  agentRulesSave: async (rules: string): Promise<boolean> => {
    const res = await fetch(`${BASE}/api/agent-rules`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rules })
    })
    return res.ok
  },

  // Config
  configShow: async () => {
    const res = await fetch(`${BASE}/api/config`)
    return res.json()
  },

  // Ops
  opsList: async () => {
    const res = await fetch(`${BASE}/api/ops`)
    return res.json()
  },

  // Sessions
  sessionList: async () => {
    const res = await fetch(`${BASE}/api/sessions`)
    return res.json()
  },

  // Report
  reportContent: async (name: string): Promise<string> => {
    const res = await fetch(`${BASE}/api/report?name=${encodeURIComponent(name)}`)
    const data = await res.json()
    return data.content || ''
  },

  // Sidecar
  readSidecar: async (plotPath: string): Promise<PlotSidecar | null> => {
    const res = await fetch(`${BASE}/api/sidecar?path=${encodeURIComponent(plotPath)}`)
    return res.json()
  },

  // Custom ops
  projectCustomOps: async (name: string): Promise<string[]> => {
    const res = await fetch(`${BASE}/api/projects/custom-ops?name=${encodeURIComponent(name)}`)
    return res.json()
  },

  projectCustomOpRead: async (name: string, op: string): Promise<string | null> => {
    const res = await fetch(`${BASE}/api/projects/custom-ops/read?name=${encodeURIComponent(name)}&op=${encodeURIComponent(op)}`)
    const data = await res.json()
    return data.content
  },

  // Clear conversations
  projectClearConversations: async (name: string): Promise<boolean> => {
    const res = await fetch(`${BASE}/api/projects/clear-conversations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name })
    })
    return res.ok
  },

  // Delete file
  projectDeleteFile: async (name: string, filePath: string): Promise<boolean> => {
    const res = await fetch(`${BASE}/api/projects/delete-file`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, filePath })
    })
    return res.ok
  },

  // Update config
  projectUpdateConfig: async (name: string, updates: { description?: string; agentNotes?: string }): Promise<boolean> => {
    const res = await fetch(`${BASE}/api/projects/update-config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, ...updates })
    })
    return res.ok
  },

  // -- Behavior dials (autonomy / pushback / memory) -------------------
  projectBehavior: async (name: string): Promise<{
    autonomy: string
    pushback: string
    memory: { slice_budget_tokens: number }
  }> => {
    const res = await fetch(`${BASE}/api/projects/behavior?name=${encodeURIComponent(name)}`)
    return res.json()
  },

  projectBehaviorSave: async (
    name: string,
    body: { autonomy?: string; pushback?: string; memory?: { slice_budget_tokens?: number } },
  ): Promise<boolean> => {
    const res = await fetch(`${BASE}/api/projects/behavior`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, ...body }),
    })
    return res.ok
  },

  // -- Memory entries (REVAMP Phase 4.7) -------------------------------
  // TODO: tighten these permissive types once the daemon settles on a final
  // MemoryEntry schema (REVAMP §7 memory_entries).
  listMemoryEntries: async (
    opts: {
      type?: string
      status?: string
      scope?: string
      datasetId?: string
      limit?: number
    } = {},
  ): Promise<{ entries: any[] }> => {
    const qs = new URLSearchParams()
    if (opts.type) qs.set('type', opts.type)
    if (opts.status) qs.set('status', opts.status)
    if (opts.scope) qs.set('scope', opts.scope)
    if (opts.datasetId) qs.set('dataset_id', opts.datasetId)
    if (opts.limit) qs.set('limit', String(opts.limit))
    const url = `${BASE}/api/memory/entries${qs.toString() ? `?${qs.toString()}` : ''}`
    const res = await fetch(url)
    if (!res.ok) return { entries: [] }
    const data = await res.json()
    // Daemon may return {entries: [...]} or a bare list — normalize.
    if (Array.isArray(data)) return { entries: data }
    return { entries: data.entries ?? data.rows ?? [] }
  },

  proposeMemoryEntry: async (body: Record<string, any>): Promise<any> => {
    const res = await fetch(`${BASE}/api/memory/entries`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    return res.json()
  },

  commitMemoryEntries: async (
    ids: string[],
    sessionId?: string,
  ): Promise<any> => {
    const res = await fetch(`${BASE}/api/memory/entries/commit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids, session_id: sessionId }),
    })
    return res.json()
  },

  discardMemoryEntries: async (ids: string[]): Promise<any> => {
    const res = await fetch(`${BASE}/api/memory/entries/discard`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    })
    return res.json()
  },

  patchMemoryEntryStatus: async (id: string, status: string): Promise<any> => {
    const res = await fetch(
      `${BASE}/api/memory/entries/${encodeURIComponent(id)}/status`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      },
    )
    return res.json()
  },

  supersedeMemoryEntry: async (oldId: string, newId: string): Promise<any> => {
    const res = await fetch(`${BASE}/api/memory/entries/supersede`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ old_id: oldId, new_id: newId }),
    })
    return res.json()
  },

  softDeleteMemoryEntry: async (id: string): Promise<boolean> => {
    const res = await fetch(
      `${BASE}/api/memory/entries/${encodeURIComponent(id)}`,
      { method: 'DELETE' },
    )
    return res.ok
  },

  extractSessionMemories: async (sessionId: string): Promise<any> => {
    const res = await fetch(`${BASE}/api/memory/extract`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId }),
    })
    return res.json()
  },

  // -- Artifacts (REVAMP Phase 5) --------------------------------------
  // TODO: tighten the `any` once the daemon settles on a final Artifact shape
  // (REVAMP §7 artifacts). Schema is {id, type, sha256, created_at, run_id, metadata, ...}.
  listArtifacts: async (
    opts: { type?: string; runId?: string; limit?: number } = {},
  ): Promise<{ artifacts: any[] }> => {
    const qs = new URLSearchParams()
    if (opts.type) qs.set('type', opts.type)
    if (opts.runId) qs.set('run_id', opts.runId)
    if (opts.limit) qs.set('limit', String(opts.limit))
    const url = `${BASE}/api/memory/artifacts${qs.toString() ? `?${qs.toString()}` : ''}`
    const res = await fetch(url)
    if (!res.ok) return { artifacts: [] }
    const data = await res.json()
    const rows = Array.isArray(data) ? data : (data.data ?? data.artifacts ?? [])
    return { artifacts: rows }
  },

  getArtifactMetadata: async (id: string): Promise<any | null> => {
    const res = await fetch(
      `${BASE}/api/memory/artifacts/${encodeURIComponent(id)}`,
    )
    if (!res.ok) return null
    const data = await res.json()
    return data.data ?? data
  },

  getArtifactBytesUrl: (id: string): string =>
    `${BASE}/api/memory/artifacts/${encodeURIComponent(id)}/bytes`,

  softDeleteArtifact: async (id: string): Promise<boolean> => {
    const res = await fetch(
      `${BASE}/api/memory/artifacts/${encodeURIComponent(id)}`,
      { method: 'DELETE' },
    )
    return res.ok
  },

  // Export URL
  projectExportUrl: (name: string): string =>
    `${BASE}/api/projects/export?name=${encodeURIComponent(name)}`,

  // -- Datasets (REVAMP Phase 6 / Task 6.6) ----------------------------
  // TODO(Task 6.6): tighten these `any` types once the daemon settles on
  // final Dataset / DatasetVersion shapes (spec §7 datasets, dataset_versions).
  importDataset: async (body: {
    source_path: string
    name?: string
    description?: string
  }): Promise<any> => {
    const res = await fetch(`${BASE}/api/memory/datasets`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) throw new Error(`importDataset failed: ${res.status}`)
    return res.json()
  },

  listDatasets: async (): Promise<{ datasets: any[] }> => {
    const res = await fetch(`${BASE}/api/memory/datasets`)
    if (!res.ok) return { datasets: [] }
    const data = await res.json()
    if (Array.isArray(data)) return { datasets: data }
    return { datasets: data.datasets ?? data.data ?? [] }
  },

  getDataset: async (id: string): Promise<any | null> => {
    const res = await fetch(
      `${BASE}/api/memory/datasets/${encodeURIComponent(id)}`,
    )
    if (!res.ok) return null
    return res.json()
  },

  listDatasetVersions: async (id: string): Promise<{ versions: any[] }> => {
    const res = await fetch(
      `${BASE}/api/memory/datasets/${encodeURIComponent(id)}/versions`,
    )
    if (!res.ok) return { versions: [] }
    const data = await res.json()
    if (Array.isArray(data)) return { versions: data }
    return { versions: data.versions ?? data.data ?? [] }
  },

  profileDataset: async (
    id: string,
    versionId?: string,
  ): Promise<any> => {
    const res = await fetch(
      `${BASE}/api/memory/datasets/${encodeURIComponent(id)}/profile`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(versionId ? { version_id: versionId } : {}),
      },
    )
    if (!res.ok) throw new Error(`profileDataset failed: ${res.status}`)
    return res.json()
  },

  deriveDatasetVersion: async (
    id: string,
    body: Record<string, any>,
  ): Promise<any> => {
    const res = await fetch(
      `${BASE}/api/memory/datasets/${encodeURIComponent(id)}/derive`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
    )
    if (!res.ok) throw new Error(`deriveDatasetVersion failed: ${res.status}`)
    return res.json()
  },

  // Runs (Task 7.5)
  listRuns: async (
    _project: string,
    opts?: { sessionId?: string; status?: string; limit?: number },
  ) => {
    const qs = new URLSearchParams()
    if (opts?.sessionId) qs.set('session_id', opts.sessionId)
    if (opts?.status) qs.set('status', opts.status)
    if (opts?.limit) qs.set('limit', String(opts.limit))
    const res = await fetch(`${BASE}/api/memory/runs${qs.toString() ? '?' + qs : ''}`)
    return res.json()
  },
  getRunLineage: async (_project: string, runId: string) => {
    const res = await fetch(
      `${BASE}/api/memory/runs/${encodeURIComponent(runId)}/lineage`,
    )
    return res.json()
  },

  // Plot image URL — served via Express static
  plotUrl: (plotPath: string): string => {
    // Convert absolute path to relative URL under /plots
    // e.g. <IRIS_ROOT>/projects/my-proj/output/plot.png → /plots/my-proj/output/plot.png
    const match = plotPath.replace(/\\/g, '/').match(/projects\/(.+)/)
    if (match) return `${BASE}/plots/${match[1]}`
    return plotPath
  }
}
