import { useCallback, useEffect, useState } from 'react'
import { Loader2, RefreshCw } from 'lucide-react'
import { useProjectStore } from '../../stores/project-store'
import { Button } from '../ui/button'
import { Badge } from '../ui/badge'
import { Card } from '../ui/card'
import { ScrollArea } from '../ui/scroll-area'
import { api } from '../../lib/api'

interface RunRow {
  id: string
  operation?: string
  op_name?: string
  status?: string
  started_at?: string
  ended_at?: string
  duration_ms?: number
}

interface Lineage {
  ancestors: RunRow[]
  descendants: RunRow[]
}

function fmtDuration(row: RunRow): string {
  if (typeof row.duration_ms === 'number') {
    const s = row.duration_ms / 1000
    return s < 1 ? `${row.duration_ms}ms` : `${s.toFixed(2)}s`
  }
  if (row.started_at && row.ended_at) {
    const d = Date.parse(row.ended_at) - Date.parse(row.started_at)
    if (!Number.isNaN(d) && d >= 0) return `${(d / 1000).toFixed(2)}s`
  }
  return '—'
}

function fmtStarted(row: RunRow): string {
  if (!row.started_at) return '—'
  try { return new Date(row.started_at).toLocaleString() } catch { return row.started_at }
}

function statusTone(status?: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  switch ((status || '').toLowerCase()) {
    case 'success': case 'ok': case 'done': return 'default'
    case 'running': case 'pending': return 'secondary'
    case 'error': case 'failed': return 'destructive'
    default: return 'outline'
  }
}

export function RunHistory() {
  const project = useProjectStore((s) => s.activeProject)
  const [rows, setRows] = useState<RunRow[]>([])
  const [loading, setLoading] = useState(false)
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [selected, setSelected] = useState<RunRow | null>(null)
  const [lineage, setLineage] = useState<Lineage | null>(null)
  const [lineageLoading, setLineageLoading] = useState(false)

  const load = useCallback(async () => {
    if (!project) return
    setLoading(true)
    try {
      const res = await api.listRuns(project, {
        status: statusFilter || undefined,
        limit: 100,
      })
      setRows(res.rows ?? [])
    } finally {
      setLoading(false)
    }
  }, [project, statusFilter])

  useEffect(() => { load() }, [load])

  // Poll every 5s
  useEffect(() => {
    if (!project) return
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [project, load])

  const onRowClick = useCallback(async (row: RunRow) => {
    if (!project) return
    setSelected(row)
    setLineage(null)
    setLineageLoading(true)
    try {
      const res = await api.getRunLineage(project, row.id)
      setLineage({ ancestors: res.ancestors ?? [], descendants: res.descendants ?? [] })
    } finally {
      setLineageLoading(false)
    }
  }, [project])

  if (!project) {
    return (
      <div className="p-6 text-sm text-muted-foreground">Open a project to view runs.</div>
    )
  }

  return (
    <div className="flex h-full min-h-0">
      {/* Main table */}
      <div className="flex-1 min-w-0 flex flex-col">
        <div className="flex items-center gap-2 px-4 py-2 border-b shrink-0">
          <select
            className="text-xs border rounded px-2 py-1 bg-background"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="">All statuses</option>
            <option value="success">Success</option>
            <option value="running">Running</option>
            <option value="error">Error</option>
            <option value="pending">Pending</option>
          </select>
          <Button variant="ghost" size="sm" onClick={load} disabled={loading}>
            {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          </Button>
          <span className="text-xs text-muted-foreground ml-auto">
            {rows.length} run{rows.length === 1 ? '' : 's'} · polling 5s
          </span>
        </div>
        <ScrollArea className="flex-1 min-h-0">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-background border-b">
              <tr className="text-left text-muted-foreground">
                <th className="px-4 py-2 font-medium">Operation</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Started</th>
                <th className="px-4 py-2 font-medium">Duration</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && !loading && (
                <tr>
                  <td colSpan={4} className="px-4 py-8 text-center text-muted-foreground">
                    No runs yet.
                  </td>
                </tr>
              )}
              {rows.map((row) => {
                const isSelected = selected?.id === row.id
                return (
                  <tr
                    key={row.id}
                    onClick={() => onRowClick(row)}
                    className={
                      'cursor-pointer border-b hover:bg-muted/50 ' +
                      (isSelected ? 'bg-muted' : '')
                    }
                  >
                    <td className="px-4 py-2 font-mono">{row.operation || row.op_name || '—'}</td>
                    <td className="px-4 py-2">
                      <Badge variant={statusTone(row.status)} className="text-[10px]">
                        {row.status || 'unknown'}
                      </Badge>
                    </td>
                    <td className="px-4 py-2 text-muted-foreground">{fmtStarted(row)}</td>
                    <td className="px-4 py-2 text-muted-foreground">{fmtDuration(row)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </ScrollArea>
      </div>

      {/* Lineage side panel */}
      {selected && (
        <div className="w-80 border-l flex flex-col shrink-0">
          <div className="px-4 py-2 border-b flex items-center justify-between shrink-0">
            <div className="text-xs font-medium truncate">Lineage</div>
            <Button variant="ghost" size="sm" onClick={() => { setSelected(null); setLineage(null) }}>
              Close
            </Button>
          </div>
          <ScrollArea className="flex-1 min-h-0">
            <div className="p-4 space-y-4">
              <Card className="p-3 space-y-1">
                <div className="text-[10px] uppercase text-muted-foreground">Selected run</div>
                <div className="font-mono text-xs">{selected.operation || selected.op_name || '—'}</div>
                <div className="text-[10px] text-muted-foreground break-all">{selected.id}</div>
              </Card>

              <div>
                <div className="text-[10px] uppercase text-muted-foreground mb-1">Ancestors</div>
                {lineageLoading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                {!lineageLoading && lineage && lineage.ancestors.length === 0 && (
                  <div className="text-xs text-muted-foreground">None</div>
                )}
                <div className="space-y-1">
                  {lineage?.ancestors.map((a) => (
                    <Card key={a.id} className="p-2 text-xs">
                      <div className="font-mono">{a.operation || a.op_name || '—'}</div>
                      <div className="text-[10px] text-muted-foreground break-all">{a.id}</div>
                    </Card>
                  ))}
                </div>
              </div>

              <div>
                <div className="text-[10px] uppercase text-muted-foreground mb-1">Descendants</div>
                {!lineageLoading && lineage && lineage.descendants.length === 0 && (
                  <div className="text-xs text-muted-foreground">None</div>
                )}
                <div className="space-y-1">
                  {lineage?.descendants.map((d) => (
                    <Card key={d.id} className="p-2 text-xs">
                      <div className="font-mono">{d.operation || d.op_name || '—'}</div>
                      <div className="text-[10px] text-muted-foreground break-all">{d.id}</div>
                    </Card>
                  ))}
                </div>
              </div>
            </div>
          </ScrollArea>
        </div>
      )}
    </div>
  )
}
