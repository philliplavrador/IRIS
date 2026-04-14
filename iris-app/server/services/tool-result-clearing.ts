/**
 * Tool-result clearing (spec §9.3, REVAMP Task 3.6).
 *
 * Pure-function compaction of an SDK-shaped conversation-message array. When a
 * tool_result block's content exceeds the configured token threshold, it is
 * replaced with a one-line stub whose wire format matches the Python helper
 * `iris.projects.tool_calls.summarize_for_clearing` (so the stub is stable
 * across the Express/daemon boundary). The original `tool_use` block stays
 * intact — callers that need the full output can resolve it via the
 * content-addressed artifacts store keyed by `tool_call_id`.
 *
 * The Claude Code SDK does not expose its internal conversation buffer for
 * direct mutation; this helper is therefore applied to the copy of the
 * message stream that the agent-bridge forwards to the websocket + memory
 * layer, not to the SDK's own buffer. See agent-bridge.ts for the wiring.
 */

// TODO: read `[agent.dials].clear_tool_results_above_tokens` from
// configs/config.toml once Express gains a TOML parser. Until then this
// mirror of the Python default in iris.config must be kept in sync by hand.
export const DEFAULT_CLEAR_THRESHOLD_TOKENS = 500

/**
 * Rough token estimate — 4 characters per token is the standard GPT-style
 * heuristic and is good enough for a threshold check. We deliberately do not
 * pull a tokenizer: this helper must be sync + dependency-free to keep the
 * unit-test surface small.
 */
export function approximateTokens(text: string): number {
  return Math.ceil((text?.length ?? 0) / 4)
}

/** Produce the stub text substituted for a cleared tool_result body. */
export function formatClearingStub(toolCallId: string, outputText: string): string {
  const summary = firstNonEmptyLine(outputText, 120)
  return (
    `[Tool result cleared. Summary: ${summary}. ` +
    `Full output retained as tool_call ${toolCallId}.]`
  )
}

function firstNonEmptyLine(text: string, maxChars: number): string {
  const lines = (text ?? '').split(/\r?\n/)
  for (const raw of lines) {
    const s = raw.trim()
    if (s) {
      return s.length > maxChars ? s.slice(0, maxChars - 1) + '\u2026' : s
    }
  }
  return '<empty output>'
}

/**
 * Minimal shape of the SDK user/assistant message as it appears in the
 * `query()` async iterator. We model only the pieces we touch — the rest is
 * preserved verbatim via spread copies.
 */
export type SdkContentBlock =
  | { type: 'text'; text: string }
  | { type: 'tool_use'; id: string; name?: string; input?: unknown }
  | {
      type: 'tool_result'
      tool_use_id: string
      content: unknown // string | Array<{type:'text'; text:string}> | etc.
      is_error?: boolean
    }
  | { type: string; [key: string]: unknown }

export type SdkMessage = {
  type: string
  message?: {
    content?: SdkContentBlock[]
    [key: string]: unknown
  }
  [key: string]: unknown
}

/** Optional per-call stub override — defaults to `formatClearingStub`. */
export type StubFormatter = (toolCallId: string, outputText: string) => string

export type ClearOptions = {
  /** Token threshold — results at or below this count stay untouched. */
  thresholdTokens?: number
  /** Custom stub formatter (tests). */
  stubFormatter?: StubFormatter
}

/**
 * Return a new message array where every `tool_result` block whose
 * `tool_use_id` is in `idsToClear` and whose content exceeds the threshold
 * has been replaced with a single `{type:'text'}` stub block. `tool_use`
 * blocks are never touched. The input array is not mutated.
 *
 * Idempotent: applying twice yields the same result (the second pass sees
 * text blocks where tool_results used to be, and leaves them alone).
 */
export function clearToolResults(
  messages: SdkMessage[],
  idsToClear: Iterable<string>,
  options: ClearOptions = {},
): SdkMessage[] {
  const idSet = new Set(idsToClear)
  if (idSet.size === 0) return messages
  const threshold = options.thresholdTokens ?? DEFAULT_CLEAR_THRESHOLD_TOKENS
  const formatter = options.stubFormatter ?? formatClearingStub

  return messages.map((msg) => {
    const blocks = msg?.message?.content
    if (!Array.isArray(blocks)) return msg

    let changed = false
    const nextBlocks = blocks.map((block) => {
      if (!block || (block as SdkContentBlock).type !== 'tool_result') return block
      const tr = block as {
        type: 'tool_result'
        tool_use_id: string
        content: unknown
        is_error?: boolean
      }
      if (!idSet.has(tr.tool_use_id)) return block
      const text = toolResultText(tr.content)
      if (approximateTokens(text) <= threshold) return block
      changed = true
      return {
        type: 'text' as const,
        text: formatter(tr.tool_use_id, text),
      }
    })

    if (!changed) return msg
    return {
      ...msg,
      message: { ...msg.message, content: nextBlocks },
    }
  })
}

/**
 * SDK tool_result.content may be a string, an array of text blocks, or an
 * arbitrary JSON value. Normalize to a single string for threshold-checking
 * and stub-summary extraction.
 */
function toolResultText(content: unknown): string {
  if (typeof content === 'string') return content
  if (Array.isArray(content)) {
    return content
      .map((c) => {
        if (typeof c === 'string') return c
        if (c && typeof c === 'object' && 'text' in c && typeof (c as any).text === 'string') {
          return (c as any).text as string
        }
        return JSON.stringify(c)
      })
      .join('\n')
  }
  return JSON.stringify(content ?? '')
}
