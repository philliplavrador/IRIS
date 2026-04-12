import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Activity } from 'lucide-react'
import { useProjectStore } from '../stores/project-store'
import { useWorkspaceStore } from '../stores/workspace-store'
import { useChatStore } from '../stores/chat-store'
import { useAgentMessages } from '../hooks/useAgentMessages'
import { api } from '../lib/api'
import { WorkspaceLayout } from '../components/layout/WorkspaceLayout'

export function WorkspacePage() {
  const { name } = useParams<{ name: string }>()
  const navigate = useNavigate()
  const activeProject = useProjectStore((s) => s.activeProject)
  const setActiveProject = useProjectStore((s) => s.setActiveProject)
  const [loading, setLoading] = useState(!activeProject || activeProject !== name)

  useAgentMessages()

  useEffect(() => {
    if (!name) { navigate('/'); return }

    if (activeProject === name) {
      setLoading(false)
      return
    }

    async function init() {
      try {
        await api.projectOpen(name!)
        const reportContent = await api.reportContent(name!)
        useWorkspaceStore.getState().setReportContent(reportContent)
        setActiveProject(name!)
      } catch (err) {
        console.error('Failed to open project:', err)
        navigate('/')
      }
      setLoading(false)
    }
    init()
  }, [name, activeProject, setActiveProject, navigate])

  if (loading) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center bg-background">
        <Activity className="h-8 w-8 text-primary animate-pulse mb-3" />
        <p className="text-sm text-muted-foreground">Loading project...</p>
      </div>
    )
  }

  return <WorkspaceLayout />
}
