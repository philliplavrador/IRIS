import { useRef, useEffect } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useChatStore } from '../../stores/chat-store'
import { Activity } from 'lucide-react'
import { ChatMessage } from './ChatMessage'
import { ChatInput } from './ChatInput'
import { ScrollArea } from '../ui/scroll-area'

export function ChatPanel() {
  const messages = useChatStore((s) => s.messages)
  const agentStatus = useChatStore((s) => s.agentStatus)
  const scrollRef = useRef<HTMLDivElement>(null)

  const virtualizer = useVirtualizer({
    count: messages.length + (agentStatus !== 'idle' ? 1 : 0),
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 100,
    overscan: 5,
  })

  useEffect(() => {
    const count = messages.length + (agentStatus !== 'idle' ? 1 : 0)
    if (count > 0) {
      virtualizer.scrollToIndex(count - 1, { align: 'end', behavior: 'smooth' })
    }
  }, [messages.length, agentStatus])

  return (
    <div className="h-full flex flex-col">
      {/* Messages */}
      <ScrollArea ref={scrollRef} className="flex-1">
        {messages.length === 0 && agentStatus === 'idle' ? (
          <div className="flex items-center justify-center h-full min-h-[300px]">
            <div className="text-center max-w-xs px-4">
              <Activity className="h-10 w-10 mx-auto mb-4 text-primary/30" />
              <h2 className="text-sm font-semibold mb-1">Ready to analyze</h2>
              <p className="text-xs text-muted-foreground">
                Ask a question about your data below
              </p>
            </div>
          </div>
        ) : (
          <div
            style={{ height: virtualizer.getTotalSize(), position: 'relative', width: '100%' }}
          >
            {virtualizer.getVirtualItems().map((virtualItem) => {
              const isStatusRow = virtualItem.index === messages.length
              return (
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
                  {isStatusRow ? (
                    <StatusIndicator status={agentStatus} />
                  ) : (
                    <div className="px-4 py-2">
                      <ChatMessage message={messages[virtualItem.index]} />
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </ScrollArea>

      <ChatInput />
    </div>
  )
}

function StatusIndicator({ status }: { status: string }) {
  return (
    <div className="flex items-center gap-2.5 text-muted-foreground text-xs py-3 px-5">
      {status === 'thinking' ? (
        <>
          <div className="flex gap-1">
            <span className="w-1.5 h-1.5 bg-primary rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
            <span className="w-1.5 h-1.5 bg-primary rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
            <span className="w-1.5 h-1.5 bg-primary rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
          </div>
          Thinking...
        </>
      ) : (
        <>
          <div className="w-3.5 h-3.5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          Running...
        </>
      )}
    </div>
  )
}
