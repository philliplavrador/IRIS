import { create } from 'zustand'
import type { ChatMessage, AgentStatus } from '../types'

interface ChatStore {
  messages: ChatMessage[]
  agentStatus: AgentStatus

  addMessage: (msg: ChatMessage) => void
  updateLastAssistantMessage: (update: Partial<ChatMessage>) => void
  clearMessages: () => void
  setAgentStatus: (status: AgentStatus) => void
}

export const useChatStore = create<ChatStore>((set) => ({
  messages: [],
  agentStatus: 'idle',

  addMessage: (msg) =>
    set((s) => ({ messages: [...s.messages, msg] })),

  updateLastAssistantMessage: (update) =>
    set((s) => {
      const msgs = [...s.messages]
      for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i].role === 'assistant') {
          msgs[i] = { ...msgs[i], ...update }
          break
        }
      }
      return { messages: msgs }
    }),

  clearMessages: () => set({ messages: [] }),
  setAgentStatus: (agentStatus) => set({ agentStatus }),
}))
