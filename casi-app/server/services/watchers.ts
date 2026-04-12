/**
 * Consolidated file watchers for plots, reports, and file changes.
 */
import { watch, type FSWatcher } from 'fs'
import { readFile } from 'fs/promises'
import { join, extname } from 'path'

type BroadcastFn = (type: string, data: unknown) => void

export class PlotWatcher {
  private watcher: FSWatcher | null = null
  private seenFiles = new Set<string>()
  private broadcast: BroadcastFn

  constructor(broadcast: BroadcastFn) {
    this.broadcast = broadcast
  }

  watchProject(projectPath: string): void {
    this.stop()
    this.seenFiles.clear()
    const outputDir = join(projectPath, 'output')

    try {
      this.watcher = watch(outputDir, { recursive: true }, async (_event, filename: string | null) => {
        if (!filename) return
        const fullPath = join(outputDir, filename)
        const ext = extname(filename).toLowerCase()
        if (!['.png', '.pdf', '.svg'].includes(ext)) return
        if (this.seenFiles.has(fullPath)) return
        this.seenFiles.add(fullPath)

        let sidecar = null
        try {
          const raw = await readFile(fullPath + '.json', 'utf-8')
          sidecar = JSON.parse(raw)
        } catch {}

        this.broadcast('plot:new', { path: fullPath, filename, sidecar })
      })
      this.watcher.on('error', () => {})
    } catch {}
  }

  stop(): void {
    try { this.watcher?.close() } catch {}
    this.watcher = null
  }
}

export class ReportWatcher {
  private watcher: FSWatcher | null = null
  private broadcast: BroadcastFn
  private debounceTimer: ReturnType<typeof setTimeout> | null = null

  constructor(broadcast: BroadcastFn) {
    this.broadcast = broadcast
  }

  watchProject(projectName: string, projectsDir: string): void {
    this.stop()
    const reportPath = `${projectsDir}/${projectName}/report.md`

    try {
      this.watcher = watch(reportPath, async () => {
        if (this.debounceTimer) clearTimeout(this.debounceTimer)
        this.debounceTimer = setTimeout(async () => {
          try {
            const content = await readFile(reportPath, 'utf-8')
            this.broadcast('report:update', { content })
          } catch {}
        }, 300)
      })
      this.watcher.on('error', () => {})
    } catch {}
  }

  stop(): void {
    try { this.watcher?.close() } catch {}
    this.watcher = null
    if (this.debounceTimer) clearTimeout(this.debounceTimer)
  }
}
