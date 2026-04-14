import { useEffect, useState, useCallback } from 'react'
import {
  Loader2,
  RefreshCw,
  Sparkles,
  AlertTriangle,
  Clock,
  BarChart3,
} from 'lucide-react'
import { useProjectStore } from '../../stores/project-store'
import { Button } from '../ui/button'
import { Card } from '../ui/card'
import { ScrollArea } from '../ui/scroll-area'
import { api } from '../../lib/api'

type Metrics = {
  retrievals: number
  retrieved_total: number
  used_total: number
  usage_ratio: number
  stale_rate: number
  contradiction_rate: number
}

type Contradiction = {
  contradiction_id: string
  memory_id_a: string
  memory_id_b: string
  resolved: boolean
  resolution_text: string | null
  created_at: string
}

/**
 * V2 memory Insights panel (REVAMP Phases 13/16/17).
 *
 * One screen for the background memory hygiene knobs that the spec
 * §10.2/10.3 introduces: reflection trigger, staleness scan,
 * contradictions inbox, and retrieval-to-usage metrics.
 */
export function Insights() {
  const project = useProjectStore((s) => s.activeProject)
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [contras, setContras] = useState<Contradiction[]>([])
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    if (!project) return
    setLoading(true)
    try {
      const [m, c] = await Promise.all([
        api.memoryMetrics(),
        api.listContradictions(false),
      ])
      setMetrics(m?.data ?? null)
      setContras(c?.data ?? [])
    } catch (e: any) {
      setStatus(`Failed: ${e?.message ?? String(e)}`)
    } finally {
      setLoading(false)
    }
  }, [project])

  useEffect(() => {
    refresh()
  }, [refresh])

  async function runReflection() {
    setStatus(null)
    try {
      const res = await api.reflect()
      const ids = res?.data?.ids ?? []
      setStatus(`Reflection produced ${ids.length} new insight${ids.length === 1 ? '' : 's'}.`)
    } catch (e: any) {
      setStatus(`Reflection failed: ${e?.message ?? String(e)}`)
    }
  }

  async function runStalenessScan() {
    setStatus(null)
    try {
      const res = await api.stalenessScan()
      const ids = res?.data?.ids ?? []
      setStatus(`${ids.length} memor${ids.length === 1 ? 'y' : 'ies'} marked stale.`)
    } catch (e: any) {
      setStatus(`Scan failed: ${e?.message ?? String(e)}`)
    }
  }

  async function resolveContradiction(
    id: string,
    winningMemoryId: string,
    text: string,
  ) {
    try {
      await api.resolveContradiction(id, text, winningMemoryId)
      await refresh()
    } catch (e: any) {
      setStatus(`Resolve failed: ${e?.message ?? String(e)}`)
    }
  }

  if (!project) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        Open a project to see memory insights.
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col">
      <div className="px-6 pt-4 pb-2 flex items-center gap-2 border-b">
        <h2 className="text-sm font-semibold flex items-center gap-1.5">
          <BarChart3 className="h-4 w-4" /> Memory insights
        </h2>
        <div className="flex-1" />
        <Button size="sm" variant="outline" onClick={refresh}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      <ScrollArea className="flex-1">
        <div className="p-6 space-y-5 max-w-4xl">
          {status && (
            <div className="text-xs rounded-md border bg-muted/40 px-3 py-2">
              {status}
            </div>
          )}

          {/* Metrics */}
          <Card className="p-5 space-y-3">
            <h3 className="text-sm font-semibold">Retrieval quality</h3>
            {loading && !metrics ? (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading…
              </div>
            ) : metrics ? (
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-sm">
                <MetricBox
                  label="Retrievals"
                  value={metrics.retrievals.toString()}
                />
                <MetricBox
                  label="Usage ratio"
                  value={formatPct(metrics.usage_ratio)}
                />
                <MetricBox
                  label="Used / retrieved"
                  value={`${metrics.used_total} / ${metrics.retrieved_total}`}
                />
                <MetricBox
                  label="Stale rate"
                  value={formatPct(metrics.stale_rate)}
                />
                <MetricBox
                  label="Contradiction rate"
                  value={formatPct(metrics.contradiction_rate)}
                />
              </div>
            ) : (
              <div className="text-xs text-muted-foreground">No metrics.</div>
            )}
          </Card>

          {/* Actions */}
          <Card className="p-5 space-y-3">
            <h3 className="text-sm font-semibold">Maintenance</h3>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={runReflection}>
                <Sparkles className="h-3.5 w-3.5 mr-1" /> Run reflection
              </Button>
              <Button size="sm" variant="outline" onClick={runStalenessScan}>
                <Clock className="h-3.5 w-3.5 mr-1" /> Scan staleness
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Reflection synthesizes high-importance memories into
              higher-level insights. Staleness flags old findings,
              assumptions, and open questions for revalidation.
            </p>
          </Card>

          {/* Contradictions */}
          <Card className="p-5 space-y-3">
            <h3 className="text-sm font-semibold flex items-center gap-1.5">
              <AlertTriangle className="h-4 w-4 text-yellow-500" />
              Open contradictions
            </h3>
            {contras.length === 0 ? (
              <div className="text-xs text-muted-foreground">
                No unresolved contradictions.
              </div>
            ) : (
              <div className="space-y-2">
                {contras.map((c) => (
                  <div
                    key={c.contradiction_id}
                    className="rounded-md border p-3 text-xs space-y-2"
                  >
                    <div className="font-mono text-[11px] text-muted-foreground">
                      {new Date(c.created_at).toLocaleString()}
                    </div>
                    <div>
                      <span className="font-mono">{c.memory_id_a.slice(0, 8)}</span>
                      {' '}↔{' '}
                      <span className="font-mono">{c.memory_id_b.slice(0, 8)}</span>
                    </div>
                    <div className="flex gap-1.5">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          resolveContradiction(
                            c.contradiction_id,
                            c.memory_id_a,
                            `Kept A (${c.memory_id_a.slice(0, 8)})`,
                          )
                        }
                      >
                        Keep A
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          resolveContradiction(
                            c.contradiction_id,
                            c.memory_id_b,
                            `Kept B (${c.memory_id_b.slice(0, 8)})`,
                          )
                        }
                      >
                        Keep B
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      </ScrollArea>
    </div>
  )
}

function MetricBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border p-3">
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="text-lg font-semibold tabular-nums">{value}</div>
    </div>
  )
}

function formatPct(v: number): string {
  if (!Number.isFinite(v)) return '—'
  return `${(v * 100).toFixed(1)}%`
}
