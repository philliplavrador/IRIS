import { BarChart3, FileText, FolderOpen, Brain, CheckSquare, Sliders } from 'lucide-react'
import { useWorkspaceStore } from '../../stores/workspace-store'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../ui/tabs'
import { PlotViewer } from '../visualization/PlotViewer'
import { ReportViewer } from '../ReportViewer'
import { FileManager } from './FileManager'
import { MemoryInspector } from './MemoryInspector'
import { CurationRitual } from './CurationRitual'
import { BehaviorConfig } from './BehaviorConfig'
import { cn } from '../../lib/utils'
import type { WorkspaceTab } from '../../types'

const tabs: Array<{ value: WorkspaceTab; label: string; icon: React.ReactNode }> = [
  { value: 'plots', label: 'Plots', icon: <BarChart3 className="h-3.5 w-3.5" /> },
  { value: 'report', label: 'Report', icon: <FileText className="h-3.5 w-3.5" /> },
  { value: 'files', label: 'Files', icon: <FolderOpen className="h-3.5 w-3.5" /> },
  { value: 'memory', label: 'Memory', icon: <Brain className="h-3.5 w-3.5" /> },
  { value: 'curation', label: 'Curate', icon: <CheckSquare className="h-3.5 w-3.5" /> },
  { value: 'behavior', label: 'Behavior', icon: <Sliders className="h-3.5 w-3.5" /> },
]

export function WorkspaceTabs() {
  const activeTab = useWorkspaceStore((s) => s.activeTab)
  const setActiveTab = useWorkspaceStore((s) => s.setActiveTab)

  return (
    <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as WorkspaceTab)} className="h-full">
      <div className="border-b px-6 pt-1 shrink-0">
        <TabsList className="h-11 bg-transparent p-0 gap-1.5">
          {tabs.map((tab) => (
            <TabsTrigger
              key={tab.value}
              value={tab.value}
              className={cn(
                "gap-1.5 rounded-md px-3.5 relative",
                "data-[state=active]:bg-transparent data-[state=active]:shadow-none"
              )}
            >
              {tab.icon}
              {tab.label}
              {/* Active underline indicator */}
              {activeTab === tab.value && (
                <span className="absolute bottom-0 left-2 right-2 h-0.5 bg-primary rounded-full" />
              )}
            </TabsTrigger>
          ))}
        </TabsList>
      </div>

      <TabsContent value="plots" className="flex-1 min-h-0 animate-fade-in">
        <PlotViewer />
      </TabsContent>

      <TabsContent value="report" className="flex-1 min-h-0 animate-fade-in">
        <ReportViewer />
      </TabsContent>

      <TabsContent value="files" className="flex-1 min-h-0 animate-fade-in">
        <FileManager />
      </TabsContent>

      <TabsContent value="memory" className="flex-1 min-h-0 animate-fade-in">
        <MemoryInspector />
      </TabsContent>

      <TabsContent value="curation" className="flex-1 min-h-0 animate-fade-in">
        <CurationRitual />
      </TabsContent>

      <TabsContent value="behavior" className="flex-1 min-h-0 animate-fade-in">
        <BehaviorConfig />
      </TabsContent>
    </Tabs>
  )
}
