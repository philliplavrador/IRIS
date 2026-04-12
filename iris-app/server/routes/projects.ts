import type { Express } from 'express'
import { readFile, writeFile, readdir, stat, mkdir, rm, rename } from 'fs/promises'
import { createReadStream } from 'fs'
import { join } from 'path'
import multer from 'multer'
import archiver from 'archiver'
import { getProjectsDir } from '../lib/paths.js'
import type { PlotWatcher, ReportWatcher } from '../services/watchers.js'

interface Watchers {
  plotWatcher: PlotWatcher
  reportWatcher: ReportWatcher
}

export function registerProjectRoutes(app: Express, watchers: Watchers): void {
  const projectsDir = getProjectsDir()

  app.get('/api/projects', async (_req, res) => {
    try {
      const entries = await readdir(projectsDir, { withFileTypes: true })
      const projects = []
      for (const entry of entries) {
        if (!entry.isDirectory() || entry.name === 'TEMPLATE' || entry.name.startsWith('.')) continue
        const projectDir = `${projectsDir}/${entry.name}`
        let n_outputs = 0
        try {
          const outputFiles = await readdir(`${projectDir}/output`)
          n_outputs = outputFiles.filter(f => /\.(png|pdf|svg)$/i.test(f)).length
        } catch {}
        let n_references = 0
        for (const refDir of ['claude_references', 'user_references']) {
          try {
            const refs = await readdir(`${projectDir}/${refDir}`)
            n_references += refs.filter(f => !f.startsWith('.')).length
          } catch {}
        }
        let description: string | null = null
        try {
          const configRaw = await readFile(`${projectDir}/claude_config.yaml`, 'utf-8')
          const descMatch = configRaw.match(/description:\s*(.+)/)
          if (descMatch) description = descMatch[1].trim()
        } catch {}
        projects.push({ name: entry.name, path: projectDir, created_at: null, description, n_references, n_outputs })
      }
      res.json(projects)
    } catch {
      res.json([])
    }
  })

  app.post('/api/projects/open', async (req, res) => {
    try {
      const name = req.body.name
      const projectPath = `${projectsDir}/${name}`
      watchers.plotWatcher.watchProject(projectPath)
      watchers.reportWatcher.watchProject(name, projectsDir)
      res.json({ ok: true })
    } catch (err: any) {
      res.status(500).json({ error: err.message })
    }
  })

  app.post('/api/projects/create', async (req, res) => {
    try {
      const { name, description } = req.body
      const projectDir = `${projectsDir}/${name}`
      // Copy from TEMPLATE
      const templateDir = `${projectsDir}/TEMPLATE`
      const { cpSync } = await import('fs')
      cpSync(templateDir, projectDir, { recursive: true })
      if (description) {
        const configPath = `${projectDir}/claude_config.yaml`
        try {
          let config = await readFile(configPath, 'utf-8')
          config = config.replace(/description:.*/, `description: ${description}`)
          const { writeFileSync } = await import('fs')
          writeFileSync(configPath, config)
        } catch {}
      }
      res.json({ ok: true })
    } catch (err: any) {
      res.status(500).json({ error: err.message })
    }
  })

  app.post('/api/projects/rename', async (req, res) => {
    try {
      const { oldName, newName } = req.body
      await rename(`${projectsDir}/${oldName}`, `${projectsDir}/${newName}`)
      res.json({ ok: true })
    } catch (err: any) {
      res.status(500).json({ error: err.message })
    }
  })

  app.post('/api/projects/delete', async (req, res) => {
    try {
      await rm(`${projectsDir}/${req.body.name}`, { recursive: true, force: true })
      res.json({ ok: true })
    } catch (err: any) {
      res.status(500).json({ error: err.message })
    }
  })

  app.get('/api/projects/info', async (req, res) => {
    try {
      const name = req.query.name as string
      if (!name) { res.json({ info: null }); return }
      const projectDir = `${projectsDir}/${name}`
      const configRaw = await readFile(`${projectDir}/claude_config.yaml`, 'utf-8')
      res.json({ info: configRaw })
    } catch {
      res.json({ info: null })
    }
  })

  // File upload
  const upload = multer({ storage: multer.diskStorage({
    destination: async (req, _file, cb) => {
      const name = (req as any).query.name || (req as any).body?.name
      const dest = `${projectsDir}/${name}/input_data`
      await mkdir(dest, { recursive: true })
      cb(null, dest)
    },
    filename: (_req, file, cb) => cb(null, file.originalname),
  })})

  app.post('/api/projects/upload', upload.array('files'), (req, res) => {
    const count = (req.files as Express.Multer.File[])?.length ?? 0
    res.json({ ok: true, count })
  })

  // File listing
  app.get('/api/projects/files', async (req, res) => {
    try {
      const name = req.query.name as string
      if (!name) { res.json([]); return }
      const projectDir = `${projectsDir}/${name}`

      // Internal project scaffolding — hidden from user-facing file manager
      const HIDDEN = new Set([
        'claude_references', 'user_references', 'CLAUDE.md',
        'claude_history.md', 'claude_config.yaml', 'memory.yaml', 'report.md',
      ])

      async function walk(dir: string, prefix: string): Promise<{ name: string; path: string; type: 'file' | 'dir'; size: number }[]> {
        const entries = await readdir(dir, { withFileTypes: true })
        const results: { name: string; path: string; type: 'file' | 'dir'; size: number }[] = []
        for (const entry of entries) {
          if (entry.name.startsWith('.') || HIDDEN.has(entry.name)) continue
          const fullPath = `${dir}/${entry.name}`
          const relPath = prefix ? `${prefix}/${entry.name}` : entry.name
          if (entry.isDirectory()) {
            results.push({ name: entry.name, path: relPath, type: 'dir', size: 0 })
            results.push(...await walk(fullPath, relPath))
          } else {
            const s = await stat(fullPath)
            results.push({ name: entry.name, path: relPath, type: 'file', size: s.size })
          }
        }
        return results
      }

      const files = await walk(projectDir, '')
      res.json(files)
    } catch {
      res.json([])
    }
  })

  // Report
  app.get('/api/report', async (req, res) => {
    try {
      const name = req.query.name as string
      if (!name) { res.json({ content: '' }); return }
      const content = await readFile(`${projectsDir}/${name}/report.md`, 'utf-8')
      res.json({ content })
    } catch {
      res.json({ content: '' })
    }
  })

  // Sidecar
  app.get('/api/sidecar', async (req, res) => {
    try {
      const plotPath = req.query.path as string
      const raw = await readFile(plotPath + '.json', 'utf-8')
      res.json(JSON.parse(raw))
    } catch {
      res.json(null)
    }
  })

  // Memory
  app.get('/api/projects/memory', async (req, res) => {
    try {
      const name = req.query.name as string
      if (!name) { res.json({ content: '' }); return }
      const content = await readFile(`${projectsDir}/${name}/memory.yaml`, 'utf-8')
      res.json({ content })
    } catch {
      res.json({ content: '' })
    }
  })

  app.post('/api/projects/memory', async (req, res) => {
    try {
      const { name, content } = req.body
      await writeFile(`${projectsDir}/${name}/memory.yaml`, content, 'utf-8')
      res.json({ ok: true })
    } catch (err: any) {
      res.status(500).json({ error: err.message })
    }
  })

  // Custom ops
  app.get('/api/projects/custom-ops', async (req, res) => {
    try {
      const name = req.query.name as string
      if (!name) { res.json([]); return }
      const opsDir = `${projectsDir}/${name}/custom_ops`
      const entries = await readdir(opsDir).catch(() => [] as string[])
      const ops = entries.filter(f => f.endsWith('.py') && !f.startsWith('.')).map(f => f.replace('.py', ''))
      res.json(ops)
    } catch {
      res.json([])
    }
  })

  app.get('/api/projects/custom-ops/read', async (req, res) => {
    try {
      const name = req.query.name as string
      const op = req.query.op as string
      const content = await readFile(`${projectsDir}/${name}/custom_ops/${op}.py`, 'utf-8')
      res.json({ content })
    } catch {
      res.json({ content: null })
    }
  })

  // Clear conversations
  app.post('/api/projects/clear-conversations', async (req, res) => {
    try {
      const { name } = req.body
      const convDir = `${projectsDir}/${name}/conversations`
      await rm(convDir, { recursive: true, force: true })
      await mkdir(convDir, { recursive: true })
      res.json({ ok: true })
    } catch (err: any) {
      res.status(500).json({ error: err.message })
    }
  })

  // Delete file from project
  app.post('/api/projects/delete-file', async (req, res) => {
    try {
      const { name, filePath } = req.body
      const fullPath = `${projectsDir}/${name}/${filePath}`
      // Prevent path traversal
      if (filePath.includes('..')) { res.status(400).json({ error: 'Invalid path' }); return }
      await rm(fullPath, { recursive: true, force: true })
      res.json({ ok: true })
    } catch (err: any) {
      res.status(500).json({ error: err.message })
    }
  })

  // Update project config
  app.post('/api/projects/update-config', async (req, res) => {
    try {
      const { name, description, agentNotes } = req.body
      const configPath = `${projectsDir}/${name}/claude_config.yaml`
      let config = await readFile(configPath, 'utf-8')
      if (description !== undefined) {
        config = config.replace(/description:.*/, `description: ${description || 'null'}`)
      }
      if (agentNotes !== undefined) {
        // Replace agent_notes whether single-line or block scalar (it's the last key)
        config = config.replace(/agent_notes:[\s\S]*$/, agentNotes
          ? `agent_notes: |\n${agentNotes.split('\n').map((l: string) => `  ${l}`).join('\n')}\n`
          : 'agent_notes: null\n')
      }
      await writeFile(configPath, config, 'utf-8')
      res.json({ ok: true })
    } catch (err: any) {
      res.status(500).json({ error: err.message })
    }
  })

  // Export project as zip
  app.get('/api/projects/export', async (req, res) => {
    try {
      const name = req.query.name as string
      if (!name) { res.status(400).json({ error: 'Missing name' }); return }
      const projectDir = `${projectsDir}/${name}`
      res.setHeader('Content-Type', 'application/zip')
      res.setHeader('Content-Disposition', `attachment; filename="${name}.zip"`)
      const archive = archiver('zip', { zlib: { level: 6 } })
      archive.pipe(res)
      archive.directory(projectDir, name)
      await archive.finalize()
    } catch (err: any) {
      res.status(500).json({ error: err.message })
    }
  })
}
