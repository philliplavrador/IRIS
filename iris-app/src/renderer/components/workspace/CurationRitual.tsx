import { useEffect, useState, useCallback } from 'react'
import { Loader2, Check, X, RefreshCw, CheckCheck, FileText } from 'lucide-react'
import { useProjectStore } from '../../stores/project-store'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { Badge } from '../ui/badge'
import { Card } from '../ui/card'
import { ScrollArea } from '../ui/scroll-area'
import { api } from '../../lib/api'

type PendingRow = {
  id: number
  kind: string
  payload: Record<string, any>
  session_id: string
  created_at: string
}

type DigestEntry = { id: string; text: string; tags?: string[]; refs?: any[] }

type DigestState = {
  session_id: string
  focus: string
  decisions: DigestEntry[]
  surprises: DigestEntry[]
  open_questions: DigestEntry[]
  next_steps: DigestEntry[]
}

const LIST_FIELDS: Array<keyof DigestState> = [
  'decisions', 'surprises', 'open_questions', 'next_steps',
]

export function CurationRitual() {
  const project = useProjectStore((s) => s.activeProject)
  const [drafts, setDrafts] = useState<string[]>([])
  const [selectedSession, setSelectedSession] = useState<string | null>(null)
  const [pending, setPending] = useState<PendingRow[]>([])
  const [digest, setDigest] = useState<DigestState | null>(null)
  const [approved, setApproved] = useState<Set<number>>(new Set())
  const [loading, setLoading] = useState(false)
  const [working, setWorking] = useState(false)
  const [status, setStatus] = useState<string | null>(null)

  const loadSessions = useCallback(async () => {
    if (!project) return
    const res = await api.listDigests(project)
    setDrafts(res.drafts ?? [])
    if (!selectedSession && res.drafts?.length) {
      setSelectedSession(res.drafts[res.drafts.length - 1])
    }
  }, [project, selectedSession])

  const loadSession = useCallback(async () => {
    if (!project || !selectedSession) return
    setLoading(true)
    try {
      const [d, p] = await Promise.all([
        api.getDraftDigest(project, selectedSession),
        api.listPending(project, selectedSession),
      ])
      setDigest(normalizeDigest(selectedSession, d))
      setPending(p.pending ?? [])
      setApproved(new Set((p.pending ?? []).map((r: PendingRow) => r.id)))
    } finally { setLoading(false) }
  }, [project, selectedSession])

  useEffect(() => { loadSessions() }, [loadSessions])
  useEffect(() => { loadSession() }, [loadSession])

  function toggle(id: number) {
    setApproved((s) => {
      const n = new Set(s)
      if (n.has(id)) n.delete(id); else n.add(id)
      return n
    })
  }

  async function discardRow(id: number) {
    if (!project) return
    await api.discardPending(project, [id])
    setApproved((s) => { const n = new Set(s); n.delete(id); return n })
    await loadSession()
  }

  async function saveDigest() {
    if (!project || !selectedSession || !digest) return
    await api.replaceDraftDigest(project, selectedSession, digest)
    setStatus('Digest saved.')
  }

  async function commitAll(finalize: boolean) {
    if (!project || !selectedSession || !digest) return
    setWorking(true)
    setStatus(null)
    try {
      // Save digest edits first.
      await api.replaceDraftDigest(project, selectedSession, digest)
      // Discard rejected rows.
      const rejected = pending.filter((r) => !approved.has(r.id)).map((r) => r.id)
      if (rejected.length) await api.discardPending(project, rejected)
      const approveIds = Array.from(approved)
      const rep = await api.commitSession(project, selectedSession, {
        approve_ids: approveIds,
        finalize_digest: finalize,
      })
      setStatus(`Committed ${rep.committed}${finalize ? ', digest finalized' : ''}.`)
      await loadSession()
      await loadSessions()
    } catch (e: any) {
      setStatus(`Failed: ${e.message}`)
    }
    setWorking(false)
  }

  function patchDigest(patch: Partial<DigestState>) {
    setDigest((d) => d ? { ...d, ...patch } : d)
  }

  function addEntry(field: keyof DigestState) {
    setDigest((d) => {
      if (!d) return d
      const list = [...(d[field] as DigestEntry[]), { id: `new-${Date.now()}`, text: '' }]
      return { ...d, [field]: list }
    })
  }

  function editEntry(field: keyof DigestState, idx: number, text: string) {
    setDigest((d) => {
      if (!d) return d
      const list = [...(d[field] as DigestEntry[])]
      list[idx] = { ...list[idx], text }
      return { ...d, [field]: list }
    })
  }

  function removeEntry(field: keyof DigestState, idx: number) {
    setDigest((d) => {
      if (!d) return d
      const list = [...(d[field] as DigestEntry[])]
      list.splice(idx, 1)
      return { ...d, [field]: list }
    })
  }

  if (!project) {
    return <div className="p-6 text-sm text-muted-foreground">Open a project to start a curation ritual.</div>
  }

  return (
    <div className="h-full flex flex-col">
      <div className="px-6 pt-4 pb-2 flex items-center gap-3 border-b">
        <FileText className="h-4 w-4 text-primary" />
        <span className="text-xs text-muted-foreground">Session draft</span>
        <select
          className="text-xs bg-background border rounded px-2 py-1 font-mono"
          value={selectedSession ?? ''}
          onChange={(e) => setSelectedSession(e.target.value || null)}
        >
          <option value="">—</option>
          {drafts.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <div className="flex-1" />
        <Button size="sm" variant="outline" onClick={() => { loadSessions(); loadSession() }}>
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
          {!loading && !selectedSession && (
            <div className="text-sm text-muted-foreground">No draft sessions. A draft is created automatically as you work.</div>
          )}

          {digest && (
            <Card className="p-5 space-y-4">
              <div>
                <h3 className="text-sm font-semibold">Draft digest</h3>
                <p className="text-xs text-muted-foreground">Edit the auto-drafted focus and lists. Saved on commit or via the save button.</p>
              </div>
              <div>
                <label className="text-xs font-medium">Focus</label>
                <Input
                  value={digest.focus}
                  onChange={(e) => patchDigest({ focus: e.target.value })}
                  placeholder="One sentence summary of what this session was about."
                  className="text-sm mt-1"
                />
              </div>
              {LIST_FIELDS.map((f) => (
                <div key={f}>
                  <div className="flex items-center justify-between mb-1.5">
                    <label className="text-xs font-medium capitalize">{String(f).replace('_', ' ')}</label>
                    <Button size="sm" variant="ghost" onClick={() => addEntry(f)}>+ add</Button>
                  </div>
                  <div className="space-y-1.5">
                    {(digest[f] as DigestEntry[]).map((e, i) => (
                      <div key={e.id + i} className="flex gap-2">
                        <Input
                          value={e.text}
                          onChange={(ev) => editEntry(f, i, ev.target.value)}
                          className="text-xs h-8 flex-1"
                        />
                        <Button size="sm" variant="ghost" onClick={() => removeEntry(f, i)}>
                          <X className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    ))}
                    {(digest[f] as DigestEntry[]).length === 0 && (
                      <div className="text-[11px] text-muted-foreground italic">empty</div>
                    )}
                  </div>
                </div>
              ))}
              <div>
                <Button size="sm" variant="outline" onClick={saveDigest}>Save digest only</Button>
              </div>
            </Card>
          )}

          {selectedSession && (
            <Card className="p-5 space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-semibold">Pending proposals</h3>
                  <p className="text-xs text-muted-foreground">L3 writes IRIS queued during the session. Uncheck to reject.</p>
                </div>
                <div className="flex gap-1.5">
                  <Button size="sm" variant="outline" onClick={() => setApproved(new Set(pending.map((r) => r.id)))}>
                    <CheckCheck className="h-3.5 w-3.5 mr-1" /> All
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setApproved(new Set())}>None</Button>
                </div>
              </div>
              {pending.length === 0 && (
                <div className="text-xs text-muted-foreground">No pending proposals for this session.</div>
              )}
              {groupByKind(pending).map(([kind, rows]) => (
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
                          <div className="font-mono text-[10px] text-muted-foreground">#{r.id}</div>
                          <ProposalBody kind={r.kind} payload={r.payload} />
                        </div>
                        <Button size="sm" variant="ghost" onClick={() => discardRow(r.id)} title="Discard permanently">
                          <X className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </Card>
          )}

          {selectedSession && (
            <div className="flex items-center gap-3">
              <Button onClick={() => commitAll(false)} disabled={working} variant="outline">
                {working ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> : <Check className="h-3.5 w-3.5 mr-1.5" />}
                Commit (keep draft)
              </Button>
              <Button onClick={() => commitAll(true)} disabled={working}>
                {working ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> : <Check className="h-3.5 w-3.5 mr-1.5" />}
                Commit &amp; finalize
              </Button>
              {status && <span className="text-xs text-muted-foreground">{status}</span>}
            </div>
          )}
        </div>
      </ScrollArea>
    </div>
  )
}

function ProposalBody({ kind, payload }: { kind: string; payload: any }) {
  if (kind === 'decision' || kind === 'goal' || kind === 'declined') {
    return <div>{payload.text}</div>
  }
  if (kind === 'fact') {
    return <div><span className="font-mono">{payload.key}</span> = {payload.value}</div>
  }
  if (kind === 'profile_annotation') {
    return <div><span className="font-mono">{payload.field_path}</span> — {payload.annotation}</div>
  }
  return <pre className="text-[10px] whitespace-pre-wrap">{JSON.stringify(payload, null, 2)}</pre>
}

function groupByKind(rows: PendingRow[]): Array<[string, PendingRow[]]> {
  const m = new Map<string, PendingRow[]>()
  for (const r of rows) {
    if (!m.has(r.kind)) m.set(r.kind, [])
    m.get(r.kind)!.push(r)
  }
  return Array.from(m.entries())
}

function normalizeDigest(session_id: string, raw: any): DigestState {
  return {
    session_id,
    focus: raw?.focus ?? '',
    decisions: raw?.decisions ?? [],
    surprises: raw?.surprises ?? [],
    open_questions: raw?.open_questions ?? [],
    next_steps: raw?.next_steps ?? [],
  }
}
