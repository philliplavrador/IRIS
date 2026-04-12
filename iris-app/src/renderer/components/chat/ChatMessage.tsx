import React, { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import rehypeHighlight from 'rehype-highlight'
import { ChevronRight, Info, Wrench, Sparkles } from 'lucide-react'
import { useWorkspaceStore } from '../../stores/workspace-store'
import { api } from '../../lib/api'
import { Badge } from '../ui/badge'
import { cn } from '../../lib/utils'
import type { ChatMessage as ChatMessageType, ToolUseInfo } from '../../types'

interface Props {
  message: ChatMessageType
}

export const ChatMessage = React.memo(function ChatMessage({ message }: Props) {
  if (message.role === 'system') {
    return (
      <div className="flex items-start gap-2.5 py-2 px-3 text-xs text-muted-foreground bg-muted/40 rounded-lg border border-border/50 animate-fade-in">
        <Info className="w-3.5 h-3.5 mt-0.5 shrink-0 text-muted-foreground/70" />
        <span className="leading-relaxed">{message.content}</span>
      </div>
    )
  }

  if (message.role === 'user') {
    return (
      <div className="flex justify-end animate-slide-in-right">
        <div className="max-w-[85%] px-3.5 py-2.5 rounded-2xl rounded-br-md bg-primary text-primary-foreground text-sm leading-relaxed shadow-sm">
          {message.content}
        </div>
      </div>
    )
  }

  // Assistant message
  return (
    <div className="flex gap-2.5 animate-fade-in">
      {/* Avatar */}
      <div className="shrink-0 mt-0.5">
        <div className="w-6 h-6 rounded-lg bg-gradient-to-br from-primary/20 to-primary/5 flex items-center justify-center ring-1 ring-primary/10">
          <Sparkles className="w-3 h-3 text-primary/70" />
        </div>
      </div>

      {/* Content */}
      <div className="min-w-0 flex-1 space-y-2">
        {message.content && (
          <div className="prose prose-sm dark:prose-invert max-w-none text-sm leading-relaxed [&_pre]:bg-muted [&_pre]:rounded-lg [&_pre]:border [&_pre]:p-3 [&_code]:text-xs [&_code:not(pre_code)]:bg-muted/80 [&_code:not(pre_code)]:px-1.5 [&_code:not(pre_code)]:py-0.5 [&_code:not(pre_code)]:rounded [&_code:not(pre_code)]:border [&_code:not(pre_code)]:border-border/50 [&_a]:text-primary [&_p]:mb-2 [&_ul]:mb-2 [&_ol]:mb-2 [&_p:last-child]:mb-0 [&_ul:last-child]:mb-0 [&_ol:last-child]:mb-0">
            <ReactMarkdown
              remarkPlugins={[remarkGfm, remarkMath]}
              rehypePlugins={[rehypeKatex, rehypeHighlight]}
            >
              {message.content}
            </ReactMarkdown>
          </div>
        )}

        {message.toolUse?.map((tool, i) => (
          <ToolUseCard key={i} tool={tool} />
        ))}

        {message.plots && message.plots.length > 0 && (
          <div className="flex flex-wrap gap-2 mt-1">
            {message.plots.map((plotPath, i) => (
              <PlotThumbnail key={i} path={plotPath} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}, (prev, next) =>
  prev.message.id === next.message.id &&
  prev.message.content === next.message.content &&
  prev.message.isStreaming === next.message.isStreaming
)

function ToolUseCard({ tool }: { tool: ToolUseInfo }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="rounded-lg border border-border/60 overflow-hidden bg-muted/20">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-accent/40 text-left transition-colors cursor-pointer"
      >
        <ChevronRight className={cn("h-3 w-3 text-muted-foreground/60 transition-transform duration-200", expanded && "rotate-90")} />
        <Wrench className="h-3 w-3 text-muted-foreground/50 shrink-0" />
        <Badge variant="secondary" className="text-[10px] font-mono px-1.5 py-0">{tool.tool}</Badge>
        <span className="text-[11px] text-muted-foreground/70 truncate flex-1 font-mono">
          {tool.input.length > 50 ? tool.input.slice(0, 50) + '...' : tool.input}
        </span>
      </button>
      {expanded && (
        <div className="px-3 py-2.5 bg-muted/30 border-t border-border/50 animate-expand-down">
          <pre className="text-xs font-mono text-muted-foreground whitespace-pre-wrap break-all max-h-48 overflow-y-auto leading-relaxed">
            {tool.input}
          </pre>
          {tool.output && (
            <>
              <div className="text-[10px] text-muted-foreground/60 mt-2.5 mb-1 font-semibold uppercase tracking-wider">Output</div>
              <pre className="text-xs font-mono text-muted-foreground whitespace-pre-wrap break-all max-h-48 overflow-y-auto leading-relaxed">
                {tool.output}
              </pre>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function PlotThumbnail({ path }: { path: string }) {
  const [loaded, setLoaded] = useState(false)
  const setCurrentPlot = useWorkspaceStore((s) => s.setCurrentPlot)
  const setActiveTab = useWorkspaceStore((s) => s.setActiveTab)
  const imgUrl = api.plotUrl(path)

  return (
    <button
      onClick={() => {
        setCurrentPlot({ path, filename: path.split(/[\\/]/).pop()!, sidecar: null })
        setActiveTab('plots')
        api.readSidecar(path).then((sidecar) => {
          if (sidecar) {
            useWorkspaceStore.getState().setCurrentPlot({ path, filename: path.split(/[\\/]/).pop()!, sidecar })
          }
        })
      }}
      className="rounded-lg overflow-hidden border border-border/60 hover:border-primary/40 hover:shadow-md transition-all duration-200 group"
      title={path.split(/[\\/]/).pop()}
    >
      {!loaded && <div className="w-36 h-22 skeleton" />}
      <img
        src={imgUrl}
        alt="Plot"
        className={cn(
          "w-36 h-22 object-cover bg-muted group-hover:brightness-110 transition-all duration-200",
          loaded ? "opacity-100" : "opacity-0 h-0"
        )}
        loading="lazy"
        onLoad={() => setLoaded(true)}
        onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
      />
    </button>
  )
}
