import { useProjectStore } from '../stores/project-store'
import { useChatStore } from '../stores/chat-store'
import { useWorkspaceStore } from '../stores/workspace-store'
import { cn } from '../lib/utils'

export function StatusBar() {
  const activeProject = useProjectStore((s) => s.activeProject)
  const agentStatus = useChatStore((s) => s.agentStatus)
  const messageCount = useChatStore((s) => s.messages.length)
  const plotCount = useWorkspaceStore((s) => s.sessionPlots.length)

  return (
    <div className="h-7 flex items-center px-4 gap-4 border-t text-[11px] text-muted-foreground select-none shrink-0">
      {/* Project */}
      <div className="flex items-center gap-1.5">
        <span className={cn(activeProject ? 'font-medium text-foreground' : 'italic')}>
          {activeProject ?? 'no project'}
        </span>
      </div>

      <div className="w-px h-3 bg-border" />

      {/* Agent status */}
      <div className="flex items-center gap-1.5">
        <StatusDot status={agentStatus} />
        <span>{agentStatus === 'tool_use' ? 'running' : agentStatus}</span>
      </div>

      <div className="w-px h-3 bg-border" />

      <span>{messageCount} msg{messageCount !== 1 ? 's' : ''}</span>

      {plotCount > 0 && (
        <>
          <div className="w-px h-3 bg-border" />
          <span>{plotCount} plot{plotCount !== 1 ? 's' : ''}</span>
        </>
      )}

      <div className="flex-1" />
      <span className="opacity-50">CASI v0.2</span>
    </div>
  )
}

function StatusDot({ status }: { status: string }) {
  if (status === 'idle') return <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
  if (status === 'thinking') return <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
  if (status === 'tool_use') return <span className="w-1.5 h-1.5 rounded-full border border-primary border-t-transparent animate-spin" />
  return <span className="w-1.5 h-1.5 rounded-full bg-destructive" />
}
