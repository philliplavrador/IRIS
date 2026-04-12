import { useChatStore } from '../stores/chat-store'
import { useWorkspaceStore } from '../stores/workspace-store'
import { useWebSocket } from './useWebSocket'
import { processAgentMessage } from '../lib/message-parser'
import type { AgentStatus } from '../types'

export function useAgentMessages(): void {
  const addMessage = useChatStore((s) => s.addMessage)
  const updateLastAssistantMessage = useChatStore((s) => s.updateLastAssistantMessage)
  const setAgentStatus = useChatStore((s) => s.setAgentStatus)
  const addSessionPlot = useWorkspaceStore((s) => s.addSessionPlot)
  const setCurrentPlot = useWorkspaceStore((s) => s.setCurrentPlot)
  const setReportContent = useWorkspaceStore((s) => s.setReportContent)
  const setActiveTab = useWorkspaceStore((s) => s.setActiveTab)

  const protocol = typeof window !== 'undefined' && window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsUrl = typeof window !== 'undefined'
    ? `${protocol}//${window.location.host}/ws`
    : 'ws://localhost:4001/ws'

  useWebSocket(wsUrl, ({ type, data }) => {
    if (type === 'agent:status') {
      setAgentStatus(data as AgentStatus)
      return
    }

    if (type === 'agent:message') {
      const result = processAgentMessage(data)

      if (result.action === 'add' && result.message) {
        addMessage(result.message)
        if (result.message.plots) {
          for (const plotPath of result.message.plots) {
            const plot = { path: plotPath, filename: plotPath.split(/[\\/]/).pop()!, sidecar: null }
            addSessionPlot(plot)
            setCurrentPlot(plot)
            setActiveTab('plots')
          }
        }
      } else if (result.action === 'update' && result.update) {
        updateLastAssistantMessage(result.update)
        if (result.update.plots) {
          for (const plotPath of result.update.plots) {
            const plot = { path: plotPath, filename: plotPath.split(/[\\/]/).pop()!, sidecar: null }
            addSessionPlot(plot)
            setCurrentPlot(plot)
            setActiveTab('plots')
          }
        }
      }
      return
    }

    if (type === 'plot:new') {
      addSessionPlot(data as any)
      setCurrentPlot(data as any)
      setActiveTab('plots')
    }

    if (type === 'report:update') {
      setReportContent((data as any).content)
      setActiveTab('report')
    }
  })
}
