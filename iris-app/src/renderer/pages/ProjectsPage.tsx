import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, RefreshCw, FolderOpen, Settings, SlidersHorizontal, Loader2, ChevronRight, BarChart3, FileText } from 'lucide-react'
import { useProjectStore } from '../stores/project-store'
import { useWorkspaceStore } from '../stores/workspace-store'
import { api } from '../lib/api'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { ThemeToggle } from '../components/shared/ThemeToggle'
import { GlobalSettings } from '../components/shared/GlobalSettings'
import { ProjectSettings } from '../components/workspace/ProjectSettings'
import { cn } from '../lib/utils'
import type { ProjectInfo } from '../types'

function isRealDescription(desc?: string | null): desc is string {
  if (!desc) return false
  if (desc === 'null') return false
  if (desc.includes('filled in by')) return false
  return desc.trim().length > 0
}

export function ProjectsPage() {
  const projects = useProjectStore((s) => s.projects)
  const setProjects = useProjectStore((s) => s.setProjects)
  const setActiveProject = useProjectStore((s) => s.setActiveProject)
  const navigate = useNavigate()

  const [isCreating, setIsCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [settingsProject, setSettingsProject] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [openingProject, setOpeningProject] = useState<string | null>(null)
  const [creatingProject, setCreatingProject] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [globalSettingsOpen, setGlobalSettingsOpen] = useState(false)

  useEffect(() => {
    refresh().finally(() => setLoading(false))
  }, [])

  async function refresh() {
    setRefreshing(true)
    try {
      const list = await api.projectList()
      setProjects(list)
    } catch {}
    setRefreshing(false)
  }

  async function openProject(name: string) {
    setOpeningProject(name)
    try {
      await api.projectOpen(name)
      const reportContent = await api.reportContent(name)
      useWorkspaceStore.getState().setReportContent(reportContent)
      setActiveProject(name)
      navigate(`/project/${name}`)
    } catch (err) {
      console.error('Failed to open project:', err)
    }
    setOpeningProject(null)
  }

  async function handleCreate() {
    const name = newName.trim()
    if (!name) return
    setError(null)
    setCreatingProject(true)
    try {
      await api.projectCreate(name, newDesc.trim() || undefined)
      await refresh()
      setNewName('')
      setNewDesc('')
      setIsCreating(false)
      openProject(name)
    } catch (err: any) {
      setError(err.message || 'Failed to create project')
    }
    setCreatingProject(false)
  }


  if (loading) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center bg-background">
        <div className="animate-fade-in-up flex flex-col items-center">
          <div className="w-12 h-12 mb-6 rounded-2xl bg-primary/10 flex items-center justify-center">
            <Loader2 className="h-5 w-5 text-primary animate-spin" />
          </div>
          <div className="skeleton h-3 w-24 rounded mb-2" />
          <div className="skeleton h-2.5 w-40 rounded" />
        </div>
      </div>
    )
  }

  return (
    <div className="h-full w-full flex flex-col bg-background relative overflow-hidden">
      {/* Ambient background glow */}
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[600px] h-[400px] bg-primary/[0.04] rounded-full blur-3xl pointer-events-none" />

      {/* Top bar */}
      <div className="flex items-center justify-between px-5 py-4 relative z-10">
        <span className="text-xs text-muted-foreground/50 font-medium tracking-wide uppercase">IRIS</span>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon" onClick={() => setGlobalSettingsOpen(true)} title="Global settings" className="h-8 w-8">
            <SlidersHorizontal className="h-4 w-4" />
          </Button>
          <ThemeToggle />
        </div>
      </div>

      <div className="flex-1 flex items-center justify-center relative z-10">
        <div className="w-full max-w-lg px-6">
          {/* Header */}
          <div className="mb-8 animate-fade-in-up">
            <h1 className="text-3xl font-bold tracking-tight">Projects</h1>
            <p className="text-sm text-muted-foreground mt-1.5">
              {projects.length > 0
                ? `${projects.length} project${projects.length !== 1 ? 's' : ''}`
                : 'Create your first project to get started'}
            </p>
          </div>

          {/* Project list */}
          <div className="space-y-2 mb-6 stagger-children">
            {projects.map((project: ProjectInfo) => (
              <div key={project.name} className="relative">
                  <div className={cn(
                    "rounded-xl border bg-card transition-all duration-200 group overflow-hidden",
                    "hover:bg-accent/50 hover:border-border",
                    openingProject === project.name && "border-primary/40 bg-primary/5"
                  )}>
                    <div className="flex items-center">
                      <button
                        onClick={() => openProject(project.name)}
                        className="flex-1 text-left px-4 py-3.5 cursor-pointer"
                        disabled={openingProject !== null}
                      >
                        <div className="flex items-center gap-3">
                          <div className={cn(
                            "w-10 h-10 rounded-xl flex items-center justify-center shrink-0 transition-colors",
                            openingProject === project.name
                              ? "bg-primary/15"
                              : "bg-muted"
                          )}>
                            {openingProject === project.name ? (
                              <Loader2 className="h-4.5 w-4.5 text-primary animate-spin" />
                            ) : (
                              <FolderOpen className="h-4.5 w-4.5 text-muted-foreground" />
                            )}
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="text-sm font-semibold truncate">{project.name}</div>
                            {isRealDescription(project.description) && (
                              <div className="text-xs text-muted-foreground mt-0.5 truncate">{project.description}</div>
                            )}
                            {(project.n_outputs > 0 || project.n_references > 0) && (
                              <div className="flex items-center gap-2.5 mt-1">
                                {project.n_outputs > 0 && (
                                  <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                                    <BarChart3 className="h-3 w-3" />
                                    {project.n_outputs}
                                  </span>
                                )}
                                {project.n_references > 0 && (
                                  <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                                    <FileText className="h-3 w-3" />
                                    {project.n_references}
                                  </span>
                                )}
                              </div>
                            )}
                          </div>
                          <ChevronRight className={cn(
                            "h-4 w-4 text-muted-foreground/40 shrink-0 transition-all duration-200",
                            "group-hover:text-muted-foreground group-hover:translate-x-0.5",
                            openingProject === project.name && "opacity-0"
                          )} />
                        </div>
                      </button>

                      <div className="pr-2">
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            setActiveProject(project.name)
                            setSettingsProject(project.name)
                          }}
                          className="w-8 h-8 rounded-lg flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                          title="Project settings"
                        >
                          <Settings className="h-4 w-4" />
                        </button>
                      </div>
                    </div>
                    {/* Loading bar when opening */}
                    {openingProject === project.name && (
                      <div className="progress-bar-indeterminate" />
                    )}
                  </div>
              </div>
            ))}

            {projects.length === 0 && !isCreating && (
              <div className="text-center py-16 animate-fade-in">
                <div className="w-14 h-14 mx-auto mb-4 rounded-2xl bg-muted flex items-center justify-center">
                  <FolderOpen className="h-6 w-6 text-muted-foreground/50" />
                </div>
                <p className="text-sm text-muted-foreground">No projects yet</p>
              </div>
            )}
          </div>

          {/* Create form */}
          {isCreating ? (
            <div className="rounded-xl border bg-card p-4 animate-scale-in">
              <div className="text-sm font-semibold mb-3">New project</div>
              <Input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleCreate()
                  if (e.key === 'Escape') { setIsCreating(false); setError(null) }
                }}
                placeholder="Project name"
                autoFocus
                disabled={creatingProject}
              />
              <Input
                value={newDesc}
                onChange={(e) => setNewDesc(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleCreate()
                  if (e.key === 'Escape') { setIsCreating(false); setError(null) }
                }}
                placeholder="Description (optional)"
                className="mt-2"
                disabled={creatingProject}
              />
              {error && <p className="text-xs text-destructive mt-2 animate-fade-in">{error}</p>}
              <div className="flex gap-2 mt-3">
                <Button onClick={handleCreate} className="flex-1" disabled={creatingProject || !newName.trim()}>
                  {creatingProject ? <><Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" /> Creating...</> : 'Create'}
                </Button>
                <Button variant="ghost" onClick={() => { setIsCreating(false); setError(null) }} disabled={creatingProject}>Cancel</Button>
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-2 animate-fade-in">
              <Button onClick={() => setIsCreating(true)} variant="outline" className="flex-1 h-10 border-dashed">
                <Plus className="h-4 w-4 mr-1.5" /> New Project
              </Button>
              <Button variant="ghost" size="icon" onClick={refresh} title="Refresh" disabled={refreshing} className="h-10 w-10 shrink-0">
                <RefreshCw className={cn("h-4 w-4", refreshing && "animate-spin")} />
              </Button>
            </div>
          )}
        </div>
      </div>

      {/* Footer */}
      <div className="px-5 py-4 text-center relative z-10">
        <span className="text-[11px] text-muted-foreground/40">v0.2</span>
      </div>

      {/* Global settings dialog */}
      <GlobalSettings open={globalSettingsOpen} onOpenChange={setGlobalSettingsOpen} />

      {/* Project settings dialog */}
      <ProjectSettings
        open={settingsProject !== null}
        onOpenChange={(open) => {
          if (!open) {
            setSettingsProject(null)
            setActiveProject(null)
            refresh()
          }
        }}
      />
    </div>
  )
}
