type BroadcastFn = (type: string, data: unknown) => void

// Claude Code SDK needs git-bash on Windows
import { accessSync } from 'fs'
import { readFile } from 'fs/promises'
import { execSync } from 'child_process'
import { resolve } from 'path'
import { getIrisRoot } from './lib/paths.js'
import { daemonPost } from './services/daemon-client.js'
import {
  approximateTokens,
  clearToolResults,
  DEFAULT_CLEAR_THRESHOLD_TOKENS,
  type SdkMessage,
} from './services/tool-result-clearing.js'

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

// Per-project memory-layer session tracking (REVAMP Task 2.5). Distinct from
// the Claude Code SDK session above: this id is the `sessions.session_id`
// row created by POST /api/memory/sessions/start and is what every later
// memory write (messages, tool_calls, memory_entries, runs) carries so queries
// can scope to one conversation. Naming follows server/CLAUDE.md §3 —
// { sdkSessionId, memorySessionId } pair.
const projectMemorySessions = new Map<string, string>()

const CLAUDE_MODEL_PROVIDER = 'anthropic'
// The Claude Code SDK selects the model based on the user's Max subscription;
// we don't have a reliable "which model answered" signal in the stream yet,
// so we stamp the configured default here. When the SDK surfaces the model
// in its init message we can replace this with the reported id.
const CLAUDE_MODEL_NAME = process.env.IRIS_CLAUDE_MODEL ?? 'claude-sonnet-4-5'

/**
 * Ensure the daemon's active-project pointer matches `projectName`. The
 * memory-session endpoints resolve the active project server-side, so we
 * must flip it before starting/ending a session. Failures are logged and
 * swallowed — memory-session lifecycle is best-effort and must never block
 * the chat stream.
 */
async function ensureActiveProject(projectName: string): Promise<void> {
  try {
    await daemonPost('/api/projects/active', { name: projectName })
  } catch (err: any) {
    console.error('[agent-bridge] activate project failed:', err?.message ?? err)
  }
}

/**
 * Start a memory-layer session for `projectName` if one isn't already open.
 * Writes the returned session_id into `projectMemorySessions` and returns it.
 * Never throws — returns null on failure so the caller can continue without
 * memory-session scoping.
 */
async function startMemorySession(
  projectName: string,
  systemPrompt: string,
): Promise<string | null> {
  const existing = projectMemorySessions.get(projectName)
  if (existing) return existing
  try {
    await ensureActiveProject(projectName)
    const resp = await daemonPost<{ data: { session_id: string } }>(
      '/api/memory/sessions/start',
      {
        model_provider: CLAUDE_MODEL_PROVIDER,
        model_name: CLAUDE_MODEL_NAME,
        system_prompt: systemPrompt,
      },
    )
    const sid = resp?.data?.session_id
    if (sid) {
      projectMemorySessions.set(projectName, sid)
      return sid
    }
    return null
  } catch (err: any) {
    console.error('[agent-bridge] start memory session failed:', err?.message ?? err)
    return null
  }
}

/**
 * Close the memory-layer session bound to `projectName`, if any. Called when
 * the SDK reports a different session_id than the one we cached (treated as
 * "new conversation") and from the exported `endMemorySession` hook so
 * higher layers (e.g., the /api/agent/abort route, explicit "new chat"
 * actions) can force a close.
 */
async function endMemorySessionInternal(
  projectName: string,
  summary: string,
): Promise<void> {
  const sid = projectMemorySessions.get(projectName)
  if (!sid) return
  projectMemorySessions.delete(projectName)
  clearPendingForProject(projectName)
  clearCacheForProject(projectName)
  try {
    await ensureActiveProject(projectName)
    await daemonPost(
      `/api/memory/sessions/${encodeURIComponent(sid)}/end`,
      { summary },
    )
  } catch (err: any) {
    console.error('[agent-bridge] end memory session failed:', err?.message ?? err)
  }
}

/** Public hook: end the memory-layer session tied to `projectName`. */
export async function endMemorySession(
  projectName: string,
  summary = 'conversation closed',
): Promise<void> {
  await endMemorySessionInternal(projectName, summary)
}

/** Test-only: read the currently-tracked memory session_id for a project. */
export function getMemorySessionId(projectName: string): string | undefined {
  return projectMemorySessions.get(projectName)
}

/**
 * Per-turn persistence (REVAMP Task 3.5). Every assistant message lands in
 * ``messages``; every tool_use/tool_result pair lands in ``tool_calls``.
 *
 * tool_use and tool_result can arrive in separate SDK messages. We buffer the
 * ``tool_use`` input on first sight and flush one ``POST /memory/tool_calls``
 * when the matching ``tool_result`` block arrives — so the row hits SQLite
 * with success + output_summary in a single insert (the Python API takes
 * those fields up front; see ``tool_calls.append_tool_call``). If a
 * conversation ends before the result returns, ``pendingToolCalls`` is
 * cleared by ``endMemorySessionInternal`` to prevent cross-session leaks.
 */
