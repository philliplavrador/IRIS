import { create } from 'zustand'
import type { PlotInfo, WorkspaceTab, ReportSection, SectionStatus } from '../types'

interface WorkspaceStore {
  activeTab: WorkspaceTab
  setActiveTab: (tab: WorkspaceTab) => void

  currentPlot: PlotInfo | null
  sessionPlots: PlotInfo[]
  setCurrentPlot: (plot: PlotInfo | null) => void
  addSessionPlot: (plot: PlotInfo) => void
  clearSessionPlots: () => void

  reportContent: string
  reportSections: ReportSection[]
  setReportContent: (content: string) => void
  setReportSections: (sections: ReportSection[]) => void
  updateSectionStatus: (id: string, status: SectionStatus, notes?: string) => void
}

export const useWorkspaceStore = create<WorkspaceStore>((set) => ({
  activeTab: 'plots',
  setActiveTab: (activeTab) => set({ activeTab }),

  currentPlot: null,
  sessionPlots: [],
  setCurrentPlot: (currentPlot) => set({ currentPlot }),
  addSessionPlot: (plot) =>
    set((s) => ({ sessionPlots: [...s.sessionPlots, plot] })),
  clearSessionPlots: () => set({ sessionPlots: [], currentPlot: null }),

  reportContent: '',
  reportSections: [],
  setReportContent: (reportContent) => set({ reportContent }),
  setReportSections: (reportSections) => set({ reportSections }),
  updateSectionStatus: (id, status, userNotes) =>
    set((s) => ({
      reportSections: s.reportSections.map((sec) =>
        sec.id === id ? { ...sec, status, userNotes: userNotes ?? sec.userNotes } : sec
      ),
    })),
}))
