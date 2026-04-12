import { useEffect, useRef, useState } from 'react'
import { Upload, FolderPlus, RefreshCw, File, Folder, ChevronRight, ChevronDown, Trash2, Pencil } from 'lucide-react'
import { useProjectStore } from '../../stores/project-store'
import { useFilesStore } from '../../stores/files-store'
import { api } from '../../lib/api'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { ScrollArea } from '../ui/scroll-area'
import { cn } from '../../lib/utils'
import type { FileNode } from '../../types'

export function FileManager() {
  const activeProject = useProjectStore((s) => s.activeProject)
  const tree = useFilesStore((s) => s.tree)
  const setTree = useFilesStore((s) => s.setTree)
  const selectedFile = useFilesStore((s) => s.selectedFile)
  const setSelectedFile = useFilesStore((s) => s.setSelectedFile)
  const [search, setSearch] = useState('')
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!activeProject) return
    loadTree()
  }, [activeProject])

  async function loadTree() {
    if (!activeProject) return
    try {
      const files = await api.projectFiles(activeProject)
      setTree(buildTree(files))
    } catch {
      setTree([])
    }
  }

  async function handleUpload(fileList: FileList | null) {
    if (!fileList || !activeProject) return
    setUploading(true)
    try {
      await api.projectUpload(activeProject, fileList)
      await loadTree()
    } catch (err) {
      console.error('Upload failed:', err)
    }
    setUploading(false)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  return (
    <div className="h-full flex flex-col">
      <input ref={fileInputRef} type="file" multiple className="hidden" onChange={(e) => handleUpload(e.target.files)} />

      {/* Toolbar */}
      <div className="flex items-center gap-2 p-3 border-b shrink-0">
        <Button size="sm" variant="outline" onClick={() => fileInputRef.current?.click()} disabled={uploading}>
          <Upload className="h-3.5 w-3.5 mr-1.5" />
          {uploading ? 'Uploading...' : 'Upload'}
        </Button>
        <Button size="sm" variant="outline" onClick={loadTree}>
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
          Refresh
        </Button>
        <div className="flex-1" />
        <Input
          placeholder="Search files..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-48 h-8 text-xs"
        />
      </div>

      {/* Tree + Preview split */}
      <div className="flex-1 min-h-0 flex">
        {/* File tree */}
        <ScrollArea className="w-72 border-r shrink-0">
          <div className="p-2">
            {tree.length === 0 ? (
              <div className="text-center py-8 text-sm text-muted-foreground">
                No files yet. Upload data to get started.
              </div>
            ) : (
              tree.map((node) => (
                <TreeNode
                  key={node.path}
                  node={node}
                  depth={0}
                  search={search}
                  selectedPath={selectedFile?.path ?? null}
                  onSelect={setSelectedFile}
                />
              ))
            )}
          </div>
        </ScrollArea>

        {/* Preview */}
        <div className="flex-1 min-w-0 flex items-center justify-center">
          {selectedFile ? (
            <FilePreview file={selectedFile} projectName={activeProject!} />
          ) : (
            <div className="text-center text-muted-foreground">
              <File className="h-12 w-12 mx-auto mb-3 opacity-30" />
              <p className="text-sm">Select a file to preview</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function TreeNode({
  node, depth, search, selectedPath, onSelect,
}: {
  node: FileNode; depth: number; search: string; selectedPath: string | null; onSelect: (f: FileNode) => void
}) {
  const [expanded, setExpanded] = useState(depth < 2)

  const matchesSearch = !search || node.name.toLowerCase().includes(search.toLowerCase())
  const hasMatchingChildren = node.children?.some(
    (c) => c.name.toLowerCase().includes(search.toLowerCase()) || c.children?.length
  )

  if (search && !matchesSearch && !hasMatchingChildren) return null

  const isDir = node.type === 'dir'

  return (
    <div>
      <button
        className={cn(
          "w-full flex items-center gap-1.5 px-2 py-1 rounded-md text-sm hover:bg-accent transition-colors text-left",
          selectedPath === node.path && "bg-accent text-accent-foreground"
        )}
        style={{ paddingLeft: depth * 16 + 8 }}
        onClick={() => {
          if (isDir) setExpanded(!expanded)
          else onSelect(node)
        }}
      >
        {isDir ? (
          expanded ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
        ) : (
          <File className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
        )}
        {isDir && <Folder className="h-3.5 w-3.5 text-primary/70 shrink-0" />}
        <span className="truncate">{node.name}</span>
        {!isDir && node.size > 0 && (
          <span className="ml-auto text-[10px] text-muted-foreground tabular-nums shrink-0">{formatSize(node.size)}</span>
        )}
      </button>
      {isDir && expanded && node.children?.map((child) => (
        <TreeNode
          key={child.path}
          node={child}
          depth={depth + 1}
          search={search}
          selectedPath={selectedPath}
          onSelect={onSelect}
        />
      ))}
    </div>
  )
}

function FilePreview({ file, projectName }: { file: FileNode; projectName: string }) {
  const isImage = /\.(png|jpg|jpeg|svg|gif|webp|pdf)$/i.test(file.name)

  return (
    <div className="p-6 max-w-lg text-center">
      {isImage ? (
        <img
          src={api.plotUrl(`d:/Projects/CASI/projects/${projectName}/${file.path}`)}
          alt={file.name}
          className="max-w-full max-h-[60vh] object-contain rounded-lg shadow-md mx-auto"
        />
      ) : (
        <div>
          <File className="h-16 w-16 mx-auto mb-4 text-muted-foreground/30" />
          <p className="font-medium text-sm">{file.name}</p>
          <p className="text-xs text-muted-foreground mt-1">{formatSize(file.size)}</p>
          <p className="text-xs text-muted-foreground">{file.path}</p>
        </div>
      )}
    </div>
  )
}

function buildTree(flat: Array<{ name: string; path: string; type: 'file' | 'dir'; size: number }>): FileNode[] {
  const root: FileNode[] = []
  const map = new Map<string, FileNode>()

  // Sort so directories come before files
  const sorted = [...flat].sort((a, b) => {
    if (a.type !== b.type) return a.type === 'dir' ? -1 : 1
    return a.path.localeCompare(b.path)
  })

  for (const item of sorted) {
    const node: FileNode = { name: item.name, path: item.path, type: item.type, size: item.size }
    if (item.type === 'dir') node.children = []
    map.set(item.path, node)

    const parentPath = item.path.includes('/') ? item.path.slice(0, item.path.lastIndexOf('/')) : ''
    const parent = parentPath ? map.get(parentPath) : null

    if (parent?.children) {
      parent.children.push(node)
    } else if (!parentPath) {
      root.push(node)
    }
  }

  return root
}

function formatSize(b: number) {
  if (b < 1024) return `${b} B`
  if (b < 1048576) return `${(b / 1024).toFixed(0)} KB`
  if (b < 1073741824) return `${(b / 1048576).toFixed(1)} MB`
  return `${(b / 1073741824).toFixed(1)} GB`
}
