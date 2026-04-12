import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, RefreshCw, FolderOpen, MoreVertical, Pencil, Trash2, Activity } from 'lucide-react'
import { useProjectStore } from '../stores/project-store'
import { useWorkspaceStore } from '../stores/workspace-store'
import { api } from '../lib/api'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Card, CardContent } from '../components/ui/card'
import { ThemeToggle } from '../components/shared/ThemeToggle'
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from '../components/ui/dropdown-menu'
import { cn } from '../lib/utils'
import type { ProjectInfo } from '../types'

export function ProjectsPage() {
  const projects = useProjectStore((s) => s.projects)
  const setProjects = useProjectStore((s) => s.setProjects)
  const setActiveProject = useProjectStore((s) => s.setActiveProject)
  const navigate = useNavigate()

  const [isCreating, setIsCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [editingProject, setEditingProject] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    refresh().finally(() => setLoading(false))
  }, [])

  async function refresh() {
    try {
      const list = await api.projectList()
      setProjects(list)
    } catch {}
  }

  async function openProject(name: string) {
    try {
      await api.projectOpen(name)
      const reportContent = await api.reportContent(name)
      useWorkspaceStore.getState().setReportContent(reportContent)
      setActiveProject(name)
      navigate(`/project/${name}`)
    } catch (err) {
      console.error('Failed to open project:', err)
    }
  }

  async function handleCreate() {
    const name = newName.trim()
    if (!name) return
    setError(null)
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
  }

  async function handleRename(oldName: string) {
    const name = renameValue.trim()
    if (!name || name === oldName) { setEditingProject(null); return }
    try {
      await api.projectRename(oldName, name)
      await refresh()
      setEditingProject(null)
    } catch {}
  }

  async function handleDelete(name: string) {
    try {
      await api.projectDelete(name)
      await refresh()
      setConfirmDelete(null)
    } catch {}
  }

  if (loading) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center bg-background">
        <Activity className="h-8 w-8 text-primary animate-pulse mb-3" />
        <p className="text-sm text-muted-foreground">Loading...</p>
      </div>
    )
  }

  return (
    <div className="h-full w-full flex flex-col bg-background">
      {/* Minimal top bar with theme toggle */}
      <div className="flex justify-end p-3">
        <ThemeToggle />
      </div>

      <div className="flex-1 flex items-center justify-center">
        <div className="w-full max-w-lg px-6">
          {/* Header */}
          <div className="text-center mb-8">
            <div className="w-14 h-14 mx-auto mb-4 rounded-2xl bg-primary flex items-center justify-center shadow-lg">
              <Activity className="h-7 w-7 text-primary-foreground" />
            </div>
            <h1 className="text-2xl font-bold">CASI</h1>
            <p className="text-sm text-muted-foreground mt-1">Select a project to get started</p>
          </div>

          {/* Project list */}
          <div className="space-y-2 mb-4">
            {projects.map((project: ProjectInfo) => (
              <div key={project.name} className="relative">
                {/* Delete confirmation */}
                {confirmDelete === project.name && (
                  <Card className="absolute inset-0 z-10 border-destructive">
                    <CardContent className="flex items-center justify-between p-4">
                      <span className="text-sm">Delete <strong>{project.name}</strong>?</span>
                      <div className="flex gap-2">
                        <Button size="sm" variant="destructive" onClick={() => handleDelete(project.name)}>Delete</Button>
                        <Button size="sm" variant="outline" onClick={() => setConfirmDelete(null)}>Cancel</Button>
                      </div>
                    </CardContent>
                  </Card>
                )}

                {/* Rename inline */}
                {editingProject === project.name ? (
                  <Card className="p-4">
                    <Input
                      value={renameValue}
                      onChange={(e) => setRenameValue(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleRename(project.name)
                        if (e.key === 'Escape') setEditingProject(null)
                      }}
                      autoFocus
                    />
                    <div className="flex gap-2 mt-2">
                      <Button size="sm" onClick={() => handleRename(project.name)}>Rename</Button>
                      <Button size="sm" variant="ghost" onClick={() => setEditingProject(null)}>Cancel</Button>
                    </div>
                  </Card>
                ) : (
                  <Card className="hover:border-primary/50 transition-colors group">
                    <div className="flex items-center">
                      <button
                        onClick={() => openProject(project.name)}
                        className="flex-1 text-left p-4 cursor-pointer"
                      >
                        <div className="flex items-center gap-3">
                          <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                            <FolderOpen className="h-4 w-4 text-primary" />
                          </div>
                          <div className="min-w-0">
                            <div className="text-sm font-medium truncate">{project.name}</div>
                            {project.description && (
                              <div className="text-xs text-muted-foreground mt-0.5 truncate">{project.description}</div>
                            )}
                            {project.n_outputs > 0 && (
                              <div className="text-xs text-muted-foreground mt-0.5">
                                {project.n_outputs} plot{project.n_outputs !== 1 ? 's' : ''}
                                {project.n_references > 0 && ` · ${project.n_references} ref${project.n_references !== 1 ? 's' : ''}`}
                              </div>
                            )}
                          </div>
                        </div>
                      </button>

                      <div className="pr-3">
                        <DropdownMenu>
                          <DropdownMenuTrigger className="w-8 h-8 rounded-md flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-accent transition-colors">
                            <MoreVertical className="h-4 w-4" />
                          </DropdownMenuTrigger>
                          <DropdownMenuContent>
                            <DropdownMenuItem onClick={() => { setRenameValue(project.name); setEditingProject(project.name) }}>
                              <Pencil className="h-3.5 w-3.5 mr-2" /> Rename
                            </DropdownMenuItem>
                            <DropdownMenuItem destructive onClick={() => setConfirmDelete(project.name)}>
                              <Trash2 className="h-3.5 w-3.5 mr-2" /> Delete
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    </div>
                  </Card>
                )}
              </div>
            ))}

            {projects.length === 0 && !isCreating && (
              <div className="text-center py-8 text-sm text-muted-foreground">
                No projects yet — create one to get started
              </div>
            )}
          </div>

          {/* Create form */}
          {isCreating ? (
            <Card className="p-4">
              <Input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleCreate()
                  if (e.key === 'Escape') setIsCreating(false)
                }}
                placeholder="Project name"
                autoFocus
              />
              <Input
                value={newDesc}
                onChange={(e) => setNewDesc(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleCreate()
                  if (e.key === 'Escape') setIsCreating(false)
                }}
                placeholder="Description (optional)"
                className="mt-2"
              />
              {error && <p className="text-xs text-destructive mt-2">{error}</p>}
              <div className="flex gap-2 mt-3">
                <Button onClick={handleCreate} className="flex-1">Create</Button>
                <Button variant="outline" onClick={() => { setIsCreating(false); setError(null) }} className="flex-1">Cancel</Button>
              </div>
            </Card>
          ) : (
            <div className="flex gap-2">
              <Button onClick={() => setIsCreating(true)} className="flex-1">
                <Plus className="h-4 w-4 mr-1.5" /> New Project
              </Button>
              <Button variant="outline" onClick={refresh} title="Refresh">
                <RefreshCw className="h-4 w-4" />
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