type PendingToolCall = {
  projectName: string
  tool_name: string
  input: unknown
  started_at: number
}
const pendingToolCalls = new Map<string, PendingToolCall>() // key: SDK tool_use_id

/**
 * REVAMP Task 3.6 — Tool-result clearing (spec §9.3).
 *
 * The Claude Code SDK does not let us mutate its in-flight conversation
 * buffer, so we maintain our own append-only cache of SDK messages keyed by
 * project. After a tool_result lands, if its serialized content exceeds the
 * configured threshold we rewrite the cached copy (via `clearToolResults`)
 * to a one-line stub. The memory-layer slice + websocket-replay paths read
 * from this cache, so every later turn sees the compacted form.
 *
 * TODO: once Express has a TOML parser, read the threshold from
 * `[agent.dials].clear_tool_results_above_tokens` in configs/config.toml
 * instead of falling back to the in-module default.
 */
const projectMessageCache = new Map<string, SdkMessage[]>()

function appendToCache(projectName: string, msg: SdkMessage): void {
  const arr = projectMessageCache.get(projectName) ?? []
  arr.push(msg)
  projectMessageCache.set(projectName, arr)
}

function clearCacheForProject(projectName: string): void {
  projectMessageCache.delete(projectName)
}

/** Test-only: read the cached SDK messages for a project. */
export function getCachedMessages(projectName: string): SdkMessage[] {
  return projectMessageCache.get(projectName) ?? []
}

/**
 * Rewrite cached copies of tool_result blocks for `toolUseIds` that blow the
 * size budget. Called after the matching tool_result has been persisted so
 * the durable copy lives in SQLite/artifacts before we swap the in-memory
 * buffer for a stub. Pure-function logic lives in services/tool-result-clearing.
 */
function maybeClearToolResultsFromCache(
  projectName: string,
  toolUseIds: string[],
  thresholdTokens: number = DEFAULT_CLEAR_THRESHOLD_TOKENS,
): void {
  if (toolUseIds.length === 0) return
  const arr = projectMessageCache.get(projectName)
  if (!arr || arr.length === 0) return
  const next = clearToolResults(arr, toolUseIds, { thresholdTokens })
  if (next !== arr) projectMessageCache.set(projectName, next)
}

function firstLine(text: string, maxChars: number): string {
  const line = (text ?? '').split(/\r?\n/).map((s) => s.trim()).find((s) => s.length > 0) ?? ''
  return line.length > maxChars ? line.slice(0, maxChars - 1) + '\u2026' : line
}

function postMessageRow(
  memorySessionId: string,
  role: 'user' | 'assistant' | 'tool' | 'system',
  content: string,
): void {
  if (!content) return
  daemonPost<{ data: { message_id: string } }>('/api/memory/messages', {
    session_id: memorySessionId,
    role,
    content,
  })
    .then((resp) => {
      // REVAMP Task 12.2: fire-and-forget per-turn extraction on
      // substantive assistant messages (skip short control tokens).
      if (role !== 'assistant') return
      if (!content || content.length < 80) return
      const messageId = resp?.data?.message_id
      if (!messageId) return
      daemonPost('/api/memory/extract/turn', { message_id: messageId }).catch(
        () => {
          // Silent — extraction is best-effort; missing API key or
          // daemon transients must never block chat.
        },
      )
    })
    .catch((err: any) => {
      console.error('[agent-bridge] append message failed:', err?.message ?? err)
    })
}

function recordToolUse(
  projectName: string,
  tool_use_id: string,
  tool_name: string,
  input: unknown,
): void {
  pendingToolCalls.set(tool_use_id, {
    projectName,
    tool_name,
    input,
    started_at: Date.now(),
  })
}

function finalizeToolCall(
  memorySessionId: string,
  tool_use_id: string,
  rawContent: string,
  isError: boolean,
): void {
  const pending = pendingToolCalls.get(tool_use_id)
  if (!pending) return
  pendingToolCalls.delete(tool_use_id)
  const summary = firstLine(rawContent, 240) || '<empty output>'
  daemonPost('/api/memory/tool_calls', {
    session_id: memorySessionId,
    tool_name: pending.tool_name,
    input: pending.input,
    success: !isError,
    output_summary: summary,
    error: isError ? summary : null,
    execution_time_ms: Date.now() - pending.started_at,
  }).catch((err: any) => {
    console.error('[agent-bridge] append tool_call failed:', err?.message ?? err)
  })
}

function clearPendingForProject(projectName: string): void {
  for (const [id, p] of pendingToolCalls) {
    if (p.projectName === projectName) pendingToolCalls.delete(id)
  }
}

