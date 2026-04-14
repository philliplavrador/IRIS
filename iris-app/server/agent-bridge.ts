type BroadcastFn = (type: string, data: unknown) => void

// Claude Code SDK needs git-bash on Windows
import { accessSync } from 'fs'
import { readFile } from 'fs/promises'
import { execSync } from 'child_process'
import { resolve } from 'path'
import { getIrisRoot } from './lib/paths.js'
import { daemonPost } from './services/daemon-client.js'

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

/**
 * L0 conversation logging — fire-and-forget append to the per-session JSONL.
 * §3.1: the one memory that must never be lost. Failures logged, never raised.
 */
function logTurn(
  projectName: string,
  sessionId: string,
  role: 'user' | 'assistant' | 'system' | 'tool',
  text: string,
  extras?: { tool_calls?: unknown[]; tool_results?: unknown[] },
): void {
  daemonPost('/api/memory/append_turn', {
    project: projectName,
    session_id: sessionId,
    role,
    text,
    tool_calls: extras?.tool_calls ?? null,
    tool_results: extras?.tool_results ?? null,
  }).catch((err) => {
    console.error('[agent-bridge] L0 append_turn failed:', err?.message ?? err)
  })
}

/** Extract a logged turn from an SDK message, or null if not loggable. */
function extractTurn(msg: any): {
  role: 'assistant' | 'tool'
  text: string
  tool_calls?: unknown[]
  tool_results?: unknown[]
} | null {
  if (!msg || typeof msg !== 'object') return null
  if (msg.type === 'assistant' && msg.message?.content) {
    const blocks = msg.message.content as any[]
    const textParts: string[] = []
    const tool_calls: unknown[] = []
    for (const b of blocks) {
      if (b?.type === 'text' && typeof b.text === 'string') textParts.push(b.text)
      else if (b?.type === 'tool_use') tool_calls.push({ id: b.id, name: b.name, input: b.input })
    }
    return {
      role: 'assistant',
      text: textParts.join('\n'),
      ...(tool_calls.length ? { tool_calls } : {}),
    }
  }
  if (msg.type === 'user' && msg.message?.content) {
    const blocks = msg.message.content as any[]
    const tool_results: unknown[] = []
    const textParts: string[] = []
    for (const b of blocks) {
      if (b?.type === 'tool_result') {
        tool_results.push({
          tool_use_id: b.tool_use_id,
          content: typeof b.content === 'string' ? b.content : JSON.stringify(b.content),
          is_error: b.is_error ?? false,
        })
      } else if (b?.type === 'text' && typeof b.text === 'string') {
        textParts.push(b.text)
      }
    }
    if (!tool_results.length && !textParts.length) return null
    return {
      role: 'tool',
      text: textParts.join('\n'),
      ...(tool_results.length ? { tool_results } : {}),
    }
  }
  return null
}

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

/**
 * Parse a 2-level-nested mapping like `pushback:\n  statistical: rigorous`.
 * Returns a flat { subkey: value } map. Comments and null values are stripped.
 */
