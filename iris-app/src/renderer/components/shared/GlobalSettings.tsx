import { useCallback, useEffect, useState } from 'react'
import { Loader2, Save, Check, SlidersHorizontal } from 'lucide-react'
import { Dialog, DialogHeader, DialogTitle, DialogClose, DialogBody } from '../ui/dialog'
import { Button } from '../ui/button'
import { api } from '../../lib/api'

interface GlobalSettingsProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function GlobalSettings({ open, onOpenChange }: GlobalSettingsProps) {
  const [rules, setRules] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (!open) return
    setLoaded(false)
    api.agentRules().then((r) => {
      setRules(r)
      setLoaded(true)
    })
  }, [open])

  const handleSave = useCallback(async () => {
    setSaving(true)
    await api.agentRulesSave(rules)
    setSaving(false)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }, [rules])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <SlidersHorizontal className="h-4 w-4" />
          Global Settings
        </DialogTitle>
        <DialogClose onClose={() => onOpenChange(false)} />
      </DialogHeader>
      <DialogBody className="space-y-4">
        <div className="space-y-1.5">
          <label className="text-sm font-medium">Agent behavior rules</label>
          <p className="text-xs text-muted-foreground">
            These instructions are injected into every conversation across all projects.
            Use them to control how IRIS behaves — what to prioritize, what to avoid, how to handle ambiguity.
          </p>
        </div>

        {!loaded ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground py-8 justify-center">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading...
          </div>
        ) : (
          <>
            <textarea
              className="flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm font-mono placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring resize-none"
              rows={12}
              value={rules}
              onChange={(e) => setRules(e.target.value)}
              placeholder="e.g. Always use the data source the user requests. Never substitute a different dataset."
            />
            <div className="flex justify-end">
              <Button size="sm" onClick={handleSave} disabled={saving}>
                {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : saved ? <Check className="h-3.5 w-3.5" /> : <Save className="h-3.5 w-3.5" />}
                {saving ? 'Saving...' : saved ? 'Saved' : 'Save rules'}
              </Button>
            </div>
          </>
        )}
      </DialogBody>
    </Dialog>
  )
}
