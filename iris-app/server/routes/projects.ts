import type { Express } from 'express'
import { readFile, writeFile, readdir, stat, mkdir, rm, rename } from 'fs/promises'
import { createReadStream } from 'fs'
import { join } from 'path'
import multer from 'multer'
import archiver from 'archiver'
import { getProjectsDir } from '../lib/paths.js'
import { daemonPost } from '../services/daemon-client.js'
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

  // Behavior dials (autonomy / pushback / memory) — round-trips claude_config.yaml
  app.get('/api/projects/behavior', async (req, res) => {
    try {
      const name = req.query.name as string
      const configRaw = await readFile(`${projectsDir}/${name}/claude_config.yaml`, 'utf-8')
      res.json({ yaml: configRaw, ...parseBehaviorDials(configRaw) })
    } catch (err: any) {
      res.status(500).json({ error: err.message })
    }
  })

  app.post('/api/projects/behavior', async (req, res) => {
    try {
      const { name, autonomy, pushback, memory } = req.body as {
        name: string
        autonomy?: string
        pushback?: Record<string, string>
        memory?: Record<string, number | boolean>
      }
      const path = `${projectsDir}/${name}/claude_config.yaml`
      let yaml = await readFile(path, 'utf-8')
      if (autonomy) yaml = replaceScalar(yaml, 'autonomy', autonomy)
      if (pushback) {
        for (const [k, v] of Object.entries(pushback)) {
          yaml = replaceNested(yaml, 'pushback', k, String(v))
        }
      }
      if (memory) {
        for (const [k, v] of Object.entries(memory)) {
          yaml = replaceNested(yaml, 'memory', k, String(v))
        }
      }
      await writeFile(path, yaml, 'utf-8')
      res.json({ ok: true, ...parseBehaviorDials(yaml) })
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

  app.post('/api/projects/upload', upload.array('files'), async (req, res) => {
    const files = (req.files as Express.Multer.File[]) ?? []
    const project = ((req as any).query.name || (req as any).body?.name) as string | undefined
    const profiles: Array<{ name: string; path: string; profile: any; error?: string }> = []
    if (project) {
      for (const f of files) {
        try {
          const body = await daemonPost('/api/memory/profile_data', {
            project,
            file_path: f.path,
          }) as { profile: any }
          profiles.push({ name: f.originalname, path: f.path, profile: body.profile })
        } catch (e: any) {
          profiles.push({ name: f.originalname, path: f.path, profile: null, error: e.message })
        }
      }
    }
    res.json({ ok: true, count: files.length, profiles })
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
        'claude_config.yaml', 'report.md',
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

// -- claude_config.yaml dial helpers ---------------------------------------
// Surgical in-place edits to preserve comments and formatting; full YAML
// round-trip would rewrite the file.

function parseBehaviorDials(yaml: string): {
  autonomy: string
  pushback: Record<string, string>
  memory: Record<string, string>
} {
  const autonomy = (yaml.match(/^autonomy:\s*(\S+)/m)?.[1] ?? 'medium').trim()
  return {
    autonomy,
    pushback: parseBlock(yaml, 'pushback'),
    memory: parseBlock(yaml, 'memory'),
  }
}

function parseBlock(yaml: string, key: string): Record<string, string> {
  const re = new RegExp(`^${key}:\\s*$([\\s\\S]*?)(?=^\\S|\\Z)`, 'm')
  const m = yaml.match(re)
  const out: Record<string, string> = {}
  if (!m) return out
  for (const line of m[1].split(/\r?\n/)) {
    const mm = line.match(/^\s+([A-Za-z_]+):\s*([^#\n]+?)\s*(?:#.*)?$/)
    if (mm) out[mm[1]] = mm[2].trim()
  }
  return out
}

function replaceScalar(yaml: string, key: string, value: string): string {
  const re = new RegExp(`^(${key}:\\s*)(\\S+)(.*)$`, 'm')
  if (!re.test(yaml)) return yaml + `\n${key}: ${value}\n`
  return yaml.replace(re, `$1${value}$3`)
}

function replaceNested(yaml: string, parent: string, key: string, value: string): string {
  const re = new RegExp(`^(\\s+${key}:\\s*)([^#\\n]+?)(\\s*(?:#.*)?)$`, 'm')
  // Only replace if inside the parent block — simple heuristic: must appear after "^parent:"
  const pIdx = yaml.search(new RegExp(`^${parent}:`, 'm'))
  if (pIdx < 0) return yaml
  const before = yaml.slice(0, pIdx)
  const after = yaml.slice(pIdx)
  const nextTop = after.slice(1).search(/^\S/m)
  const blockEnd = nextTop < 0 ? after.length : 1 + nextTop
  const block = after.slice(0, blockEnd)
  if (!re.test(block)) return yaml
  const newBlock = block.replace(re, `$1${value}$3`)
  return before + newBlock + after.slice(blockEnd)
}
