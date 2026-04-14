import { describe, it, expect } from 'vitest'
import {
  approximateTokens,
  clearToolResults,
  formatClearingStub,
  DEFAULT_CLEAR_THRESHOLD_TOKENS,
  type SdkMessage,
} from '../services/tool-result-clearing.js'

/** Build a user-role message containing one tool_result block. */
function makeToolResultMessage(toolUseId: string, content: string): SdkMessage {
  return {
    type: 'user',
    message: {
      content: [
        {
          type: 'tool_result',
          tool_use_id: toolUseId,
          content,
        },
      ],
    },
  }
}

/** Build an assistant message containing one tool_use block. */
function makeToolUseMessage(toolUseId: string, name = 'Bash'): SdkMessage {
  return {
    type: 'assistant',
    message: {
      content: [
        { type: 'tool_use', id: toolUseId, name, input: { cmd: 'ls' } },
        { type: 'text', text: 'running it' },
      ],
    },
  }
}

describe('formatClearingStub', () => {
  it('uses the first non-empty line, capped at 120 chars, and cites the tool_call id', () => {
    const stub = formatClearingStub('tc1', '\n\nfirst real line\nsecond line\n')
    expect(stub).toBe(
      '[Tool result cleared. Summary: first real line. Full output retained as tool_call tc1.]',
    )
  })

  it('falls back to <empty output> on blank input', () => {
    expect(formatClearingStub('tc2', '   \n\t\n')).toContain('<empty output>')
  })

  it('matches the Python helper wire format exactly', () => {
    // Must stay in sync with iris.projects.tool_calls.summarize_for_clearing.
    const stub = formatClearingStub('abc123', 'hello world')
    expect(stub).toBe(
      '[Tool result cleared. Summary: hello world. Full output retained as tool_call abc123.]',
    )
  })
})

describe('approximateTokens', () => {
  it('returns ceil(len/4)', () => {
    expect(approximateTokens('')).toBe(0)
    expect(approximateTokens('abcd')).toBe(1)
    expect(approximateTokens('abcde')).toBe(2)
  })
})

describe('clearToolResults', () => {
  it('skips tool_results whose content is below the threshold', () => {
    const small = 'short output'
    const msgs = [makeToolResultMessage('tu1', small)]
    const out = clearToolResults(msgs, ['tu1'], { thresholdTokens: 500 })
    // Below threshold → returned identical.
    expect(out[0]).toBe(msgs[0])
  })

  it('replaces only tool_results over the threshold, preserving tool_use blocks', () => {
    const big = 'x'.repeat(DEFAULT_CLEAR_THRESHOLD_TOKENS * 4 + 100) // ~500+ tokens
    const msgs: SdkMessage[] = [
      makeToolUseMessage('tu1'),
      makeToolResultMessage('tu1', big),
    ]
    const out = clearToolResults(msgs, ['tu1'])

    // tool_use untouched.
    const toolUseBlock = (out[0].message!.content as any[])[0]
    expect(toolUseBlock).toMatchObject({ type: 'tool_use', id: 'tu1' })

    // tool_result replaced by a text stub.
    const replaced = (out[1].message!.content as any[])[0]
    expect(replaced.type).toBe('text')
    expect(replaced.text).toContain('Tool result cleared')
    expect(replaced.text).toContain('tool_call tu1')
  })

  it('handles multiple tool_results in a single message, clearing only matching ids', () => {
    const big = 'y'.repeat(3000)
    const msg: SdkMessage = {
      type: 'user',
      message: {
        content: [
          { type: 'tool_result', tool_use_id: 'tu1', content: big },
          { type: 'tool_result', tool_use_id: 'tu2', content: big },
          { type: 'tool_result', tool_use_id: 'tu3', content: big },
        ],
      },
    }
    const out = clearToolResults([msg], ['tu1', 'tu3'])
    const blocks = out[0].message!.content as any[]
    expect(blocks[0].type).toBe('text')
    expect(blocks[0].text).toContain('tu1')
    expect(blocks[1].type).toBe('tool_result') // not in clear set
    expect(blocks[1].tool_use_id).toBe('tu2')
    expect(blocks[2].type).toBe('text')
    expect(blocks[2].text).toContain('tu3')
  })

  it('leaves non-matching ids untouched', () => {
    const big = 'z'.repeat(3000)
    const msgs = [makeToolResultMessage('tu_other', big)]
    const out = clearToolResults(msgs, ['tu1'])
    expect(out[0]).toBe(msgs[0])
  })

  it('is idempotent — applying twice yields the same result', () => {
    const big = 'w'.repeat(3000)
    const msgs = [makeToolUseMessage('tu1'), makeToolResultMessage('tu1', big)]
    const once = clearToolResults(msgs, ['tu1'])
    const twice = clearToolResults(once, ['tu1'])
    expect(JSON.stringify(twice)).toEqual(JSON.stringify(once))
  })

  it('does not mutate the input array or message objects', () => {
    const big = 'q'.repeat(3000)
    const original = makeToolResultMessage('tu1', big)
    const snapshot = JSON.stringify(original)
    clearToolResults([original], ['tu1'])
    expect(JSON.stringify(original)).toEqual(snapshot)
  })

  it('handles tool_result content arrays (SDK sometimes sends array-shaped bodies)', () => {
    const chunk = 'p'.repeat(3000)
    const msg: SdkMessage = {
      type: 'user',
      message: {
        content: [
          {
            type: 'tool_result',
            tool_use_id: 'tu1',
            content: [{ type: 'text', text: chunk }],
          },
        ],
      },
    }
    const out = clearToolResults([msg], ['tu1'])
    const block = out[0].message!.content as any[]
    expect(block[0].type).toBe('text')
    expect(block[0].text).toContain('Tool result cleared')
  })

  it('returns the original array when the clear set is empty', () => {
    const msgs = [makeToolResultMessage('tu1', 'x'.repeat(3000))]
    const out = clearToolResults(msgs, [])
    expect(out).toBe(msgs)
  })

  it('honours a custom stub formatter', () => {
    const big = 'r'.repeat(3000)
    const msgs = [makeToolResultMessage('tu1', big)]
    const out = clearToolResults(msgs, ['tu1'], {
      stubFormatter: (id) => `CLEARED:${id}`,
    })
    const block = (out[0].message!.content as any[])[0]
    expect(block).toEqual({ type: 'text', text: 'CLEARED:tu1' })
  })
})
