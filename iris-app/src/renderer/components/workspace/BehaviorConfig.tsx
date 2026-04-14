import { useEffect, useState } from 'react'
import { Loader2, Save, AlertCircle, Check } from 'lucide-react'
import { useProjectStore } from '../../stores/project-store'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { Card } from '../ui/card'
import { ScrollArea } from '../ui/scroll-area'
import { api } from '../../lib/api'

const AUTONOMY_LEVELS = [
  { value: 'low', label: 'Low', hint: 'Reads only — every op, plot, and write is proposed.' },
  { value: 'medium', label: 'Medium', hint: 'Reads + profiling + cache-hit retrieval run freely.' },
  { value: 'high', label: 'High', hint: 'Re-execution of familiar ops runs freely; novel work is still proposed.' },
]

const PUSHBACK_LEVELS = [
  { value: 'light', label: 'Light' },
  { value: 'balanced', label: 'Balanced' },
  { value: 'rigorous', label: 'Rigorous' },
]

const PUSHBACK_DOMAINS: Array<{ key: string; label: string; hint: string }> = [
  { key: 'statistical', label: 'Statistical', hint: 'Assumptions, sample size, multiple comparisons, test selection.' },
  { key: 'methodological', label: 'Methodological', hint: 'Pipeline order, parameters, transforms, leakage, aggregation scope.' },
  { key: 'interpretive', label: 'Interpretive', hint: 'Causal vs. correlational, overgeneralization, domain plausibility.' },
]

const MEMORY_FIELDS: Array<{ key: string; label: string; kind: 'number' | 'bool' }> = [
  { key: 'pin_budget_tokens', label: 'Pinned slice budget (tokens)', kind: 'number' },
  { key: 'goals_active_max', label: 'Max active goals in slice', kind: 'number' },
  { key: 'digest_retention_days', label: 'Digest retention (days)', kind: 'number' },
  { key: 'recall_k_default', label: 'Default recall() k', kind: 'number' },
  { key: 'recall_recency_halflife_days', label: 'Recall recency halflife (days)', kind: 'number' },
  { key: 'use_user_memory', label: 'Use ~/.iris/user_memory', kind: 'bool' },
]

export function BehaviorConfig() {
  const project = useProjectStore((s) => s.activeProject)
  const [autonomy, setAutonomy] = useState('medium')
  const [pushback, setPushback] = useState<Record<string, string>>({})
  const [memory, setMemory] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState<string | null>(null)

  useEffect(() => {
    if (!project) return
    setLoading(true)
    api.projectBehavior(project)
      .then((d) => {
        setAutonomy(d.autonomy)
        setPushback(d.pushback)
        setMemory(d.memory)
      })
      .catch((e) => setStatus(`Load failed: ${e.message}`))
      .finally(() => setLoading(false))
  }, [project])

  async function save() {
    if (!project) return
    setSaving(true)
    setStatus(null)
    try {
      const memOut: Record<string, number | boolean> = {}
      for (const f of MEMORY_FIELDS) {
        const v = memory[f.key]
        if (v === undefined) continue
        if (f.kind === 'bool') memOut[f.key] = v === 'true'
        else {
          const n = Number(v)
          if (!Number.isNaN(n)) memOut[f.key] = n
        }
      }
      const ok = await api.projectBehaviorSave(project, { autonomy, pushback, memory: memOut })
      setStatus(ok ? 'Saved.' : 'Save failed.')
    } catch (e: any) {
      setStatus(`Save failed: ${e.message}`)
    }
    setSaving(false)
  }

  if (!project) {
    return <div className="p-6 text-sm text-muted-foreground">Open a project to edit behavior dials.</div>
  }

  return (
    <ScrollArea className="h-full">
      <div className="p-6 space-y-6 max-w-3xl">
        {loading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading…
          </div>
        )}

        <Card className="p-5 space-y-3">
          <div>
            <h3 className="text-sm font-semibold">Autonomy</h3>
            <p className="text-xs text-muted-foreground">What IRIS may run without explicit approval.</p>
          </div>
          <div className="flex gap-2">
            {AUTONOMY_LEVELS.map((lv) => (
              <Button
                key={lv.value}
                variant={autonomy === lv.value ? 'default' : 'outline'}
                size="sm"
                onClick={() => setAutonomy(lv.value)}
              >
                {lv.label}
              </Button>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            {AUTONOMY_LEVELS.find((l) => l.value === autonomy)?.hint}
          </p>
        </Card>

        <Card className="p-5 space-y-4">
          <div>
            <h3 className="text-sm font-semibold">Pushback</h3>
            <p className="text-xs text-muted-foreground">How firmly IRIS flags concerns in each domain.</p>
          </div>
          {PUSHBACK_DOMAINS.map((dom) => (
            <div key={dom.key} className="space-y-1.5">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-xs font-medium">{dom.label}</div>
                  <div className="text-[11px] text-muted-foreground">{dom.hint}</div>
                </div>
                <div className="flex gap-1">
                  {PUSHBACK_LEVELS.map((lv) => (
                    <Button
                      key={lv.value}
                      size="sm"
                      variant={pushback[dom.key] === lv.value ? 'default' : 'outline'}
                      onClick={() => setPushback((p) => ({ ...p, [dom.key]: lv.value }))}
                    >
                      {lv.label}
                    </Button>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </Card>

        <Card className="p-5 space-y-3">
          <div>
            <h3 className="text-sm font-semibold">Memory</h3>
            <p className="text-xs text-muted-foreground">Dials for pinned-slice assembly, retrieval, and archival.</p>
          </div>
          {MEMORY_FIELDS.map((f) => (
            <div key={f.key} className="flex items-center gap-3">
              <label className="text-xs flex-1">{f.label}</label>
              {f.kind === 'bool' ? (
                <div className="flex gap-1">
                  {['false', 'true'].map((v) => (
                    <Button
                      key={v}
                      size="sm"
                      variant={(memory[f.key] ?? 'false') === v ? 'default' : 'outline'}
                      onClick={() => setMemory((m) => ({ ...m, [f.key]: v }))}
                    >
                      {v}
                    </Button>
                  ))}
                </div>
              ) : (
                <Input
                  type="number"
                  value={memory[f.key] ?? ''}
                  onChange={(e) => setMemory((m) => ({ ...m, [f.key]: e.target.value }))}
                  className="h-8 text-xs w-32"
                />
              )}
            </div>
          ))}
        </Card>

        <div className="flex items-center gap-3">
          <Button onClick={save} disabled={saving || loading}>
            {saving ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> : <Save className="h-3.5 w-3.5 mr-1.5" />}
            {saving ? 'Saving…' : 'Save'}
          </Button>
          {status && (
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              {status.startsWith('Saved') ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <AlertCircle className="h-3.5 w-3.5 text-destructive" />}
              {status}
            </span>
          )}
        </div>
      </div>
    </ScrollArea>
  )
}
