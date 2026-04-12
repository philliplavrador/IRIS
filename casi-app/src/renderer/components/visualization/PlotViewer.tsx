import { useWorkspaceStore } from '../../stores/workspace-store'
import { api } from '../../lib/api'
import { SidecarCard } from './SidecarCard'
import { BarChart3, ImageIcon } from 'lucide-react'
import { ScrollArea } from '../ui/scroll-area'
import { cn } from '../../lib/utils'
import type { PlotInfo } from '../../types'

export function PlotViewer() {
  const currentPlot = useWorkspaceStore((s) => s.currentPlot)
  const sessionPlots = useWorkspaceStore((s) => s.sessionPlots)
  const setCurrentPlot = useWorkspaceStore((s) => s.setCurrentPlot)

  if (!currentPlot && sessionPlots.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-center px-8">
        <BarChart3 className="h-12 w-12 mb-4 text-muted-foreground/30" />
        <p className="text-sm font-medium">No plots yet</p>
        <p className="text-xs text-muted-foreground mt-1 max-w-xs">
          Run an analysis to generate plots, or click a thumbnail in the chat to view it here.
        </p>
      </div>
    )
  }

  if (!currentPlot && sessionPlots.length > 0) {
    // Show gallery view
    return (
      <ScrollArea className="h-full">
        <div className="p-6">
          <h3 className="text-sm font-semibold mb-4">Session Plots ({sessionPlots.length})</h3>
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
            {sessionPlots.map((plot, i) => (
              <button
                key={plot.path + i}
                onClick={() => selectPlot(plot, setCurrentPlot)}
                className="rounded-lg overflow-hidden border hover:border-primary/50 hover:shadow-md transition-all group"
              >
                <img
                  src={api.plotUrl(plot.path)}
                  alt={plot.filename}
                  className="w-full aspect-[4/3] object-cover bg-muted group-hover:brightness-105 transition-all"
                  loading="lazy"
                  onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
                />
                <div className="p-2 text-xs text-muted-foreground truncate">{plot.filename}</div>
              </button>
            ))}
          </div>
        </div>
      </ScrollArea>
    )
  }

  const imgUrl = api.plotUrl(currentPlot!.path)

  return (
    <div className="h-full flex flex-col">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <ImageIcon className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          <span className="text-xs font-mono text-muted-foreground truncate">
            {currentPlot!.filename}
          </span>
        </div>
        {sessionPlots.length > 1 && (
          <button
            onClick={() => setCurrentPlot(null)}
            className="text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            View all ({sessionPlots.length})
          </button>
        )}
      </div>

      {/* Main image */}
      <div className="flex-1 min-h-0 flex items-center justify-center overflow-auto p-6 bg-muted/30">
        <img
          src={imgUrl}
          alt={currentPlot!.filename}
          className="max-w-full max-h-full object-contain rounded-lg shadow-lg"
          draggable={false}
          onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
        />
      </div>

      {/* Sidecar metadata */}
      {currentPlot!.sidecar && (
        <SidecarCard sidecar={currentPlot!.sidecar} />
      )}

      {/* Thumbnail strip */}
      {sessionPlots.length > 1 && (
        <div className="shrink-0 border-t px-3 py-2 overflow-x-auto">
          <div className="flex gap-2">
            {sessionPlots.map((plot, i) => (
              <button
                key={plot.path + i}
                onClick={() => selectPlot(plot, setCurrentPlot)}
                className={cn(
                  "shrink-0 w-16 h-12 rounded-lg overflow-hidden border-2 transition-all",
                  plot.path === currentPlot!.path
                    ? "border-primary shadow-sm"
                    : "border-transparent opacity-70 hover:opacity-100"
                )}
                title={plot.filename}
              >
                <img
                  src={api.plotUrl(plot.path)}
                  alt={plot.filename}
                  className="w-full h-full object-cover bg-muted"
                  loading="lazy"
                  onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
                />
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function selectPlot(plot: PlotInfo, setCurrentPlot: (p: PlotInfo) => void) {
  setCurrentPlot(plot)
  if (!plot.sidecar) {
    api.readSidecar(plot.path).then((sidecar) => {
      if (sidecar) {
        useWorkspaceStore.getState().setCurrentPlot({ ...plot, sidecar })
      }
    })
  }
}