/** Persist an SDK message to the memory layer. Fire-and-forget. */
function persistSdkMessage(projectName: string, memorySessionId: string, msg: any): void {
  if (!msg || typeof msg !== 'object') return
  if (msg.type === 'assistant' && msg.message?.content) {
    const blocks = msg.message.content as any[]
    const textParts: string[] = []
    for (const b of blocks) {
      if (b?.type === 'text' && typeof b.text === 'string') {
        textParts.push(b.text)
      } else if (b?.type === 'tool_use' && typeof b.id === 'string') {
        recordToolUse(projectName, b.id, String(b.name ?? ''), b.input)
      }
    }
    const text = textParts.join('\n').trim()
    if (text) postMessageRow(memorySessionId, 'assistant', text)
    return
  }
  if (msg.type === 'user' && msg.message?.content) {
    const blocks = msg.message.content as any[]
    const textParts: string[] = []
    const toClear: string[] = []
    for (const b of blocks) {
      if (b?.type === 'tool_result' && typeof b.tool_use_id === 'string') {
        const content =
          typeof b.content === 'string' ? b.content : JSON.stringify(b.content)
        finalizeToolCall(memorySessionId, b.tool_use_id, content, b.is_error === true)
        // REVAMP Task 3.6: flag oversized tool_results for in-cache clearing.
        if (approximateTokens(content) > DEFAULT_CLEAR_THRESHOLD_TOKENS) {
          toClear.push(b.tool_use_id)
        }
      } else if (b?.type === 'text' && typeof b.text === 'string') {
        textParts.push(b.text)
      }
    }
    const text = textParts.join('\n').trim()
    if (text) postMessageRow(memorySessionId, 'tool', text)
    if (toClear.length) maybeClearToolResultsFromCache(projectName, toClear)
  }
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

/**
 * Assemble the system prompt from the daemon's 7-segment slice builder
 * (REVAMP Task 9.5, spec §9.1). Segments land in spec order so the stable
 * prefix (system_prompt, core_memory, dataset_context) sits first for
 * Anthropic prompt-cache efficiency.
 *
 * Agent dials now live in [agent.dials] of configs/config.toml and are
 * rendered into segment 1 by slice_builder — no YAML dial block here.
 */
async function buildSystemPrompt(
  projectName: string,
  _cwd: string,
  currentQuery: string,
  memorySessionId?: string,
): Promise<string> {
  try {
    await ensureActiveProject(projectName)
    const resp = await daemonPost<{
      data: {
        segments: Array<{ name: string; content: string; token_count: number }>
        total_tokens: number
        retrieval_skipped: boolean
      }
    }>('/api/memory/slice', {
      session_id: memorySessionId ?? '',
      current_query: currentQuery,
    })
    const segments = resp?.data?.segments ?? []
    const parts: string[] = []
    for (const seg of segments) {
      if (seg.content && seg.content.trim()) parts.push(seg.content)
    }
    if (parts.length === 0) {
      return `You are IRIS, a project-scoped AI analysis partner working in project "${projectName}".`
    }
    return parts.join('\n\n')
  } catch {
    return `You are IRIS, a project-scoped AI analysis partner working in project "${projectName}".`
  }
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
      ? await buildSystemPrompt(projectName, cwd, prompt, projectMemorySessions.get(projectName))
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

    // memorySessionPromise resolves to the memory-layer session_id once the
    // daemon has opened it. All persistence calls chain off this promise so
    // late-arriving messages still land in the right session — and we never
    // block the SDK stream waiting for it.
    let memorySessionPromise: Promise<string | null> = Promise.resolve(null)
    let userTurnLogged = false
    for await (const msg of messages) {
      if (msg.type === 'system' && 'subtype' in msg && (msg as any).subtype === 'init') {
        const newSessionId = (msg as any).session_id ?? null
        if (newSessionId) {
          // REVAMP Task 2.5: if the SDK reports a *different* session id than
          // the one we had cached, the previous conversation is over. Close
          // its memory-layer session before opening a new one so the events
          // table records a clean session_started/session_ended pair.
          if (
            projectName &&
            existingSessionId &&
            existingSessionId !== newSessionId
          ) {
            // fire-and-forget; do not block the stream on the end call
            endMemorySessionInternal(
              projectName,
              'SDK started a new session',
            ).catch(() => {})
          }
          projectSessions.set(sessionKey, newSessionId)
        }
        // REVAMP Task 2.5 + 3.5: open a memory-layer session on the first
        // init of a conversation. The returned promise is reused by every
        // later persistSdkMessage call so writes scope to the right session
        // even if the daemon round-trip hasn't completed yet.
        if (projectName && systemPrompt) {
          memorySessionPromise = startMemorySession(projectName, systemPrompt)
        }
        // Log the user prompt as the opening message row.
        if (projectName && !userTurnLogged) {
          userTurnLogged = true
          memorySessionPromise.then((sid) => {
            if (sid) postMessageRow(sid, 'user', prompt)
          })
        }
      }

      // REVAMP Task 3.5: persist every assistant message + tool call to the
      // memory layer. Fire-and-forget — failures log but never break chat.
      if (projectName) {
        const captured = msg
        // REVAMP Task 3.6: keep a per-project SDK message cache so later
        // turns (and the slice builder) see cleared tool_result bodies.
        appendToCache(projectName, captured as SdkMessage)
        memorySessionPromise.then((sid) => {
          if (sid) persistSdkMessage(projectName, sid, captured)
        })
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