export function extractYamlSubmap(content: string, parentKey: string): Record<string, string> {
  const out: Record<string, string> = {}
  const re = new RegExp(`^${parentKey}:\\s*\\n((?:[ \\t]+[^\\n]*\\n?)+)`, 'm')
  const m = content.match(re)
  if (!m) return out
  const block = m[1]
  for (const line of block.split(/\r?\n/)) {
    const kv = line.match(/^\s+([A-Za-z_][\w-]*):\s*(.+?)\s*(#.*)?$/)
    if (!kv) continue
    const val = kv[2].trim()
    if (val === 'null' || val === '') continue
    out[kv[1]] = val
  }
  return out
}

const AUTONOMY_RUBRIC: Record<string, string> = {
  low:
    'autonomy=low — Only free reads (memory, history, ledger, cache lookups) run without approval. ' +
    'Every op run, every plot, every L3 write must be proposed and approved first.',
  medium:
    'autonomy=medium — Free reads plus cheap profiling and cache-hit retrieval run without approval. ' +
    'New op runs, new plots, new op definitions, and all L3 writes must be proposed and approved.',
  high:
    'autonomy=high — Free reads, profiling, and re-execution of ops already run in this project ' +
    '(cache-addressable or identical params) run without approval. Novel analyses, new op definitions, ' +
    'and L3 writes are still proposed and approved. Autonomy NEVER grants "run without approval for new work."',
}

const PUSHBACK_DOMAIN_SCOPE: Record<string, string> = {
  statistical:
    'assumption violations, sample size, multiple comparisons, effect sizes, CIs, test selection',
  methodological:
    'pipeline ordering, parameter choices, transforms/normalization, train/test leakage, aggregation scope',
  interpretive:
    'causal vs. correlational claims, overgeneralization from the sample, domain-plausibility of results',
}

const PUSHBACK_LEVEL_ACTION: Record<string, string> = {
  light: 'note the concern in a single sentence, then implement anyway',
  balanced: 'flag the concern, propose alternatives, and ask the user to choose before proceeding',
  rigorous: 'refuse to run until the user acknowledges the concern or overrides in writing',
}

/**
 * Render the autonomy + pushback rubric block from a project's claude_config.yaml.
 * Exported for tests. Pure function — no I/O.
 */
export function buildDialsBlock(configRaw: string): string {
  const autonomy = (extractYamlValue(configRaw, 'autonomy') || 'medium').toLowerCase()
  const autonomyLine = AUTONOMY_RUBRIC[autonomy] ?? AUTONOMY_RUBRIC.medium

  const pushback = extractYamlSubmap(configRaw, 'pushback')
  const domains = ['statistical', 'methodological', 'interpretive'] as const
  const pushbackLines = domains.map((d) => {
    const level = (pushback[d] || 'balanced').toLowerCase()
    const action = PUSHBACK_LEVEL_ACTION[level] ?? PUSHBACK_LEVEL_ACTION.balanced
    const scope = PUSHBACK_DOMAIN_SCOPE[d]
    return `- ${d}: ${level} — ${action}. Scope: ${scope}.`
  })

  return (
    `## Behavior Dials\n` +
    `${autonomyLine}\n` +
    `L0 (conversation) and L1 (event ledger) writes are never gated by autonomy — they are automatic at every level.\n\n` +
    `Pushback (self-police concerns in these domains before running):\n` +
    pushbackLines.join('\n') + '\n' +
    `When a domain's level is "rigorous", you must refuse the tool call and say so explicitly; do not execute until the user writes an acknowledgment or override. ` +
    `When "balanced", pause after flagging and wait for the user's choice. When "light", surface the concern in one line, then proceed.`
  )
}

async function buildSystemPrompt(projectName: string, cwd: string): Promise<string> {
  const irisRoot = getIrisRoot()
  const parts: string[] = []

  // Base identity — domain-agnostic. The user's data type is whatever they
  // uploaded; the agent learns meaning from their annotations, not from
  // hard-coded assumptions here.
  parts.push(
    `You are IRIS, a project-scoped AI analysis partner working in project "${projectName}" at ${cwd}. ` +
    `Uploaded data lives in input_data/. You are already in the correct project — do NOT read .iris/active_project. ` +
    `Work is domain-agnostic: never assume a field (neuroscience, finance, marketing, etc.). ` +
    `Semantic meaning of columns/datasets comes from the user's annotations on the data profile, which are summarized below.`
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

    parts.push(buildDialsBlock(configRaw))
  } catch {}

  // Pinned slice — the derived, token-budgeted memory view (L2 last digest +
  // L3 active goals/decisions/facts + confirmed profile annotations). See
  // docs/iris-memory.md §3.6.
  try {
    const slice = await daemonPost<{
      rendered: string
      used_tokens: number
      budget: number
      dropped_sections: string[]
    }>('/api/memory/build_slice', { project: projectName })
    if (slice.rendered && slice.rendered !== '(pinned slice is empty)') {
      parts.push(`## Pinned Memory (${slice.used_tokens}/${slice.budget} tokens)\n${slice.rendered}`)
    }
  } catch {}

  // Retrieval primitive reminder.
  parts.push(
    `## Retrieval\n` +
    `For anything not in the pinned slice above, use the recall() primitive (POST /api/memory/recall) ` +
    `rather than grepping markdown. Returned hits include citation ids like "decision#42" — cite them verbatim. ` +
    `Durable facts/decisions go through propose_* (queued) and commit at session end.`
  )

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

    let userTurnLogged = false
    for await (const msg of messages) {
      if (msg.type === 'system' && 'subtype' in msg && (msg as any).subtype === 'init') {
        const newSessionId = (msg as any).session_id ?? null
        if (newSessionId) {
          projectSessions.set(sessionKey, newSessionId)
        }
        // SDK session_id only becomes known after the first init message,
        // so log the user prompt here (not before query()) to land it in the
        // correct session file.
        if (projectName && !userTurnLogged && newSessionId) {
          logTurn(projectName, newSessionId, 'user', prompt)
          userTurnLogged = true
        }
      }

      // L0 append (§3.1) — fire-and-forget, never blocks the stream.
      if (projectName) {
        const activeSessionId = projectSessions.get(sessionKey)
        if (activeSessionId) {
          const turn = extractTurn(msg)
          if (turn) {
            logTurn(projectName, activeSessionId, turn.role, turn.text, {
              tool_calls: turn.tool_calls,
              tool_results: turn.tool_results,
            })
          }
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
