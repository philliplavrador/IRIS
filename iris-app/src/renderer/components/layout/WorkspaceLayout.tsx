import { useCallback, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Settings } from 'lucide-react'
import { useProjectStore } from '../../stores/project-store'
import { Button } from '../ui/button'
import { ThemeToggle } from '../shared/ThemeToggle'
import { ChatPanel } from '../chat/ChatPanel'
import { WorkspaceTabs } from '../workspace/WorkspaceTabs'
import { ProjectSettings } from '../workspace/ProjectSettings'
import { StatusBar } from '../StatusBar'
import { cn } from '../../lib/utils'

const MIN_CHAT_WIDTH = 300
const MAX_CHAT_WIDTH = 600
const DEFAULT_CHAT_WIDTH = 400

export function WorkspaceLayout() {
  const activeProject = useProjectStore((s) => s.activeProject)
  const setActiveProject = useProjectStore((s) => s.setActiveProject)
  const navigate = useNavigate()
  const [chatWidth, setChatWidth] = useState(DEFAULT_CHAT_WIDTH)
  const [isDragging, setIsDragging] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const dragging = useRef(false)

  const handleBack = useCallback(() => {
    setActiveProject(null)
    navigate('/')
  }, [setActiveProject, navigate])

  const handleDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    dragging.current = true
    setIsDragging(true)
    const startX = e.clientX
    const startWidth = chatWidth

    function onMove(ev: MouseEvent) {
      if (!dragging.current) return
      const delta = ev.clientX - startX
      const newWidth = Math.max(MIN_CHAT_WIDTH, Math.min(MAX_CHAT_WIDTH, startWidth + delta))
      setChatWidth(newWidth)
    }

    function onUp() {
      dragging.current = false
      setIsDragging(false)
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }

    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [chatWidth])

  return (
    <div className={cn("h-screen flex flex-col bg-background", isDragging && "select-none cursor-col-resize")}>
      {/* Top bar */}
      <header className="h-13 border-b flex items-center px-6 justify-between shrink-0 bg-background/80 backdrop-blur-sm">
        <div className="flex items-center gap-3 min-w-0">
          <Button variant="ghost" size="icon" onClick={handleBack} title="Back to projects" className="h-8 w-8">
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div className="w-px h-5 bg-border" />
          <span className="font-semibold text-sm truncate">{activeProject}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <ThemeToggle />
          <Button variant="ghost" size="icon" title="Settings" className="h-8 w-8" onClick={() => setSettingsOpen(true)}>
            <Settings className="h-4 w-4" />
          </Button>
        </div>
      </header>

      {/* Main area: chat sidebar + workspace */}
      <div className="flex-1 min-h-0 flex">
        {/* Chat sidebar */}
        <div style={{ width: chatWidth }} className="shrink-0 flex flex-col border-r border-border/60 bg-sidebar">
          <ChatPanel />
        </div>

        {/* Drag handle */}
        <div
          className={cn(
            "w-1.5 cursor-col-resize shrink-0 relative group transition-colors",
            isDragging ? "bg-primary/30" : "hover:bg-primary/15"
          )}
          onMouseDown={handleDragStart}
        >
          {/* Visual grip indicator on hover */}
          <div className={cn(
            "absolute inset-y-0 left-0 right-0 flex items-center justify-center transition-opacity",
            isDragging ? "opacity-100" : "opacity-0 group-hover:opacity-100"
          )}>
            <div className="flex flex-col gap-1">
              <div className="w-0.5 h-0.5 rounded-full bg-muted-foreground/40" />
              <div className="w-0.5 h-0.5 rounded-full bg-muted-foreground/40" />
              <div className="w-0.5 h-0.5 rounded-full bg-muted-foreground/40" />
            </div>
          </div>
        </div>

        {/* Workspace */}
        <div className="flex-1 min-w-0 flex flex-col">
          <WorkspaceTabs />
        </div>
      </div>

      {/* Status bar */}
      <StatusBar />

      <ProjectSettings open={settingsOpen} onOpenChange={setSettingsOpen} />
    </div>
  )
}
