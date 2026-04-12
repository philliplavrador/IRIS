import { Presentation } from 'lucide-react'

export function SlidesViewer() {
  return (
    <div className="h-full flex flex-col items-center justify-center text-center px-8">
      <Presentation className="h-12 w-12 mb-4 text-muted-foreground/30" />
      <p className="text-sm font-medium">Slides</p>
      <p className="text-xs text-muted-foreground mt-1 max-w-xs">
        Ask the agent to generate a presentation from your report, or click "Generate Slides" in the Report tab.
      </p>
    </div>
  )
}
