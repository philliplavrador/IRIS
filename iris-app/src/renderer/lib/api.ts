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

  // Projects
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

  projectInfo: async (name?: string): Promise<string | null> => {
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
    yaml: string
    autonomy: string
    pushback: Record<string, string>
    memory: Record<string, string>
  }> => {
    const res = await fetch(`${BASE}/api/projects/behavior?name=${encodeURIComponent(name)}`)
    return res.json()
  },

  projectBehaviorSave: async (
    name: string,
    body: { autonomy?: string; pushback?: Record<string, string>; memory?: Record<string, number | boolean> },
  ): Promise<boolean> => {
    const res = await fetch(`${BASE}/api/projects/behavior`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, ...body }),
    })
    return res.ok
  },

  // -- L3 knowledge inspector ------------------------------------------
  listKnowledge: async (
    project: string,
    table: string,
    opts: { status?: string; limit?: number } = {},
  ): Promise<{ rows: any[] }> => {
    const qs = new URLSearchParams({ project, table })
    if (opts.status) qs.set('status', opts.status)
    if (opts.limit) qs.set('limit', String(opts.limit))
    const res = await fetch(`${BASE}/api/memory/list_knowledge?${qs.toString()}`)
    return res.json()
  },

  setKnowledgeStatus: async (project: string, table: string, id: number, status: string): Promise<boolean> => {
    const res = await fetch(`${BASE}/api/memory/set_status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, table, id, status }),
    })
    return res.ok
  },

  deleteKnowledgeRow: async (project: string, table: string, id: number): Promise<boolean> => {
    const res = await fetch(`${BASE}/api/memory/delete_row`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, table, id }),
    })
    return res.ok
  },

  // -- Curation ritual --------------------------------------------------
  listDigests: async (project: string): Promise<{ drafts: string[]; finals: string[] }> => {
    const res = await fetch(`${BASE}/api/memory/list_digests?project=${encodeURIComponent(project)}`)
    return res.json()
  },

  getDraftDigest: async (project: string, session_id: string): Promise<any> => {
    const res = await fetch(
      `${BASE}/api/memory/draft_digest?project=${encodeURIComponent(project)}&session_id=${encodeURIComponent(session_id)}`,
    )
    return res.json()
  },

  replaceDraftDigest: async (project: string, session_id: string, digest: any): Promise<any> => {
    const res = await fetch(`${BASE}/api/memory/replace_draft`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, session_id, digest }),
    })
    return res.json()
  },

  listPending: async (project: string, session_id?: string): Promise<{ pending: any[] }> => {
    const qs = new URLSearchParams({ project })
    if (session_id) qs.set('session_id', session_id)
    const res = await fetch(`${BASE}/api/memory/pending?${qs.toString()}`)
    return res.json()
  },

  discardPending: async (project: string, ids: number[]): Promise<boolean> => {
    const res = await fetch(`${BASE}/api/memory/discard_pending`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, ids }),
    })
    return res.ok
  },

  commitSession: async (
    project: string,
    session_id: string,
    opts: { approve_ids?: number[]; finalize_digest?: boolean } = {},
  ): Promise<{ committed: number; by_kind: Record<string, number> }> => {
    const res = await fetch(`${BASE}/api/memory/commit_session_writes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        project,
        session_id,
        approve_ids: opts.approve_ids,
        finalize_digest: opts.finalize_digest ?? true,
      }),
    })
    return res.json()
  },

  // Export URL
  projectExportUrl: (name: string): string =>
    `${BASE}/api/projects/export?name=${encodeURIComponent(name)}`,

  // Plot image URL — served via Express static
  plotUrl: (plotPath: string): string => {
    // Convert absolute path to relative URL under /plots
    // e.g. <IRIS_ROOT>/projects/my-proj/output/plot.png → /plots/my-proj/output/plot.png
    const match = plotPath.replace(/\\/g, '/').match(/projects\/(.+)/)
    if (match) return `${BASE}/plots/${match[1]}`
    return plotPath
  }
}
