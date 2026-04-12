import { BarChart3, FileText, FolderOpen } from 'lucide-react'
import { useWorkspaceStore } from '../../stores/workspace-store'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../ui/tabs'
import { PlotViewer } from '../visualization/PlotViewer'
import { ReportViewer } from '../ReportViewer'
import { FileManager } from './FileManager'
import type { WorkspaceTab } from '../../types'

const tabs: Array<{ value: WorkspaceTab; label: string; icon: React.ReactNode }> = [
  { value: 'plots', label: 'Plots', icon: <BarChart3 className="h-3.5 w-3.5" /> },
  { value: 'report', label: 'Report', icon: <FileText className="h-3.5 w-3.5" /> },
  { value: 'files', label: 'Files', icon: <FolderOpen className="h-3.5 w-3.5" /> },
]

export function WorkspaceTabs() {
  const activeTab = useWorkspaceStore((s) => s.activeTab)
  const setActiveTab = useWorkspaceStore((s) => s.setActiveTab)

  return (
    <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as WorkspaceTab)} className="h-full">
      <div className="border-b px-4 shrink-0">
        <TabsList className="h-10 bg-transparent p-0 gap-1">
          {tabs.map((tab) => (
            <TabsTrigger
              key={tab.value}
              value={tab.value}
              className="gap-1.5 data-[state=active]:bg-muted rounded-md px-3"
            >
              {tab.icon}
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </div>

      <TabsContent value="plots" className="flex-1 min-h-0">
        <PlotViewer />
      </TabsContent>

      <TabsContent value="report" className="flex-1 min-h-0">
        <ReportViewer />
      </TabsContent>

      <TabsContent value="files" className="flex-1 min-h-0">
        <FileManager />
      </TabsContent>
    </Tabs>
  )
}
