import { useMemo, useState } from 'react'
import { Check, X as XIcon, Loader2, FileText, AlertCircle } from 'lucide-react'
import { Dialog, DialogHeader, DialogTitle, DialogClose, DialogBody, DialogFooter } from '../ui/dialog'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { Badge } from '../ui/badge'
import { ScrollArea } from '../ui/scroll-area'
import { api } from '../../lib/api'
import type { UploadedProfile, FileProfile } from '../../types'

interface Row {
  fieldPath: string
  summary: string
  annotation: string
  skip: boolean
}

interface Props {
  open: boolean
  onClose: () => void
  projectName: string
  uploaded: UploadedProfile[]
}

export function ProfileConfirmation({ open, onClose, projectName, uploaded }: Props) {
  const initial = useMemo(() => buildRows(uploaded), [uploaded])
  const [rows, setRows] = useState<Record<string, Row>>(initial)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<string | null>(null)

  // Reset state when dialog re-opens with new uploads
  useMemo(() => { setRows(initial); setResult(null) }, [initial])

  function patchRow(key: string, patch: Partial<Row>) {
    setRows((r) => ({ ...r, [key]: { ...r[key], ...patch } }))
  }

  async function handleConfirm() {
    setSubmitting(true)
    setResult(null)
    try {
      const session_id = `profile-${Date.now()}`
      const pending: number[] = []
      for (const row of Object.values(rows)) {
        if (row.skip) continue
        const pid = await api.proposeProfileAnnotation(
          projectName, session_id, row.fieldPath, row.annotation || row.summary,
        )
        pending.push(pid)
      }
      if (pending.length === 0) {
        setResult('No fields selected.')
      } else {
        const rep = await api.commitSessionWrites(projectName, session_id, pending)
        setResult(`Confirmed ${rep.committed} annotation${rep.committed === 1 ? '' : 's'}.`)
      }
    } catch (err: any) {
      setResult(`Failed: ${err.message}`)
    }
    setSubmitting(false)
  }

  const perFile = groupByFile(uploaded)
  const rowCount = Object.values(rows).filter((r) => !r.skip).length

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <div className="w-full max-w-3xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>Confirm data profile</DialogTitle>
          <DialogClose onClose={onClose} />
        </DialogHeader>
        <DialogBody className="p-0">
          <ScrollArea className="max-h-[60vh]">
            <div className="p-6 space-y-6">
              <p className="text-xs text-muted-foreground">
                IRIS auto-profiled your uploads. Edit the annotation for any field to give it semantic meaning,
                or skip fields that shouldn't be remembered. Confirmed rows are stored in <code>knowledge.sqlite</code>.
              </p>
              {perFile.map(({ name, profile, error, rowKeys }) => (
                <section key={name} className="space-y-2">
                  <div className="flex items-center gap-2">
                    <FileText className="h-4 w-4 text-primary" />
                    <span className="font-medium text-sm">{name}</span>
                    {profile?.kind && <Badge variant="outline">{profile.kind}</Badge>}
                    {profile?.shape && (
                      <span className="text-xs text-muted-foreground tabular-nums">
                        shape [{profile.shape.join(' × ')}]
                      </span>
                    )}
                  </div>
                  {error && (
                    <div className="flex items-center gap-2 text-xs text-destructive">
                      <AlertCircle className="h-3.5 w-3.5" /> {error}
                    </div>
                  )}
                  {profile?.error && (
                    <div className="flex items-center gap-2 text-xs text-destructive">
                      <AlertCircle className="h-3.5 w-3.5" /> {profile.error}
                    </div>
                  )}
                  <div className="rounded-md border divide-y">
                    {rowKeys.length === 0 && (
                      <div className="px-3 py-4 text-xs text-muted-foreground">No structured fields extracted.</div>
                    )}
                    {rowKeys.map((key) => {
                      const row = rows[key]
                      if (!row) return null
                      return (
                        <div key={key} className="flex items-start gap-3 px-3 py-2">
                          <div className="w-44 shrink-0">
                            <div className="text-xs font-mono truncate" title={row.fieldPath}>
                              {row.fieldPath.split('::').slice(1).join('::') || row.fieldPath}
                            </div>
                            <div className="text-[10px] text-muted-foreground truncate" title={row.summary}>
                              {row.summary}
                            </div>
                          </div>
                          <Input
                            value={row.annotation}
                            placeholder="e.g. time in seconds, customer id, …"
                            onChange={(e) => patchRow(key, { annotation: e.target.value })}
                            disabled={row.skip}
                            className="flex-1 h-8 text-xs"
                          />
                          <Button
                            size="sm"
                            variant={row.skip ? 'outline' : 'ghost'}
                            onClick={() => patchRow(key, { skip: !row.skip })}
                            title={row.skip ? 'Include' : 'Skip'}
                          >
                            {row.skip ? <Check className="h-3.5 w-3.5" /> : <XIcon className="h-3.5 w-3.5" />}
                          </Button>
                        </div>
                      )
                    })}
                  </div>
                </section>
              ))}
            </div>
          </ScrollArea>
        </DialogBody>
        <DialogFooter>
          <div className="flex items-center gap-3 w-full">
            <span className="text-xs text-muted-foreground">{rowCount} field{rowCount === 1 ? '' : 's'} to confirm</span>
            <div className="flex-1" />
            {result && <span className="text-xs text-muted-foreground">{result}</span>}
            <Button variant="outline" onClick={onClose} disabled={submitting}>Cancel</Button>
            <Button onClick={handleConfirm} disabled={submitting || rowCount === 0}>
              {submitting ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> : <Check className="h-3.5 w-3.5 mr-1.5" />}
              {submitting ? 'Confirming…' : 'Confirm'}
            </Button>
          </div>
        </DialogFooter>
      </div>
    </Dialog>
  )
}

