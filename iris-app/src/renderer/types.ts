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
  iris_version: string
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

export type WorkspaceTab = 'plots' | 'report' | 'files' | 'memory' | 'curation' | 'behavior'

export type SectionStatus = 'draft' | 'approved' | 'needs-revision'

export interface ReportSection {
  id: string
  heading: string
  content: string
  status: SectionStatus
  userNotes?: string
}

export interface ProfileColumn {
  name: string
  dtype?: string
  nulls?: number
  min?: number | string | null
  max?: number | string | null
  mean?: number | null
  std?: number | null
  unique?: number
  values?: string[]
}

export interface FileProfile {
  kind?: string
  path?: string
  name?: string
  bytes?: number
  mtime?: string
  suffix?: string
  shape?: number[]
  sampled?: boolean
  columns?: ProfileColumn[]
  datasets?: Array<{ name: string; shape: number[]; dtype: string }>
  arrays?: Record<string, { shape: number[]; dtype: string }>
  variables?: Record<string, { shape: number[]; dtype: string }>
  tables?: Record<string, { columns: Array<{ name: string; type: string }>; rows: number | null }>
  keys?: string[]
  top_type?: string
  error?: string
  note?: string
  sample_head?: string
}

export interface UploadedProfile {
  name: string
  path: string
  profile: FileProfile | null
  error?: string
}

export interface UploadResult {
  count: number
  profiles: UploadedProfile[]
}

export interface FileNode {
  name: string
  path: string
  type: 'file' | 'dir'
  size: number
  children?: FileNode[]
}
