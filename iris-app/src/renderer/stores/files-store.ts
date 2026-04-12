import { create } from 'zustand'
import type { FileNode } from '../types'

interface FilesStore {
  tree: FileNode[]
  selectedFile: FileNode | null

  setTree: (tree: FileNode[]) => void
  setSelectedFile: (file: FileNode | null) => void
}

export const useFilesStore = create<FilesStore>((set) => ({
  tree: [],
  selectedFile: null,

  setTree: (tree) => set({ tree }),
  setSelectedFile: (selectedFile) => set({ selectedFile }),
}))
