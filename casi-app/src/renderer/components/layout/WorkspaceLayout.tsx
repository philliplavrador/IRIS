import { useCallback, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Settings } from 'lucide-react'
import { useProjectStore } from '../../stores/project-store'
import { Button } from '../ui/button'
import { ThemeToggle } from '../shared/ThemeToggle'
import { ChatPanel } from '../chat/ChatPanel'
import { WorkspaceTabs } from '../workspace/WorkspaceTabs'
import { StatusBar } from '../StatusBar'

const MIN_CHAT_WIDTH = 300
const MAX_CHAT_WIDTH = 600
const DEFAULT_CHAT_WIDTH = 380

export function WorkspaceLayout() {
  const activeProject = useProjectStore((s) => s.activeProject)
  const setActiveProject = useProjectStore((s) => s.setActiveProject)
  const navigate = useNavigate()
  const [chatWidth, setChatWidth] = useState(DEFAULT_CHAT_WIDTH)
  const dragging = useRef(false)

  const handleBack = useCallback(() => {
    setActiveProject(null)
    navigate('/')
  }, [setActiveProject, navigate])

  const handleDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    dragging.current = true
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
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }

    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [chatWidth])

  return (
    <div className="h-screen flex flex-col bg-background">
      {/* Top bar */}
      <header className="h-12 border-b flex items-center px-4 justify-between shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <Button variant="ghost" size="icon" onClick={handleBack} title="Back to projects">
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div className="w-px h-5 bg-border" />
          <span className="font-semibold text-sm truncate">{activeProject}</span>
        </div>
        <div className="flex items-center gap-1">
          <ThemeToggle />
          <Button variant="ghost" size="icon" title="Settings">
            <Settings className="h-4 w-4" />
          </Button>
        </div>
      </header>

      {/* Main area: chat sidebar + workspace */}
      <div className="flex-1 min-h-0 flex">
        {/* Chat sidebar */}
        <div style={{ width: chatWidth }} className="shrink-0 flex flex-col border-r">
          <ChatPanel />
        </div>

        {/* Drag handle */}
        <div
          className="w-1 cursor-col-resize hover:bg-primary/20 active:bg-primary/30 transition-colors shrink-0"
          onMouseDown={handleDragStart}
        />

        {/* Workspace */}
        <div className="flex-1 min-w-0 flex flex-col">
          <WorkspaceTabs />
        </div>
      </div>

      {/* Status bar */}
      <StatusBar />
    </div>
  )
}
