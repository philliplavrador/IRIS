import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Pencil, Trash2, Download, MessageSquareOff, FileCode2,
  Brain, Save, Loader2, Check, AlertTriangle, FolderOpen
} from 'lucide-react'
import { Dialog, DialogHeader, DialogTitle, DialogClose, DialogBody } from '../ui/dialog'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../ui/tabs'
import { useProjectStore } from '../../stores/project-store'
import { useChatStore } from '../../stores/chat-store'
import { useWorkspaceStore } from '../../stores/workspace-store'
import { api } from '../../lib/api'
import { cn } from '../../lib/utils'

interface ProjectSettingsProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

type ConfirmAction = 'clear-conversations' | 'delete-project' | null

export function ProjectSettings({ open, onOpenChange }: ProjectSettingsProps) {
  const activeProject = useProjectStore((s) => s.activeProject)
  const setActiveProject = useProjectStore((s) => s.setActiveProject)
  const clearMessages = useChatStore((s) => s.clearMessages)
  const clearSessionPlots = useWorkspaceStore((s) => s.clearSessionPlots)
  const navigate = useNavigate()

  const [tab, setTab] = useState('general')

  // General
  const [renameValue, setRenameValue] = useState('')
  const [description, setDescription] = useState('')
  const [agentNotes, setAgentNotes] = useState('')
  const [configLoaded, setConfigLoaded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  // Memory
  const [memory, setMemory] = useState('')
  const [memoryLoaded, setMemoryLoaded] = useState(false)
  const [memorySaving, setMemorySaving] = useState(false)
  const [memorySaved, setMemorySaved] = useState(false)

  // Custom ops
  const [customOps, setCustomOps] = useState<string[]>([])
  const [selectedOp, setSelectedOp] = useState<string | null>(null)
  const [opSource, setOpSource] = useState<string | null>(null)

  // Files
  const [files, setFiles] = useState<{ name: string; path: string; type: 'file' | 'dir'; size: number }[]>([])

  // Confirm
  const [confirmAction, setConfirmAction] = useState<ConfirmAction>(null)
  const [confirmInput, setConfirmInput] = useState('')
  const [actionLoading, setActionLoading] = useState(false)

  // Load project config on open
  useEffect(() => {
    if (!open || !activeProject) return
    setConfigLoaded(false)
    setMemoryLoaded(false)
    setRenameValue(activeProject)

    api.projectInfo(activeProject).then((raw) => {
      if (!raw) return
      const parseYamlVal = (key: string) => {
        const m = raw.match(new RegExp(`${key}:\\s*(.+)`))
        if (!m) return ''
        const val = m[1].replace(/#.*/, '').trim()
        return val === 'null' ? '' : val
      }
      setDescription(parseYamlVal('description'))
      setAgentNotes(parseYamlVal('agent_notes'))
      setConfigLoaded(true)
    })
  }, [open, activeProject])

  // Load tab-specific data lazily
  useEffect(() => {
    if (!open || !activeProject) return
    if (tab === 'memory' && !memoryLoaded) {
      api.projectMemory(activeProject).then((content) => {
        setMemory(content)
        setMemoryLoaded(true)
      })
    }
    if (tab === 'ops') {
      api.projectCustomOps(activeProject).then(setCustomOps)
    }
    if (tab === 'files') {
      api.projectFiles(activeProject).then(setFiles)
    }
  }, [open, activeProject, tab, memoryLoaded])

  const handleSaveConfig = useCallback(async () => {
    if (!activeProject) return
    setSaving(true)
    // Rename if changed
    if (renameValue && renameValue !== activeProject) {
      const ok = await api.projectRename(activeProject, renameValue)
      if (ok) {
        setActiveProject(renameValue)
      }
    }
    const currentName = renameValue || activeProject
    await api.projectUpdateConfig(currentName, { description: description || undefined, agentNotes: agentNotes || undefined })
    setSaving(false)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }, [activeProject, renameValue, description, agentNotes, setActiveProject])

  const handleSaveMemory = useCallback(async () => {
    if (!activeProject) return
    setMemorySaving(true)
    await api.projectMemorySave(activeProject, memory)
    setMemorySaving(false)
    setMemorySaved(true)
    setTimeout(() => setMemorySaved(false), 2000)
  }, [activeProject, memory])

  const handleClearConversations = useCallback(async () => {
    if (!activeProject) return
    setActionLoading(true)
    await api.projectClearConversations(activeProject)
    clearMessages()
    setActionLoading(false)
    setConfirmAction(null)
    setConfirmInput('')
  }, [activeProject, clearMessages])

  const handleDeleteProject = useCallback(async () => {
    if (!activeProject) return
    setActionLoading(true)
    await api.projectDelete(activeProject)
    setActionLoading(false)
    setConfirmAction(null)
    setConfirmInput('')
    onOpenChange(false)
    setActiveProject(null)
    navigate('/')
  }, [activeProject, onOpenChange, setActiveProject, navigate])

  const handleExport = useCallback(() => {
    if (!activeProject) return
    window.open(api.projectExportUrl(activeProject), '_blank')
  }, [activeProject])

  const handleViewOp = useCallback(async (op: string) => {
    if (!activeProject) return
    setSelectedOp(op)
    const content = await api.projectCustomOpRead(activeProject, op)
    setOpSource(content)
  }, [activeProject])

  const handleDeleteFile = useCallback(async (filePath: string) => {
    if (!activeProject) return
    await api.projectDeleteFile(activeProject, filePath)
    const updated = await api.projectFiles(activeProject)
    setFiles(updated)
  }, [activeProject])

  const formatSize = (bytes: number) => {
    if (bytes === 0) return '--'
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  if (!activeProject) return null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle>Project Settings</DialogTitle>
        <DialogClose onClose={() => onOpenChange(false)} />
      </DialogHeader>
      <DialogBody className="p-0">
        <Tabs value={tab} onValueChange={setTab} className="h-full">
          <div className="px-6 pt-4 pb-0">
            <TabsList className="w-full">
              <TabsTrigger value="general" className="flex-1 text-xs">General</TabsTrigger>
              <TabsTrigger value="files" className="flex-1 text-xs">Files</TabsTrigger>
              <TabsTrigger value="memory" className="flex-1 text-xs">Memory</TabsTrigger>
              <TabsTrigger value="ops" className="flex-1 text-xs">Ops</TabsTrigger>
            </TabsList>
          </div>

          {/* General tab */}
          <TabsContent value="general" className="px-6 py-4 space-y-5 overflow-y-auto">
            {!configLoaded ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground py-8 justify-center">
                <Loader2 className="h-4 w-4 animate-spin" /> Loading...
              </div>
            ) : (
              <>
                <Section title="Project name">
                  <div className="flex gap-2">
                    <Input
                      value={renameValue}
                      onChange={(e) => setRenameValue(e.target.value)}
                      placeholder="Project name"
                    />
                  </div>
                </Section>

                <Section title="Description">
                  <Input
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="Brief description of this project"
                  />
                </Section>

                <Section title="Agent notes" hint="Instructions the AI should follow for this project">
                  <textarea
                    className="flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring resize-none"
                    rows={3}
                    value={agentNotes}
                    onChange={(e) => setAgentNotes(e.target.value)}
                    placeholder="e.g. Only use matplotlib for figures. Prefer narrow-band analyses."
                  />
                </Section>

                <div className="flex justify-end">
                  <Button size="sm" onClick={handleSaveConfig} disabled={saving}>
                    {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : saved ? <Check className="h-3.5 w-3.5" /> : <Save className="h-3.5 w-3.5" />}
                    {saving ? 'Saving...' : saved ? 'Saved' : 'Save changes'}
                  </Button>
                </div>

                <div className="border-t pt-5 space-y-3">
                  <h3 className="text-sm font-medium text-muted-foreground">Actions</h3>

                  <div className="flex flex-wrap gap-2">
                    <Button variant="outline" size="sm" onClick={handleExport}>
                      <Download className="h-3.5 w-3.5" /> Export project
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => setConfirmAction('clear-conversations')}>
                      <MessageSquareOff className="h-3.5 w-3.5" /> Clear conversations
                    </Button>
                  </div>
                </div>

                <div className="border-t pt-5">
                  <h3 className="text-sm font-medium text-destructive mb-3">Danger zone</h3>
                  <Button variant="destructive" size="sm" onClick={() => setConfirmAction('delete-project')}>
                    <Trash2 className="h-3.5 w-3.5" /> Delete project
                  </Button>
                </div>
              </>
            )}
          </TabsContent>

          {/* Files tab */}
          <TabsContent value="files" className="px-6 py-4 overflow-y-auto">
            {files.length === 0 ? (
              <div className="text-sm text-muted-foreground py-8 text-center">
                <FolderOpen className="h-8 w-8 mx-auto mb-2 opacity-40" />
                No files in this project
              </div>
            ) : (
              <div className="space-y-1">
                {files.filter(f => f.type === 'file').map((f) => (
                  <div key={f.path} className="flex items-center justify-between py-1.5 px-2 rounded-md hover:bg-muted/50 group">
                    <div className="min-w-0 flex-1">
                      <span className="text-sm truncate block">{f.path}</span>
                      <span className="text-xs text-muted-foreground">{formatSize(f.size)}</span>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 opacity-0 group-hover:opacity-100 text-destructive hover:text-destructive"
                      onClick={() => handleDeleteFile(f.path)}
                      title="Delete file"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </TabsContent>

          {/* Memory tab */}
          <TabsContent value="memory" className="px-6 py-4 space-y-3 overflow-y-auto">
            <p className="text-xs text-muted-foreground">
              Data profiles, learned facts, and analysis state. The AI reads this on every prompt.
            </p>
            {!memoryLoaded ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground py-8 justify-center">
                <Loader2 className="h-4 w-4 animate-spin" /> Loading...
              </div>
            ) : memory ? (
              <>
                <textarea
                  className="flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm font-mono placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring resize-none"
                  rows={14}
                  value={memory}
                  onChange={(e) => setMemory(e.target.value)}
                />
                <div className="flex justify-end">
                  <Button size="sm" onClick={handleSaveMemory} disabled={memorySaving}>
                    {memorySaving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : memorySaved ? <Check className="h-3.5 w-3.5" /> : <Save className="h-3.5 w-3.5" />}
                    {memorySaving ? 'Saving...' : memorySaved ? 'Saved' : 'Save memory'}
                  </Button>
                </div>
              </>
            ) : (
              <div className="text-sm text-muted-foreground py-8 text-center">
                <Brain className="h-8 w-8 mx-auto mb-2 opacity-40" />
                No memory yet. The AI will populate this as it learns about your data.
              </div>
            )}
          </TabsContent>

          {/* Custom ops tab */}
          <TabsContent value="ops" className="px-6 py-4 overflow-y-auto">
            {customOps.length === 0 ? (
              <div className="text-sm text-muted-foreground py-8 text-center">
                <FileCode2 className="h-8 w-8 mx-auto mb-2 opacity-40" />
                No custom operations. Ask the AI to create project-specific ops.
              </div>
            ) : (
              <div className="space-y-2">
                {customOps.map((op) => (
                  <div key={op}>
                    <button
                      className={cn(
                        "w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm text-left transition-colors",
                        selectedOp === op ? "bg-accent" : "hover:bg-muted/50"
                      )}
                      onClick={() => handleViewOp(op)}
                    >
                      <FileCode2 className="h-4 w-4 text-muted-foreground shrink-0" />
                      {op}
                    </button>
                    {selectedOp === op && opSource !== null && (
                      <pre className="mt-1 p-3 bg-muted rounded-md text-xs font-mono overflow-x-auto max-h-64 overflow-y-auto">
                        {opSource}
                      </pre>
                    )}
                  </div>
                ))}
              </div>
            )}
          </TabsContent>
        </Tabs>
      </DialogBody>

      {/* Confirmation overlay */}
      {confirmAction && (
        <div className="absolute inset-0 z-10 bg-background/95 rounded-xl flex flex-col items-center justify-center p-8 animate-fade-in">
          <AlertTriangle className={cn("h-10 w-10 mb-4", confirmAction === 'delete-project' ? 'text-destructive' : 'text-amber-500')} />
          <h3 className="text-lg font-semibold mb-2">
            {confirmAction === 'delete-project' ? 'Delete project?' : 'Clear all conversations?'}
          </h3>
          <p className="text-sm text-muted-foreground text-center mb-4 max-w-sm">
            {confirmAction === 'delete-project'
              ? `This will permanently delete "${activeProject}" and all its data. This cannot be undone.`
              : 'This will remove all conversation history. Your data, plots, and reports will be kept.'}
          </p>
          {confirmAction === 'delete-project' && (
            <div className="w-full max-w-xs mb-4">
              <p className="text-xs text-muted-foreground mb-1.5">Type the project name to confirm:</p>
              <Input
                value={confirmInput}
                onChange={(e) => setConfirmInput(e.target.value)}
                placeholder={activeProject}
                className="text-center"
              />
            </div>
          )}
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => { setConfirmAction(null); setConfirmInput('') }}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              size="sm"
              disabled={actionLoading || (confirmAction === 'delete-project' && confirmInput !== activeProject)}
              onClick={confirmAction === 'delete-project' ? handleDeleteProject : handleClearConversations}
            >
              {actionLoading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              {confirmAction === 'delete-project' ? 'Delete forever' : 'Clear conversations'}
            </Button>
          </div>
        </div>
      )}
    </Dialog>
  )
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="text-sm font-medium">{title}</label>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      {children}
    </div>
  )
}
