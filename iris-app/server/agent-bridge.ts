type BroadcastFn = (type: string, data: unknown) => void

// Claude Code SDK needs git-bash on Windows
import { accessSync } from 'fs'
import { readFile } from 'fs/promises'
import { execSync } from 'child_process'
import { resolve } from 'path'
import { getIrisRoot } from './lib/paths.js'

if (!process.env.CLAUDE_CODE_GIT_BASH_PATH) {
  // Try to locate bash via PATH (use `where` on Windows, `which` elsewhere)
  const locateCmd = process.platform === 'win32' ? 'where bash' : 'which bash'
  try {
    const bashPath = execSync(locateCmd, { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'pipe'] })
      .split(/\r?\n/)[0].trim()
    if (bashPath) process.env.CLAUDE_CODE_GIT_BASH_PATH = bashPath
  } catch {}

  // Fall back to known Windows install locations
  if (!process.env.CLAUDE_CODE_GIT_BASH_PATH) {
    for (const p of [
      'D:\\Apps\\Git\\bin\\bash.exe',
      'C:\\Program Files\\Git\\bin\\bash.exe',
      'C:\\Program Files (x86)\\Git\\bin\\bash.exe',
    ]) {
      try { accessSync(p); process.env.CLAUDE_CODE_GIT_BASH_PATH = p; break } catch {}
    }
  }
}

let queryFn: typeof import('@anthropic-ai/claude-code').query | null = null

async function getQuery() {
  if (!queryFn) {
    const mod = await import('@anthropic-ai/claude-code')
    queryFn = mod.query
  }
  return queryFn
}

let abortController: AbortController | null = null

// Per-project session tracking: each project gets its own persistent session
const projectSessions = new Map<string, string>()

/** Extract a YAML value that may be single-line or a block scalar (|) */
function extractYamlValue(content: string, key: string): string {
  // Match "key: value" (single-line, not null)
  const singleLine = content.match(new RegExp(`^${key}:\\s+(?!\\|)(.+)$`, 'm'))
  if (singleLine) {
    const val = singleLine[1].replace(/#.*/, '').trim()
    return val === 'null' ? '' : val
  }
  // Match block scalar "key: |" followed by indented lines
  const blockMatch = content.match(new RegExp(`^${key}:\\s*\\|\\s*\\n((?:[ \\t]+.+\\n?)*)`, 'm'))
  if (blockMatch) {
    return blockMatch[1].replace(/^  /gm, '').trim()
  }
  return ''
}

async function buildSystemPrompt(projectName: string, cwd: string): Promise<string> {
  const irisRoot = getIrisRoot()
  const parts: string[] = []

  // Base identity
  parts.push(
    `You are IRIS, an AI data analysis assistant working in project "${projectName}" at ${cwd}. ` +
    `The user's uploaded data files are in the input_data/ subdirectory. ` +
    `Do NOT check .iris/active_project — you are already in the correct project. ` +
    `Focus on helping the user analyze their data.`
  )

  // Global rules from configs/agent_rules.yaml
  try {
    const rulesRaw = await readFile(resolve(irisRoot, 'configs', 'agent_rules.yaml'), 'utf-8')
    const rules = extractYamlValue(rulesRaw, 'rules')
    if (rules) parts.push(`## Global Rules\n${rules}`)
  } catch {}

  // Per-project agent_notes from claude_config.yaml
  try {
    const configRaw = await readFile(resolve(cwd, 'claude_config.yaml'), 'utf-8')
    const notes = extractYamlValue(configRaw, 'agent_notes')
    if (notes) parts.push(`## Project Instructions\n${notes}`)
  } catch {}

  // Per-project memory.yaml
  try {
    const memoryRaw = await readFile(resolve(cwd, 'memory.yaml'), 'utf-8')
    if (memoryRaw.trim()) {
      const truncated = memoryRaw.length > 3200
        ? memoryRaw.slice(0, 3200) + '\n[... truncated]'
        : memoryRaw
      parts.push(`## Project Memory\n${truncated}`)
    }
  } catch {}

  return parts.join('\n\n')
}

export async function sendMessage(prompt: string, broadcast: BroadcastFn, projectName?: string): Promise<void> {
  const query = await getQuery()
  abortController = new AbortController()

  broadcast('agent:status', 'thinking')

  // Resolve session for this project
  const sessionKey = projectName || '__global__'
  const existingSessionId = projectSessions.get(sessionKey) ?? null

  const irisRoot = getIrisRoot()
  const cwd = projectName
    ? resolve(irisRoot, 'projects', projectName)
    : irisRoot

  // Strip VSCode IPC env vars so the SDK subprocess doesn't connect to the IDE.
  // We delete from process.env directly (and restore after) because Windows
  // process.env has special case-insensitive handling that a plain object loses,
  // which breaks PATH resolution and causes "spawn node ENOENT".
  const strippedVars: Record<string, string> = {}
  for (const key of Object.keys(process.env)) {
    if (/^VSCODE_/i.test(key) && process.env[key] != null) {
      strippedVars[key] = process.env[key]!
      delete process.env[key]
    }
  }

  try {
    const systemPrompt = projectName
      ? await buildSystemPrompt(projectName, cwd)
      : undefined

    const messages = query({
      prompt,
      options: {
        cwd,
        additionalDirectories: [irisRoot],
        allowedTools: ['Bash', 'Read', 'Edit', 'Write', 'Glob', 'Grep'],
        permissionMode: 'bypassPermissions',
        maxTurns: 30,
        abortController,
        ...(systemPrompt ? { appendSystemPrompt: systemPrompt } : {}),
        ...(existingSessionId ? { resume: existingSessionId } : {})
      }
    })

    for await (const msg of messages) {
      if (msg.type === 'system' && 'subtype' in msg && (msg as any).subtype === 'init') {
        const newSessionId = (msg as any).session_id ?? null
        if (newSessionId) {
          projectSessions.set(sessionKey, newSessionId)
        }
      }

      broadcast('agent:message', JSON.parse(JSON.stringify(msg)))
    }
  } catch (err: any) {
    if (err.name === 'AbortError') {
      broadcast('agent:message', { type: 'system', content: 'Aborted by user.' })
    } else {
      broadcast('agent:message', { type: 'system', content: `Error: ${err.message}` })
    }
  } finally {
    // Restore stripped VSCode env vars
    for (const [k, v] of Object.entries(strippedVars)) {
      process.env[k] = v
    }
    abortController = null
    broadcast('agent:status', 'idle')
  }
}

export function abortAgent(): void {
  abortController?.abort()
}
