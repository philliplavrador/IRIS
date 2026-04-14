import { useEffect, useState } from 'react'
import { Loader2, Save, AlertCircle, Check } from 'lucide-react'
import { useProjectStore } from '../../stores/project-store'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { Card } from '../ui/card'
import { ScrollArea } from '../ui/scroll-area'
import { api } from '../../lib/api'

const AUTONOMY_LEVELS = [
  { value: '', label: 'Inherit', hint: 'Use the global default from ~/.iris/config.' },
  { value: 'low', label: 'Low', hint: 'Reads only — every op, plot, and write is proposed.' },
  { value: 'medium', label: 'Medium', hint: 'Reads + profiling + cache-hit retrieval run freely.' },
  { value: 'high', label: 'High', hint: 'Re-execution of familiar ops runs freely; novel work is still proposed.' },
]

const PUSHBACK_LEVELS = [
  { value: '', label: 'Inherit', hint: 'Use the global default.' },
  { value: 'light', label: 'Light', hint: 'Flag only clear blockers.' },
  { value: 'balanced', label: 'Balanced', hint: 'Raise meaningful statistical, methodological, and interpretive concerns.' },
  { value: 'rigorous', label: 'Rigorous', hint: 'Challenge assumptions aggressively before running anything novel.' },
]

export function BehaviorConfig() {
  const project = useProjectStore((s) => s.activeProject)
  const [autonomy, setAutonomy] = useState('')
  const [pushback, setPushback] = useState('')
  const [sliceBudget, setSliceBudget] = useState('0')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState<string | null>(null)

  useEffect(() => {
    if (!project) return
    setLoading(true)
    setStatus(null)
    api.projectBehavior(project)
      .then((d) => {
        setAutonomy(d?.autonomy ?? '')
        setPushback(d?.pushback ?? '')
        setSliceBudget(String(d?.memory?.slice_budget_tokens ?? 0))
      })
      .catch((e) => setStatus(`Load failed: ${e.message}`))
      .finally(() => setLoading(false))
  }, [project])

  async function save() {
    if (!project) return
    setSaving(true)
    setStatus(null)
    try {
      const budget = Number(sliceBudget)
      const memory = Number.isFinite(budget) ? { slice_budget_tokens: budget } : undefined
      const ok = await api.projectBehaviorSave(project, { autonomy, pushback, memory })
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
          <div className="flex flex-wrap gap-2">
            {AUTONOMY_LEVELS.map((lv) => (
              <Button
                key={lv.value || 'inherit'}
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

        <Card className="p-5 space-y-3">
          <div>
            <h3 className="text-sm font-semibold">Pushback</h3>
            <p className="text-xs text-muted-foreground">How firmly IRIS flags statistical, methodological, and interpretive concerns.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {PUSHBACK_LEVELS.map((lv) => (
              <Button
                key={lv.value || 'inherit'}
                variant={pushback === lv.value ? 'default' : 'outline'}
                size="sm"
                onClick={() => setPushback(lv.value)}
              >
                {lv.label}
              </Button>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            {PUSHBACK_LEVELS.find((l) => l.value === pushback)?.hint}
          </p>
        </Card>

        <Card className="p-5 space-y-3">
          <div>
            <h3 className="text-sm font-semibold">Memory</h3>
            <p className="text-xs text-muted-foreground">Pinned-slice budget for the agent's system prompt. 0 inherits the global default.</p>
          </div>
          <div className="flex items-center gap-3">
            <label className="text-xs flex-1">Slice budget (tokens)</label>
            <Input
              type="number"
              value={sliceBudget}
              onChange={(e) => setSliceBudget(e.target.value)}
              className="h-8 text-xs w-32"
            />
          </div>
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
