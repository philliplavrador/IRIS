import { Settings } from 'lucide-react'

export function ProjectSettings() {
  return (
    <div className="h-full flex flex-col items-center justify-center text-center px-8">
      <Settings className="h-12 w-12 mb-4 text-muted-foreground/30" />
      <p className="text-sm font-medium">Project Settings</p>
      <p className="text-xs text-muted-foreground mt-1 max-w-xs">
        Per-project configuration, operation defaults, and plot backend selection.
      </p>
    </div>
  )
}
