import { create } from 'zustand'
import type { ProjectInfo } from '../types'

interface ProjectStore {
  projects: ProjectInfo[]
  activeProject: string | null

  setProjects: (projects: ProjectInfo[]) => void
  setActiveProject: (name: string | null) => void
}

export const useProjectStore = create<ProjectStore>((set) => ({
  projects: [],
  activeProject: null,

  setProjects: (projects) => set({ projects }),
  setActiveProject: (activeProject) => set({ activeProject }),
}))
