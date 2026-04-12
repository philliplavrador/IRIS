import { useProjectStore } from '../stores/project-store'
import { useChatStore } from '../stores/chat-store'
import { useWorkspaceStore } from '../stores/workspace-store'
import { cn } from '../lib/utils'

export function StatusBar() {
  const activeProject = useProjectStore((s) => s.activeProject)
  const agentStatus = useChatStore((s) => s.agentStatus)
  const messageCount = useChatStore((s) => s.messages.length)
  const plotCount = useWorkspaceStore((s) => s.sessionPlots.length)
  const isActive = agentStatus !== 'idle'

  return (
    <div className="shrink-0">
      {/* Progress bar at top of status bar when active */}
      {isActive && <div className="progress-bar-indeterminate" />}

      <div className="h-9 flex items-center px-6 gap-4 border-t text-[11px] text-muted-foreground select-none bg-background">
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
          <span className={cn(isActive && "text-foreground")}>
            {agentStatus === 'tool_use' ? 'running' : agentStatus}
          </span>
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
        <span className="opacity-40">IRIS v0.2</span>
      </div>
    </div>
  )
}

function StatusDot({ status }: { status: string }) {
  if (status === 'idle') return <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
  if (status === 'thinking') return <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
  if (status === 'tool_use') return <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
  return <span className="w-1.5 h-1.5 rounded-full bg-destructive" />
}
