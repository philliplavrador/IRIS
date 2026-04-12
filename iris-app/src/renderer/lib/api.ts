import type { ProjectInfo, PlotSidecar } from '../types'

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

  projectUpload: async (name: string, files: FileList): Promise<number> => {
    const form = new FormData()
    for (let i = 0; i < files.length; i++) form.append('files', files[i])
    const res = await fetch(`${BASE}/api/projects/upload?name=${encodeURIComponent(name)}`, {
      method: 'POST',
      body: form,
    })
    const data = await res.json()
    return data.count
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

  // Memory
  projectMemory: async (name: string): Promise<string> => {
    const res = await fetch(`${BASE}/api/projects/memory?name=${encodeURIComponent(name)}`)
    const data = await res.json()
    return data.content || ''
  },

  projectMemorySave: async (name: string, content: string): Promise<boolean> => {
    const res = await fetch(`${BASE}/api/projects/memory`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, content })
    })
    return res.ok
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
