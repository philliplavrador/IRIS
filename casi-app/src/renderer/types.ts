export interface ProjectInfo {
  name: string
  path: string
  created_at: string | null
  description: string | null
  n_references: number
  n_outputs: number
}

export interface PlotInfo {
  path: string
  filename: string
  sidecar: PlotSidecar | null
}

export interface PlotSidecar {
  casi_version: string
  timestamp: string
  plot_file: string
  dsl: string
  window_ms: [number, number] | 'full'
  ops: Array<{ name: string; params: Record<string, unknown> }>
  sources: Record<string, { path: string; mtime: number; size: number }>
  plot_backend: string
}

export type AgentStatus = 'idle' | 'thinking' | 'tool_use' | 'error'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  toolUse?: ToolUseInfo[]
  plots?: string[]
  isStreaming?: boolean
}

export interface ToolUseInfo {
  tool: string
  input: string
  output?: string
}

export type WorkspaceTab = 'plots' | 'report' | 'files'

export type SectionStatus = 'draft' | 'approved' | 'needs-revision'

export interface ReportSection {
  id: string
  heading: string
  content: string
  status: SectionStatus
  userNotes?: string
}

export interface FileNode {
  name: string
  path: string
  type: 'file' | 'dir'
  size: number
  children?: FileNode[]
}
