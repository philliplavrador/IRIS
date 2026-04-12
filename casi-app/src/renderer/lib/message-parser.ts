import type { ChatMessage, ToolUseInfo } from '../types'

let messageCounter = 0

function nextId(): string {
  return `msg-${Date.now()}-${++messageCounter}`
}

export function extractPlotPaths(text: string): string[] {
  const paths: string[] = []
  const regex = /(?:[a-zA-Z]:[\\/]|[\\/])?(?:[\w.\-]+[\\/])*plot[_\w\-]*\.\w{3,4}/g
  const matches = text.match(regex)
  if (matches) {
    for (const m of matches) {
      if (/\.(png|pdf|svg)$/i.test(m)) {
        paths.push(m)
      }
    }
  }
  return [...new Set(paths)]
}

export function processAgentMessage(msg: any): {
  action: 'add' | 'update' | 'ignore'
  message?: ChatMessage
  update?: Partial<ChatMessage>
} {
  if (msg.type === 'assistant' && msg.message?.content) {
    const textBlocks = msg.message.content.filter((b: any) => b.type === 'text')
    const toolBlocks = msg.message.content.filter((b: any) => b.type === 'tool_use')

    const content = textBlocks.map((b: any) => b.text).join('\n')
    const toolUse: ToolUseInfo[] = toolBlocks.map((b: any) => ({
      tool: b.name,
      input: typeof b.input === 'string' ? b.input : JSON.stringify(b.input, null, 2),
    }))

    const plots = extractPlotPaths(content)

    return {
      action: 'add',
      message: {
        id: nextId(),
        role: 'assistant',
        content,
        timestamp: Date.now(),
        toolUse: toolUse.length > 0 ? toolUse : undefined,
        plots: plots.length > 0 ? plots : undefined,
      }
    }
  }

  if (msg.type === 'result') {
    const resultContent = typeof msg.result === 'string' ? msg.result : JSON.stringify(msg.result)
    const plots = extractPlotPaths(resultContent)

    if (plots.length > 0) {
      return { action: 'update', update: { plots } }
    }
    return { action: 'ignore' }
  }

  if (msg.type === 'system') {
    if (msg.content) {
      return {
        action: 'add',
        message: {
          id: nextId(),
          role: 'system',
          content: msg.content,
          timestamp: Date.now(),
        }
      }
    }
    return { action: 'ignore' }
  }

  return { action: 'ignore' }
}
