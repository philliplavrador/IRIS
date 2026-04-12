import { useState, useRef, useEffect } from 'react'
import { Send, Square } from 'lucide-react'
import { useChatStore } from '../../stores/chat-store'
import { useProjectStore } from '../../stores/project-store'
import { api } from '../../lib/api'
import { Button } from '../ui/button'
import { cn } from '../../lib/utils'

export function ChatInput() {
  const [input, setInput] = useState('')
  const [focused, setFocused] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const agentStatus = useChatStore((s) => s.agentStatus)
  const addMessage = useChatStore((s) => s.addMessage)
  const activeProject = useProjectStore((s) => s.activeProject)
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

    api.sendMessage(text, activeProject ?? undefined)
    setInput('')
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="shrink-0">
      {/* Progress bar when running */}
      {isRunning && <div className="progress-bar-indeterminate" />}

      <div className={cn(
        "px-5 pt-3 pb-4 transition-colors duration-200",
        !isRunning && "border-t border-border/60",
      )}>
        <div className={cn(
          "flex gap-1.5 items-end rounded-xl border bg-muted/30 p-1.5 transition-all duration-200",
          focused && !isRunning && "border-primary/40 bg-muted/50 shadow-sm shadow-primary/5 ring-1 ring-primary/15",
          isRunning && "opacity-60"
        )}>
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            placeholder={isRunning ? 'Agent is working...' : 'Ask about your data...'}
            disabled={isRunning}
            rows={1}
            className="flex-1 resize-none px-2.5 py-2 bg-transparent text-sm placeholder:text-muted-foreground/50 focus:outline-none disabled:opacity-50"
          />
          {isRunning ? (
            <Button variant="destructive" size="icon" className="rounded-lg shrink-0 h-8 w-8" onClick={() => api.abortAgent()} title="Stop agent">
              <Square className="h-3.5 w-3.5" />
            </Button>
          ) : (
            <Button
              size="icon"
              className={cn(
                "rounded-lg shrink-0 h-8 w-8 transition-all duration-200",
                input.trim() ? "opacity-100 scale-100" : "opacity-30 scale-95"
              )}
              onClick={handleSend}
              disabled={!input.trim()}
              title="Send (Enter)"
            >
              <Send className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
