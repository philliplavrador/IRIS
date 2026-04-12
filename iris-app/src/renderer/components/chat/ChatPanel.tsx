import { useRef, useEffect } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useChatStore } from '../../stores/chat-store'
import { Sparkles } from 'lucide-react'
import { ChatMessage } from './ChatMessage'
import { ChatInput } from './ChatInput'
import { ScrollArea } from '../ui/scroll-area'

export function ChatPanel() {
  const messages = useChatStore((s) => s.messages)
  const agentStatus = useChatStore((s) => s.agentStatus)
  const scrollRef = useRef<HTMLDivElement>(null)

  const virtualizer = useVirtualizer({
    count: messages.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 100,
    overscan: 5,
  })

  useEffect(() => {
    if (messages.length > 0) {
      virtualizer.scrollToIndex(messages.length - 1, { align: 'end', behavior: 'smooth' })
    }
  }, [messages.length])

  return (
    <div className="h-full flex flex-col">
      {/* Messages */}
      <ScrollArea ref={scrollRef} className="flex-1">
        {messages.length === 0 && agentStatus === 'idle' ? (
          <div className="flex items-center justify-center h-full min-h-[300px]">
            <div className="text-center max-w-[260px] px-6 animate-fade-in-up">
              <div className="w-11 h-11 mx-auto mb-4 rounded-xl bg-gradient-to-br from-primary/15 to-primary/5 flex items-center justify-center ring-1 ring-primary/10">
                <Sparkles className="h-5 w-5 text-primary/60" />
              </div>
              <h2 className="text-sm font-semibold mb-1">Ready to analyze</h2>
              <p className="text-xs text-muted-foreground/80 leading-relaxed">
                Ask about your data, request a plot, or start an analysis.
              </p>
              <div className="mt-4 flex flex-wrap gap-1.5 justify-center">
                {['Profile my data', 'Show a spectrogram', 'Run spike detection'].map((suggestion) => (
                  <button
                    key={suggestion}
                    className="text-[10px] px-2.5 py-1 rounded-full bg-muted/80 text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors cursor-pointer"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div
            style={{ height: virtualizer.getTotalSize(), position: 'relative', width: '100%' }}
          >
            {virtualizer.getVirtualItems().map((virtualItem) => (
                <div
                  key={virtualItem.key}
                  data-index={virtualItem.index}
                  ref={virtualizer.measureElement}
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%',
                    transform: `translateY(${virtualItem.start}px)`,
                  }}
                >
                  <div className="px-5 py-2">
                    <ChatMessage message={messages[virtualItem.index]} />
                  </div>
                </div>
              ))}
          </div>
        )}
      </ScrollArea>

      <ChatInput />
    </div>
  )
}
