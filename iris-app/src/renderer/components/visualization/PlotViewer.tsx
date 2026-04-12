import { useState } from 'react'
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
      <div className="h-full flex flex-col items-center justify-center text-center px-12 animate-fade-in">
        <BarChart3 className="h-12 w-12 mb-5 text-muted-foreground/20" />
        <p className="text-sm font-medium">No plots yet</p>
        <p className="text-xs text-muted-foreground mt-1 max-w-xs leading-relaxed">
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
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-4 stagger-children">
            {sessionPlots.map((plot, i) => (
              <GalleryPlot key={plot.path + i} plot={plot} setCurrentPlot={setCurrentPlot} />
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
      <div className="flex items-center justify-between px-5 py-3 border-b shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <ImageIcon className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          <span className="text-xs font-mono text-muted-foreground truncate">
            {currentPlot!.filename}
          </span>
        </div>
        {sessionPlots.length > 1 && (
          <button
            onClick={() => setCurrentPlot(null)}
            className="text-xs text-primary hover:text-primary/80 transition-colors font-medium"
          >
            View all ({sessionPlots.length})
          </button>
        )}
      </div>

      {/* Main image */}
      <div className="flex-1 min-h-0 flex items-center justify-center overflow-auto p-6 bg-muted/20">
        <MainPlotImage src={imgUrl} alt={currentPlot!.filename} />
      </div>

      {/* Sidecar metadata */}
      {currentPlot!.sidecar && (
        <SidecarCard sidecar={currentPlot!.sidecar} />
      )}

      {/* Thumbnail strip */}
      {sessionPlots.length > 1 && (
        <div className="shrink-0 border-t px-4 py-2.5 overflow-x-auto">
          <div className="flex gap-2.5">
            {sessionPlots.map((plot, i) => (
              <button
                key={plot.path + i}
                onClick={() => selectPlot(plot, setCurrentPlot)}
                className={cn(
                  "shrink-0 w-16 h-12 rounded-lg overflow-hidden border-2 transition-all duration-200",
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

function GalleryPlot({ plot, setCurrentPlot }: { plot: PlotInfo; setCurrentPlot: (p: PlotInfo) => void }) {
  const [loaded, setLoaded] = useState(false)
  return (
    <button
      onClick={() => selectPlot(plot, setCurrentPlot)}
      className="rounded-lg overflow-hidden border hover:border-primary/50 hover:shadow-md transition-all duration-200 group"
    >
      {!loaded && <div className="w-full aspect-[4/3] skeleton" />}
      <img
        src={api.plotUrl(plot.path)}
        alt={plot.filename}
        className={cn(
          "w-full aspect-[4/3] object-cover bg-muted group-hover:brightness-105 transition-all duration-200",
          loaded ? "opacity-100" : "opacity-0 h-0"
        )}
        loading="lazy"
        onLoad={() => setLoaded(true)}
        onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
      />
      <div className="p-2 text-xs text-muted-foreground truncate">{plot.filename}</div>
    </button>
  )
}

function MainPlotImage({ src, alt }: { src: string; alt: string }) {
  const [loaded, setLoaded] = useState(false)
  return (
    <>
      {!loaded && (
        <div className="w-96 h-72 skeleton rounded-lg" />
      )}
      <img
        src={src}
        alt={alt}
        className={cn(
          "max-w-full max-h-full object-contain rounded-lg shadow-lg transition-opacity duration-300",
          loaded ? "opacity-100" : "opacity-0 absolute"
        )}
        draggable={false}
        onLoad={() => setLoaded(true)}
        onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
      />
    </>
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