function buildRows(uploaded: UploadedProfile[]): Record<string, Row> {
  const out: Record<string, Row> = {}
  for (const u of uploaded) {
    const filename = u.name
    const profile = u.profile
    if (!profile) continue
    // File-level row (matches _stage_rows in profile.py)
    out[`${filename}::_file`] = {
      fieldPath: `${filename}::_file`,
      summary: `kind=${profile.kind ?? '?'} bytes=${profile.bytes ?? '?'} shape=${JSON.stringify(profile.shape ?? null)}`,
      annotation: '',
      skip: false,
    }
    if (profile.kind === 'csv' || profile.kind === 'parquet') {
      for (const c of profile.columns ?? []) {
        const parts = [`dtype=${c.dtype}`]
        for (const k of ['min', 'max', 'mean', 'unique', 'nulls'] as const) {
          const v = (c as any)[k]
          if (v !== undefined && v !== null) parts.push(`${k}=${v}`)
        }
        out[`${filename}::${c.name}`] = {
          fieldPath: `${filename}::${c.name}`,
          summary: parts.join(' '),
          annotation: '',
          skip: false,
        }
      }
    } else if (profile.kind === 'h5') {
      for (const ds of profile.datasets ?? []) {
        out[`${filename}::${ds.name}`] = {
          fieldPath: `${filename}::${ds.name}`,
          summary: `shape=${JSON.stringify(ds.shape)} dtype=${ds.dtype}`,
          annotation: '',
          skip: false,
        }
      }
    } else if (profile.kind === 'npz' && profile.arrays) {
      for (const [n, a] of Object.entries(profile.arrays)) {
        out[`${filename}::${n}`] = {
          fieldPath: `${filename}::${n}`,
          summary: `shape=${JSON.stringify(a.shape)} dtype=${a.dtype}`,
          annotation: '',
          skip: false,
        }
      }
    } else if (profile.kind === 'netcdf' && profile.variables) {
      for (const [n, v] of Object.entries(profile.variables)) {
        out[`${filename}::${n}`] = {
          fieldPath: `${filename}::${n}`,
          summary: `shape=${JSON.stringify(v.shape)} dtype=${v.dtype}`,
          annotation: '',
          skip: false,
        }
      }
    } else if (profile.kind === 'sqlite' && profile.tables) {
      for (const [t, info] of Object.entries(profile.tables)) {
        out[`${filename}::${t}`] = {
          fieldPath: `${filename}::${t}`,
          summary: `rows=${info.rows} columns=${info.columns?.length ?? 0}`,
          annotation: '',
          skip: false,
        }
      }
    } else if (profile.kind === 'json' && profile.keys) {
      for (const k of profile.keys) {
        out[`${filename}::${k}`] = {
          fieldPath: `${filename}::${k}`,
          summary: `top_type=${profile.top_type}`,
          annotation: '',
          skip: false,
        }
      }
    }
  }
  return out
}

function groupByFile(uploaded: UploadedProfile[]) {
  return uploaded.map((u) => {
    const rowKeys: string[] = []
    const filename = u.name
    const profile = u.profile
    if (profile) {
      rowKeys.push(`${filename}::_file`)
      const push = (k: string) => rowKeys.push(`${filename}::${k}`)
      if (profile.kind === 'csv' || profile.kind === 'parquet') profile.columns?.forEach((c) => push(c.name))
      else if (profile.kind === 'h5') profile.datasets?.forEach((d) => push(d.name))
      else if (profile.kind === 'npz' && profile.arrays) Object.keys(profile.arrays).forEach(push)
      else if (profile.kind === 'netcdf' && profile.variables) Object.keys(profile.variables).forEach(push)
      else if (profile.kind === 'sqlite' && profile.tables) Object.keys(profile.tables).forEach(push)
      else if (profile.kind === 'json' && profile.keys) profile.keys.forEach(push)
    }
    return { name: filename, profile, error: u.error, rowKeys }
  })
}
