import { describe, it, expect, beforeEach } from 'vitest'
import { useChatStore } from '../../stores/chat-store'

describe('chat-store', () => {
  beforeEach(() => {
    useChatStore.setState({ messages: [], agentStatus: 'idle' })
  })

  it('starts with empty messages and idle status', () => {
    const state = useChatStore.getState()
    expect(state.messages).toEqual([])
    expect(state.agentStatus).toBe('idle')
  })

  it('adds a message', () => {
    useChatStore.getState().addMessage({
      id: 'msg-1',
      role: 'user',
      content: 'Hello',
      timestamp: Date.now(),
    })
    expect(useChatStore.getState().messages).toHaveLength(1)
    expect(useChatStore.getState().messages[0].content).toBe('Hello')
  })

  it('updates the last assistant message', () => {
    const store = useChatStore.getState()
    store.addMessage({ id: 'u1', role: 'user', content: 'Hi', timestamp: 1 })
    store.addMessage({ id: 'a1', role: 'assistant', content: 'Hello', timestamp: 2 })
    store.addMessage({ id: 'u2', role: 'user', content: 'More', timestamp: 3 })

    store.updateLastAssistantMessage({ content: 'Updated hello' })
    const msgs = useChatStore.getState().messages
    expect(msgs[1].content).toBe('Updated hello')
    expect(msgs[0].content).toBe('Hi')
  })

  it('clears messages', () => {
    const store = useChatStore.getState()
    store.addMessage({ id: 'u1', role: 'user', content: 'Hi', timestamp: 1 })
    store.clearMessages()
    expect(useChatStore.getState().messages).toEqual([])
  })

  it('sets agent status', () => {
    useChatStore.getState().setAgentStatus('thinking')
    expect(useChatStore.getState().agentStatus).toBe('thinking')
  })
})
