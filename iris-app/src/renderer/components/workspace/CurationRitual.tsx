import { useEffect, useState, useCallback } from 'react'
import { Loader2, Check, X, RefreshCw, CheckCheck, Sparkles } from 'lucide-react'
import { useProjectStore } from '../../stores/project-store'
import { Button } from '../ui/button'
import { Badge } from '../ui/badge'
import { Card } from '../ui/card'
import { ScrollArea } from '../ui/scroll-area'
import { api } from '../../lib/api'

// Permissive shape — tighten once the daemon settles on a final schema.
// TODO(phase-10): share this type with api.ts / MemoryInspector.
type DraftEntry = {
  id: string
  memory_type?: string
  content?: string
  text?: string
  status?: string
  importance?: number
  confidence?: number
  session_id?: string
  created_at?: string
  [key: string]: any
}

export function CurationRitual() {
  const project = useProjectStore((s) => s.activeProject)
  // TODO(phase-9): pipe the active memory-session id into the project store
  // so "Extract from session" can target the current chat. For now we allow
  // callers to set it manually once the store exposes it.
  const currentSessionId: string | null = null

  const [drafts, setDrafts] = useState<DraftEntry[]>([])
  const [approved, setApproved] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(false)
  const [working, setWorking] = useState(false)
  const [status, setStatus] = useState<string | null>(null)

  const loadDrafts = useCallback(async () => {
    if (!project) return
    setLoading(true)
    try {
      const res = await api.listMemoryEntries({ status: 'draft' })
      const rows = res.entries ?? []
      setDrafts(rows)
      setApproved(new Set(rows.map((r: DraftEntry) => r.id)))
    } finally {
      setLoading(false)
    }
  }, [project])

  useEffect(() => { loadDrafts() }, [loadDrafts])

  function toggle(id: string) {
    setApproved((s) => {
      const n = new Set(s)
      if (n.has(id)) n.delete(id); else n.add(id)
      return n
    })
  }

  async function approveAll() {
    if (!project) return
    const ids = Array.from(approved)
    if (ids.length === 0) {
      setStatus('No drafts selected for approval.')
      return
    }
    setWorking(true)
    setStatus(null)
    try {
      const rep = await api.commitMemoryEntries(ids, currentSessionId ?? undefined)
      const committed = rep?.committed ?? ids.length
      setStatus(`Committed ${committed} entr${committed === 1 ? 'y' : 'ies'}.`)
      await loadDrafts()
    } catch (e: any) {
      setStatus(`Failed: ${e?.message ?? String(e)}`)
    }
    setWorking(false)
  }

  async function rejectSelected() {
    if (!project) return
    // "Reject" = discard all drafts NOT currently approved.
    const rejectIds = drafts.filter((d) => !approved.has(d.id)).map((d) => d.id)
    if (rejectIds.length === 0) {
      setStatus('Nothing to reject — all drafts are approved.')
      return
    }
    setWorking(true)
    setStatus(null)
    try {
      await api.discardMemoryEntries(rejectIds)
      setStatus(`Discarded ${rejectIds.length}.`)
      await loadDrafts()
    } catch (e: any) {
      setStatus(`Failed: ${e?.message ?? String(e)}`)
    }
    setWorking(false)
  }

  async function discardRow(id: string) {
    if (!project) return
    await api.discardMemoryEntries([id])
    setApproved((s) => { const n = new Set(s); n.delete(id); return n })
    await loadDrafts()
  }

  async function extractFromSession() {
    if (!currentSessionId) return
    setWorking(true)
    setStatus(null)
    try {
      const rep = await api.extractSessionMemories(currentSessionId)
      const n = rep?.extracted ?? rep?.count ?? 0
      setStatus(`Extracted ${n} draft${n === 1 ? '' : 's'}.`)
      await loadDrafts()
    } catch (e: any) {
      setStatus(`Failed: ${e?.message ?? String(e)}`)
    }
    setWorking(false)
  }

  if (!project) {
    return <div className="p-6 text-sm text-muted-foreground">Open a project to start a curation ritual.</div>
  }

  return (
    <div className="h-full flex flex-col">
      <div className="px-6 pt-4 pb-2 flex items-center gap-3 border-b">
        <span className="text-xs text-muted-foreground">
          {drafts.length} draft{drafts.length === 1 ? '' : 's'}
        </span>
        <div className="flex-1" />
        <Button
          size="sm"
          variant="outline"
          onClick={extractFromSession}
          disabled={!currentSessionId || working}
          title={currentSessionId ? 'Extract memories from the active session' : 'No active memory session'}
        >
          <Sparkles className="h-3.5 w-3.5 mr-1" /> Extract from session
        </Button>
        <Button size="sm" variant="outline" onClick={loadDrafts}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      <ScrollArea className="flex-1">
        <div className="p-6 space-y-5 max-w-4xl">
          {loading && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading…
            </div>
          )}
          {!loading && drafts.length === 0 && (
            <div className="text-sm text-muted-foreground">
              No draft memory entries. Run extraction on a finished session to populate this list.
            </div>
          )}

          {drafts.length > 0 && (
            <Card className="p-5 space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-semibold">Draft memory entries</h3>
                  <p className="text-xs text-muted-foreground">
                    Uncheck to mark for rejection. Approve commits selected entries; Reject discards the rest.
                  </p>
                </div>
                <div className="flex gap-1.5">
                  <Button size="sm" variant="outline" onClick={() => setApproved(new Set(drafts.map((r) => r.id)))}>
                    <CheckCheck className="h-3.5 w-3.5 mr-1" /> All
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setApproved(new Set())}>None</Button>
                </div>
              </div>
              {groupByType(drafts).map(([kind, rows]) => (
                <div key={kind}>
                  <div className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1">{kind}</div>
                  <div className="space-y-1.5">
                    {rows.map((r) => (
                      <div key={r.id} className="flex items-start gap-2 p-2 rounded border bg-muted/30">
                        <input
                          type="checkbox"
                          checked={approved.has(r.id)}
                          onChange={() => toggle(r.id)}
                          className="mt-1"
                        />
                        <div className="flex-1 min-w-0 text-xs">
                          <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground flex-wrap">
                            <span className="font-mono">#{r.id}</span>
                            {r.importance != null && <Badge variant="outline">imp {r.importance}</Badge>}
                            {r.confidence != null && <Badge variant="outline">conf {r.confidence}</Badge>}
                          </div>
                          <div className="mt-1 whitespace-pre-wrap">{r.content ?? r.text ?? ''}</div>
                        </div>
                        <Button size="sm" variant="ghost" onClick={() => discardRow(r.id)} title="Discard">
                          <X className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </Card>
          )}

          {drafts.length > 0 && (
            <div className="flex items-center gap-3">
              <Button onClick={approveAll} disabled={working}>
                {working ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> : <Check className="h-3.5 w-3.5 mr-1.5" />}
                Approve selected
              </Button>
              <Button onClick={rejectSelected} disabled={working} variant="outline">
                {working ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> : <X className="h-3.5 w-3.5 mr-1.5" />}
                Reject unchecked
              </Button>
              {status && <span className="text-xs text-muted-foreground">{status}</span>}
            </div>
          )}
        </div>
      </ScrollArea>
    </div>
  )
}

function groupByType(rows: DraftEntry[]): Array<[string, DraftEntry[]]> {
  const m = new Map<string, DraftEntry[]>()
  for (const r of rows) {
    const k = r.memory_type ?? 'entry'
    if (!m.has(k)) m.set(k, [])
    m.get(k)!.push(r)
  }
  return Array.from(m.entries())
}
