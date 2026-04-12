type BroadcastFn = (type: string, data: unknown) => void

// Claude Code SDK needs git-bash on Windows
import { accessSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

if (!process.env.CLAUDE_CODE_GIT_BASH_PATH) {
  for (const p of [
    'D:\\Apps\\Git\\bin\\bash.exe',
    'C:\\Program Files\\Git\\bin\\bash.exe',
    'C:\\Program Files (x86)\\Git\\bin\\bash.exe',
  ]) {
    try { accessSync(p); process.env.CLAUDE_CODE_GIT_BASH_PATH = p; break } catch {}
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
let sessionId: string | null = null

export async function sendMessage(prompt: string, broadcast: BroadcastFn): Promise<void> {
  const query = await getQuery()
  abortController = new AbortController()

  broadcast('agent:status', 'thinking')

  try {
    const messages = query({
      prompt,
      options: {
        cwd: process.env.CASI_ROOT || resolve(__dirname, '..', '..', '..'),
        allowedTools: ['Bash', 'Read', 'Edit', 'Write', 'Glob', 'Grep'],
        permissionMode: 'bypassPermissions',
        maxTurns: 30,
        abortController,
        ...(sessionId ? { resume: sessionId } : {})
      }
    })

    for await (const msg of messages) {
      if (msg.type === 'system' && 'subtype' in msg && (msg as any).subtype === 'init') {
        sessionId = (msg as any).session_id ?? null
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
