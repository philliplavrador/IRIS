import { Badge } from '../ui/badge'
import type { PlotSidecar } from '../../types'

interface Props {
  sidecar: PlotSidecar
}

export function SidecarCard({ sidecar }: Props) {
  const windowLabel =
    sidecar.window_ms === 'full'
      ? 'full recording'
      : `${sidecar.window_ms[0].toFixed(1)} – ${sidecar.window_ms[1].toFixed(1)} ms`

  return (
    <div className="shrink-0 border-t px-4 py-3 max-h-36 overflow-y-auto">
      <code className="text-xs font-mono font-semibold text-primary">{sidecar.dsl}</code>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-2 text-xs text-muted-foreground">
        <span>{windowLabel}</span>
        <span>{sidecar.plot_backend}</span>
        <span>v{sidecar.iris_version}</span>
        {sidecar.timestamp && <span>{new Date(sidecar.timestamp).toLocaleString()}</span>}
      </div>

      {sidecar.ops.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2">
          {sidecar.ops.map((op, i) => (
            <Badge key={i} variant="secondary" className="text-[10px] font-mono" title={JSON.stringify(op.params, null, 2)}>
              {op.name}
            </Badge>
          ))}
        </div>
      )}
    </div>
  )
}
