import React, { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import rehypeHighlight from 'rehype-highlight'
import { ChevronRight, Info, Image } from 'lucide-react'
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
      <div className="flex items-start gap-2 py-2 px-3 text-xs text-muted-foreground bg-muted rounded-lg">
        <Info className="w-3.5 h-3.5 mt-0.5 shrink-0" />
        {message.content}
      </div>
    )
  }

  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] px-3.5 py-2.5 rounded-2xl rounded-br-sm bg-primary text-primary-foreground text-sm shadow-sm">
          {message.content}
        </div>
      </div>
    )
  }

  // Assistant message
  return (
    <div className="max-w-full space-y-2">
      {message.content && (
        <div className="prose prose-sm dark:prose-invert max-w-none text-sm [&_pre]:bg-muted [&_pre]:rounded-lg [&_pre]:border [&_pre]:p-3 [&_code]:text-xs [&_code:not(pre_code)]:bg-muted [&_code:not(pre_code)]:px-1.5 [&_code:not(pre_code)]:py-0.5 [&_code:not(pre_code)]:rounded [&_a]:text-primary">
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
  )
}, (prev, next) =>
  prev.message.id === next.message.id &&
  prev.message.content === next.message.content &&
  prev.message.isStreaming === next.message.isStreaming
)

function ToolUseCard({ tool }: { tool: ToolUseInfo }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="rounded-lg border overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-accent text-left transition-colors cursor-pointer"
      >
        <ChevronRight className={cn("h-3 w-3 text-muted-foreground transition-transform", expanded && "rotate-90")} />
        <Badge variant="secondary" className="text-[10px] font-mono">{tool.tool}</Badge>
        <span className="text-xs text-muted-foreground truncate flex-1 font-mono">
          {tool.input.length > 50 ? tool.input.slice(0, 50) + '...' : tool.input}
        </span>
      </button>
      {expanded && (
        <div className="px-3 py-2.5 bg-muted/50 border-t">
          <pre className="text-xs font-mono text-muted-foreground whitespace-pre-wrap break-all max-h-48 overflow-y-auto">
            {tool.input}
          </pre>
          {tool.output && (
            <>
              <div className="text-[10px] text-muted-foreground mt-2 mb-1 font-semibold uppercase tracking-wider">Output</div>
              <pre className="text-xs font-mono text-muted-foreground whitespace-pre-wrap break-all max-h-48 overflow-y-auto">
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
      className="rounded-lg overflow-hidden border hover:border-primary/50 hover:shadow-md transition-all group"
      title={path.split(/[\\/]/).pop()}
    >
      <img
        src={imgUrl}
        alt="Plot"
        className="w-32 h-20 object-cover bg-muted group-hover:brightness-105 transition-all"
        loading="lazy"
        onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
      />
    </button>
  )
}
