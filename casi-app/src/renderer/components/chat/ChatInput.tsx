import { useState, useRef, useEffect } from 'react'
import { Send, Square } from 'lucide-react'
import { useChatStore } from '../../stores/chat-store'
import { api } from '../../lib/api'
import { Button } from '../ui/button'

export function ChatInput() {
  const [input, setInput] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const agentStatus = useChatStore((s) => s.agentStatus)
  const addMessage = useChatStore((s) => s.addMessage)
  const isRunning = agentStatus !== 'idle'

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 140) + 'px'
    }
  }, [input])

  function handleSend() {
    const text = input.trim()
    if (!text || isRunning) return

    addMessage({
      id: `user-${Date.now()}`,
      role: 'user',
      content: text,
      timestamp: Date.now(),
    })

    api.sendMessage(text)
    setInput('')
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="border-t p-3 shrink-0">
      <div className="flex gap-2 items-end">
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={isRunning ? 'Agent is working...' : 'Ask about your data...'}
          disabled={isRunning}
          rows={1}
          className="flex-1 resize-none px-3 py-2 bg-transparent border rounded-lg text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50 transition-colors"
        />
        {isRunning ? (
          <Button variant="destructive" size="icon" onClick={() => api.abortAgent()} title="Stop">
            <Square className="h-3.5 w-3.5" />
          </Button>
        ) : (
          <Button size="icon" onClick={handleSend} disabled={!input.trim()} title="Send">
            <Send className="h-3.5 w-3.5" />
          </Button>
        )}
      </div>
    </div>
  )
}
