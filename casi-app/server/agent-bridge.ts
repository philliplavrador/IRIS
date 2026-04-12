type BroadcastFn = (type: string, data: unknown) => void

// Claude Code SDK needs git-bash on Windows
import { accessSync } from 'fs'
import { execSync } from 'child_process'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

if (!process.env.CLAUDE_CODE_GIT_BASH_PATH) {
  // Try `which bash` first (works when git is on PATH)
  try {
    const bashPath = execSync('which bash', { encoding: 'utf-8' }).trim()
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

export async function sendMessage(prompt: string, broadcast: BroadcastFn, projectName?: string): Promise<void> {
  const query = await getQuery()
  abortController = new AbortController()

  broadcast('agent:status', 'thinking')

  // Resolve session for this project
  const sessionKey = projectName || '__global__'
  const existingSessionId = projectSessions.get(sessionKey) ?? null

  try {
    const messages = query({
      prompt,
      options: {
        cwd: process.env.CASI_ROOT || resolve(__dirname, '..', '..', '..'),
        allowedTools: ['Bash', 'Read', 'Edit', 'Write', 'Glob', 'Grep'],
        permissionMode: 'bypassPermissions',
        maxTurns: 30,
        abortController,
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
    abortController = null
    broadcast('agent:status', 'idle')
  }
}

export function abortAgent(): void {
  abortController?.abort()
}
