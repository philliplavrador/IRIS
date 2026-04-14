import { useEffect, useState, useCallback } from 'react'
import { Loader2, Trash2, Archive, CheckSquare, RefreshCw } from 'lucide-react'
import { useProjectStore } from '../../stores/project-store'
import { Button } from '../ui/button'
import { Badge } from '../ui/badge'
import { Card } from '../ui/card'
import { ScrollArea } from '../ui/scroll-area'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../ui/tabs'
import { api } from '../../lib/api'

type TableKey = 'goals' | 'decisions' | 'learned_facts' | 'declined_suggestions' | 'data_profile_fields'

const TABLES: Array<{ key: TableKey; label: string }> = [
  { key: 'goals', label: 'Goals' },
  { key: 'decisions', label: 'Decisions' },
  { key: 'learned_facts', label: 'Facts' },
  { key: 'declined_suggestions', label: 'Declined' },
  { key: 'data_profile_fields', label: 'Profile' },
]

export function MemoryInspector() {
  const project = useProjectStore((s) => s.activeProject)
  const [table, setTable] = useState<TableKey>('goals')
  const [rows, setRows] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [includeInactive, setIncludeInactive] = useState(false)

  const load = useCallback(async () => {
    if (!project) return
    setLoading(true)
    try {
      const hasStatus = table === 'goals' || table === 'decisions'
      const res = await api.listKnowledge(project, table, {
        status: hasStatus && !includeInactive ? 'active' : undefined,
      })
      setRows(res.rows ?? [])
    } finally {
      setLoading(false)
    }
  }, [project, table, includeInactive])

  useEffect(() => { load() }, [load])

  async function setStatus(id: number, status: string) {
    if (!project) return
    await api.setKnowledgeStatus(project, table, id, status)
    await load()
  }

  async function del(id: number) {
    if (!project) return
    await api.deleteKnowledgeRow(project, table, id)
    await load()
  }

  if (!project) {
    return <div className="p-6 text-sm text-muted-foreground">Open a project to inspect memory.</div>
  }

  return (
    <div className="h-full flex flex-col">
      <div className="px-6 pt-4 pb-2 flex items-center gap-3 border-b">
        <Tabs value={table} onValueChange={(v) => setTable(v as TableKey)}>
          <TabsList>
            {TABLES.map((t) => <TabsTrigger key={t.key} value={t.key}>{t.label}</TabsTrigger>)}
          </TabsList>
        </Tabs>
        <div className="flex-1" />
        {(table === 'goals' || table === 'decisions') && (
          <Button
            size="sm"
            variant={includeInactive ? 'default' : 'outline'}
            onClick={() => setIncludeInactive((v) => !v)}
          >
            {includeInactive ? 'Show active only' : 'Show all'}
          </Button>
        )}
        <Button size="sm" variant="outline" onClick={load}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      <ScrollArea className="flex-1">
        <div className="p-6 space-y-2 max-w-4xl">
          {loading && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading…
            </div>
          )}
          {!loading && rows.length === 0 && (
            <div className="text-sm text-muted-foreground">No rows.</div>
          )}
          {rows.map((r) => (
            <Card key={r.id} className="p-3">
              <RowView table={table} row={r} onStatus={setStatus} onDelete={del} />
            </Card>
          ))}
        </div>
      </ScrollArea>
    </div>
  )
}

function RowView({
  table, row, onStatus, onDelete,
}: {
  table: TableKey
  row: any
  onStatus: (id: number, status: string) => void
  onDelete: (id: number) => void
}) {
  const statusBadge = row.status && (
    <Badge variant={row.status === 'active' ? 'default' : 'outline'}>{row.status}</Badge>
  )
  const ts = row.last_referenced_at || row.created_at

  if (table === 'goals') {
    return (
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className="font-mono">#{row.id}</span>
            {statusBadge}
            <span>{ts}</span>
          </div>
          <div className="text-sm mt-1">{row.text}</div>
        </div>
        {row.status === 'active' ? (
          <div className="flex gap-1.5">
            <Button size="sm" variant="outline" onClick={() => onStatus(row.id, 'done')}>
              <CheckSquare className="h-3.5 w-3.5 mr-1" /> Done
            </Button>
            <Button size="sm" variant="outline" onClick={() => onStatus(row.id, 'abandoned')}>
              <Archive className="h-3.5 w-3.5 mr-1" /> Abandon
            </Button>
          </div>
        ) : (
          <Button size="sm" variant="outline" onClick={() => onStatus(row.id, 'active')}>Reactivate</Button>
        )}
      </div>
    )
  }

  if (table === 'decisions') {
    return (
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className="font-mono">#{row.id}</span>
            {statusBadge}
            {row.supersedes && <span>supersedes #{row.supersedes}</span>}
            <span>{ts}</span>
          </div>
          <div className="text-sm mt-1">{row.text}</div>
          {row.rationale && (
            <div className="text-xs text-muted-foreground mt-1 italic">{row.rationale}</div>
          )}
        </div>
        {row.status === 'active' ? (
          <Button size="sm" variant="outline" onClick={() => onStatus(row.id, 'abandoned')}>
            <Archive className="h-3.5 w-3.5 mr-1" /> Abandon
          </Button>
        ) : (
          <Button size="sm" variant="outline" onClick={() => onStatus(row.id, 'active')}>Reactivate</Button>
        )}
      </div>
    )
  }

  if (table === 'learned_facts') {
    return (
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className="font-mono">#{row.id}</span>
            {row.superseded_by && <Badge variant="outline">superseded by #{row.superseded_by}</Badge>}
            {row.confidence != null && <span>conf {row.confidence}</span>}
            <span>{ts}</span>
          </div>
          <div className="text-sm mt-1"><span className="font-mono text-xs">{row.key}</span> = {row.value}</div>
        </div>
        <Button size="sm" variant="ghost" onClick={() => onDelete(row.id)}>
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>
    )
  }

  if (table === 'declined_suggestions') {
    return (
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className="font-mono">#{row.id}</span>
            <span>{ts}</span>
          </div>
          <div className="text-sm mt-1">{row.text}</div>
        </div>
        <Button size="sm" variant="ghost" onClick={() => onDelete(row.id)} title="Un-decline (delete)">
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>
    )
  }

  // data_profile_fields
  return (
    <div className="flex items-start gap-3">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="font-mono">#{row.id}</span>
          {row.confirmed_by_user ? <Badge>confirmed</Badge> : <Badge variant="outline">unconfirmed</Badge>}
          <span>{ts}</span>
        </div>
        <div className="text-sm mt-1 font-mono">{row.field_path}</div>
        {row.annotation && (
          <div className="text-xs text-muted-foreground mt-1">{row.annotation}</div>
        )}
      </div>
      <Button size="sm" variant="ghost" onClick={() => onDelete(row.id)}>
        <Trash2 className="h-3.5 w-3.5" />
      </Button>
    </div>
  )
}
