import { useEffect, useState, useCallback } from 'react'
import { Loader2, Trash2, Archive, RefreshCw } from 'lucide-react'
import { useProjectStore } from '../../stores/project-store'
import { Button } from '../ui/button'
import { Badge } from '../ui/badge'
import { Card } from '../ui/card'
import { ScrollArea } from '../ui/scroll-area'
import { Tabs, TabsList, TabsTrigger } from '../ui/tabs'
import { api } from '../../lib/api'

// Permissive shape — tighten once the daemon settles on a final schema
// (REVAMP §7 memory_entries). TODO(phase-10): share this type with api.ts.
type MemoryEntry = {
  id?: string
  memory_id?: string
  memory_type?: string
  content?: string
  text?: string
  status?: string
  importance?: number
  confidence?: number
  created_at?: string
  updated_at?: string
  scope?: string
  superseded_by?: string | null
  [key: string]: any
}

// Map UI tabs to schema `memory_type` values. Schema enum: finding,
// assumption, caveat, open_question, decision, failure_reflection,
// preference, reflection, session_summary.
type TabKey =
  | 'finding'
  | 'decision'
  | 'open_question'
  | 'caveat'
  | 'assumption'
  | 'preference'
  | 'reflection'

const TABS: Array<{ key: TabKey; label: string }> = [
  { key: 'finding', label: 'Findings' },
  { key: 'decision', label: 'Decisions' },
  { key: 'open_question', label: 'Open Qs' },
  { key: 'caveat', label: 'Caveats' },
  { key: 'assumption', label: 'Assumptions' },
  { key: 'preference', label: 'Preferences' },
  { key: 'reflection', label: 'Reflections' },
]

export function MemoryInspector() {
  const project = useProjectStore((s) => s.activeProject)
  const [tab, setTab] = useState<TabKey>('finding')
  const [entries, setEntries] = useState<MemoryEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [includeInactive, setIncludeInactive] = useState(false)

  const load = useCallback(async () => {
    if (!project) return
    setLoading(true)
    try {
      const res = await api.listMemoryEntries({
        type: tab,
        status: includeInactive ? undefined : 'active',
      })
      setEntries(res.entries ?? [])
    } finally {
      setLoading(false)
    }
  }, [project, tab, includeInactive])

  useEffect(() => { load() }, [load])

  async function setStatus(id: string, status: string) {
    await api.patchMemoryEntryStatus(id, status)
    await load()
  }

  async function softDelete(id: string) {
    await api.softDeleteMemoryEntry(id)
    await load()
  }

  if (!project) {
    return <div className="p-6 text-sm text-muted-foreground">Open a project to inspect memory.</div>
  }

  return (
    <div className="h-full flex flex-col">
      <div className="px-6 pt-4 pb-2 flex items-center gap-3 border-b">
        <Tabs value={tab} onValueChange={(v) => setTab(v as TabKey)}>
          <TabsList>
            {TABS.map((t) => <TabsTrigger key={t.key} value={t.key}>{t.label}</TabsTrigger>)}
          </TabsList>
        </Tabs>
        <div className="flex-1" />
        <Button
          size="sm"
          variant={includeInactive ? 'default' : 'outline'}
          onClick={() => setIncludeInactive((v) => !v)}
        >
          {includeInactive ? 'Show active only' : 'Show all'}
        </Button>
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
          {!loading && entries.length === 0 && (
            <div className="text-sm text-muted-foreground">No entries.</div>
          )}
          {entries.map((e) => {
            const id = e.id ?? e.memory_id ?? ''
            return (
              <Card key={id} className="p-3">
                <EntryView entry={{ ...e, id }} onStatus={setStatus} onDelete={softDelete} />
              </Card>
            )
          })}
        </div>
      </ScrollArea>
    </div>
  )
}

function EntryView({
  entry, onStatus, onDelete,
}: {
  entry: MemoryEntry
  onStatus: (id: string, status: string) => void
  onDelete: (id: string) => void
}) {
  const text = entry.content ?? entry.text ?? ''
  const ts = entry.updated_at ?? entry.created_at ?? ''
  const isActive = (entry.status ?? 'active') === 'active'
  return (
    <div className="flex items-start gap-3">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 text-xs text-muted-foreground flex-wrap">
          <span className="font-mono">#{entry.id}</span>
          {entry.status && (
            <Badge variant={isActive ? 'default' : 'outline'}>{entry.status}</Badge>
          )}
          {entry.importance != null && (
            <Badge variant="outline">importance {entry.importance}</Badge>
          )}
          {entry.confidence != null && (
            <Badge variant="outline">confidence {entry.confidence}</Badge>
          )}
          {entry.scope && <Badge variant="outline">{entry.scope}</Badge>}
          {entry.superseded_by && (
            <span>superseded by {entry.superseded_by}</span>
          )}
          {ts && <span>{ts}</span>}
        </div>
        <div className="text-sm mt-1 whitespace-pre-wrap">{text}</div>
      </div>
      <div className="flex gap-1.5">
        {isActive ? (
          <Button size="sm" variant="outline" onClick={() => onStatus(entry.id, 'archived')}>
            <Archive className="h-3.5 w-3.5 mr-1" /> Archive
          </Button>
        ) : (
          <Button size="sm" variant="outline" onClick={() => onStatus(entry.id, 'active')}>
            Reactivate
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={() => onDelete(entry.id)} title="Soft delete">
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  )
}
