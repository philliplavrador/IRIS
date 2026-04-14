import type { Express } from 'express'
import { readFile, writeFile, readdir, stat, mkdir, rm, rename } from 'fs/promises'
import { createReadStream } from 'fs'
import { join } from 'path'
import multer from 'multer'
import archiver from 'archiver'
import { getProjectsDir } from '../lib/paths.js'
import { daemonGet, daemonPost, daemonDelete } from '../services/daemon-client.js'
import type { PlotWatcher, ReportWatcher } from '../services/watchers.js'

interface DaemonProjectInfo {
  name: string
  path: string
  created_at: string | null
  description: string | null
  n_references: number
  n_outputs: number
  agent_notes?: string
}

interface DaemonActiveResponse {
  active: DaemonProjectInfo | null
}

interface Watchers {
  plotWatcher: PlotWatcher
  reportWatcher: ReportWatcher
}

export function registerProjectRoutes(app: Express, watchers: Watchers): void {
  const projectsDir = getProjectsDir()

  // -- Canonical project lifecycle (REVAMP Task 1.10) ----------------------
  // Proxies the six daemon endpoints from `src/iris/daemon/routes/projects.py`.
  // The Express layer adds nothing but watcher wiring on open + a couple of
  // legacy aliases below for the current frontend.

  app.get('/api/projects', async (_req, res) => {
    try {
      const projects = await daemonGet<DaemonProjectInfo[]>('/api/projects')
      res.json(projects)
    } catch (err: any) {
      // Daemon down: fall back to empty list so the projects page still renders.
      console.error('[projects] daemon list failed:', err.message)
      res.json([])
    }
  })

  // GET /api/projects/active -> { active: ProjectInfo | null }
  app.get('/api/projects/active', async (_req, res) => {
    try {
      const data = await daemonGet<DaemonActiveResponse>('/api/projects/active')
      res.json(data)
    } catch (err: any) {
      res.status(502).json({ error: err.message })
    }
  })

  // POST /api/projects/active body { name } -> { active: ProjectInfo }
  app.post('/api/projects/active', async (req, res) => {
    try {
      const { name } = req.body as { name: string }
      const data = await daemonPost<DaemonActiveResponse>('/api/projects/active', { name })
      // Wire watchers for the newly active project.
      watchers.plotWatcher.watchProject(`${projectsDir}/${name}`)
      watchers.reportWatcher.watchProject(name, projectsDir)
      res.json(data)
    } catch (err: any) {
      res.status(502).json({ error: err.message })
    }
  })

  // POST /api/projects body { name, description? } -> ProjectInfo
  app.post('/api/projects', async (req, res) => {
    try {
      const { name, description } = req.body as { name: string; description?: string }
      const info = await daemonPost<DaemonProjectInfo>('/api/projects', { name, description })
      res.json(info)
    } catch (err: any) {
      res.status(502).json({ error: err.message })
    }
  })

  // GET /api/projects/by-name/:name -> ProjectInfo (open + activate)
  // Note: distinct path prefix (`by-name`) avoids colliding with the static
  // sub-routes (/active, /upload, /files, /info, /behavior, …) declared below.
  app.get('/api/projects/by-name/:name', async (req, res) => {
    try {
      const info = await daemonGet<DaemonProjectInfo>(`/api/projects/${encodeURIComponent(req.params.name)}`)
      watchers.plotWatcher.watchProject(`${projectsDir}/${req.params.name}`)
      watchers.reportWatcher.watchProject(req.params.name, projectsDir)
      res.json(info)
    } catch (err: any) {
      res.status(502).json({ error: err.message })
    }
  })

  // DELETE /api/projects/:name -> { ok: true, name }
  app.delete('/api/projects/:name', async (req, res) => {
    try {
      const data = await daemonDelete<{ ok: boolean; name: string }>(`/api/projects/${encodeURIComponent(req.params.name)}`)
      res.json(data)
    } catch (err: any) {
      res.status(502).json({ error: err.message })
    }
  })

  // -- Legacy aliases (kept until the frontend migrates fully) -------------
  // The existing ProjectsPage still posts to these; route them through the
  // canonical daemon endpoints so behavior stays consistent.

  app.post('/api/projects/open', async (req, res) => {
    try {
      const { name } = req.body as { name: string }
      await daemonPost<DaemonActiveResponse>('/api/projects/active', { name })
      watchers.plotWatcher.watchProject(`${projectsDir}/${name}`)
      watchers.reportWatcher.watchProject(name, projectsDir)
      res.json({ ok: true })
    } catch (err: any) {
      res.status(502).json({ error: err.message })
    }
  })

  app.post('/api/projects/create', async (req, res) => {
    try {
      const { name, description } = req.body as { name: string; description?: string }
      await daemonPost<DaemonProjectInfo>('/api/projects', { name, description })
      res.json({ ok: true })
    } catch (err: any) {
      res.status(502).json({ error: err.message })
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
      const { name } = req.body as { name: string }
      await daemonDelete<{ ok: boolean }>(`/api/projects/${encodeURIComponent(name)}`)
      res.json({ ok: true })
    } catch (err: any) {
      // Last-resort fallback if daemon refuses; preserve old behavior.
      try {
        await rm(`${projectsDir}/${req.body.name}`, { recursive: true, force: true })
        res.json({ ok: true })
      } catch (err2: any) {
        res.status(500).json({ error: err2.message })
      }
    }
  })

  // Behavior dials (autonomy / pushback / memory) — round-trips config.toml
  app.get('/api/projects/behavior', async (req, res) => {
    try {
      const name = req.query.name as string
      const toml = await readFile(`${projectsDir}/${name}/config.toml`, 'utf-8')
      res.json(parseBehaviorDials(toml))
    } catch (err: any) {
      res.status(500).json({ error: err.message })
    }
  })

  app.post('/api/projects/behavior', async (req, res) => {
    try {
      const { name, autonomy, pushback, memory } = req.body as {
        name: string
        autonomy?: string
        pushback?: string
        memory?: { slice_budget_tokens?: number }
      }
      const path = `${projectsDir}/${name}/config.toml`
      let toml = await readFile(path, 'utf-8')
      if (autonomy !== undefined) toml = setTomlString(toml, 'behavior', 'autonomy', autonomy)
      if (pushback !== undefined) toml = setTomlString(toml, 'behavior', 'pushback', pushback)
      if (memory?.slice_budget_tokens !== undefined) {
        toml = setTomlNumber(toml, 'memory', 'slice_budget_tokens', memory.slice_budget_tokens)
      }
      await writeFile(path, toml, 'utf-8')
      res.json({ ok: true, ...parseBehaviorDials(toml) })
    } catch (err: any) {
      res.status(500).json({ error: err.message })
    }
  })

  app.get('/api/projects/info', async (req, res) => {
    try {
      const name = req.query.name as string
      if (!name) { res.json({ info: null }); return }
      const toml = await readFile(`${projectsDir}/${name}/config.toml`, 'utf-8')
      res.json({
        info: {
          description: getTomlString(toml, 'project', 'description'),
          agent_notes: getTomlString(toml, 'project', 'agent_notes'),
        },
      })
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
        'config.toml', 'iris.sqlite', 'iris.sqlite-wal', 'iris.sqlite-shm',
        'memory', 'artifacts', 'ops', 'indexes', 'datasets',
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
      const configPath = `${projectsDir}/${name}/config.toml`
      let toml = await readFile(configPath, 'utf-8')
      if (description !== undefined) toml = setTomlString(toml, 'project', 'description', description)
      if (agentNotes !== undefined) toml = setTomlString(toml, 'project', 'agent_notes', agentNotes)
      await writeFile(configPath, toml, 'utf-8')
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

// -- config.toml dial helpers ---------------------------------------------
// Surgical in-place edits: locate `[section]`, update `key = ...` within,
// insert before the next section if missing. Comments and formatting survive.

function parseBehaviorDials(toml: string): {
  autonomy: string
  pushback: string
  memory: { slice_budget_tokens: number }
} {
  return {
    autonomy: getTomlString(toml, 'behavior', 'autonomy'),
    pushback: getTomlString(toml, 'behavior', 'pushback'),
    memory: {
      slice_budget_tokens: Number(getTomlString(toml, 'memory', 'slice_budget_tokens') || '0'),
    },
  }
}

function sectionBounds(toml: string, section: string): { start: number; end: number } | null {
  const re = new RegExp(`^\\[${section}\\]\\s*$`, 'm')
  const m = re.exec(toml)
  if (!m) return null
  const start = m.index + m[0].length
  const next = toml.slice(start).search(/^\[/m)
  return { start, end: next < 0 ? toml.length : start + next }
}

function getTomlString(toml: string, section: string, key: string): string {
  const b = sectionBounds(toml, section)
  if (!b) return ''
  const body = toml.slice(b.start, b.end)
  // Triple-quoted multiline
  const mm = body.match(new RegExp(`^\\s*${key}\\s*=\\s*"""([\\s\\S]*?)"""`, 'm'))
  if (mm) return mm[1].replace(/^\n/, '')
  // Single-line string
  const ms = body.match(new RegExp(`^\\s*${key}\\s*=\\s*"((?:[^"\\\\]|\\\\.)*)"`, 'm'))
  if (ms) return ms[1].replace(/\\"/g, '"').replace(/\\\\/g, '\\')
  // Bare value (number, bool)
  const mn = body.match(new RegExp(`^\\s*${key}\\s*=\\s*([^\\s#]+)`, 'm'))
  if (mn) return mn[1]
  return ''
}

function writeTomlLine(toml: string, section: string, key: string, rendered: string): string {
  const b = sectionBounds(toml, section)
  if (!b) {
    const sep = toml.endsWith('\n') ? '' : '\n'
    return `${toml}${sep}\n[${section}]\n${key} = ${rendered}\n`
  }
  const body = toml.slice(b.start, b.end)
  // Match existing key (single-line, multiline, or bare) across full entry.
  const multi = new RegExp(`^(\\s*)${key}\\s*=\\s*"""[\\s\\S]*?"""[^\\n]*$`, 'm')
  const single = new RegExp(`^(\\s*)${key}\\s*=[^\\n]*$`, 'm')
  const replacement = (indent: string) => `${indent}${key} = ${rendered}`
  let newBody: string
  if (multi.test(body)) {
    newBody = body.replace(multi, (_m, indent) => replacement(indent))
  } else if (single.test(body)) {
    newBody = body.replace(single, (_m, indent) => replacement(indent))
  } else {
    const trimmed = body.replace(/\s+$/, '')
    newBody = `${trimmed}\n${key} = ${rendered}\n${body.slice(trimmed.length)}`
  }
  return toml.slice(0, b.start) + newBody + toml.slice(b.end)
}

function setTomlString(toml: string, section: string, key: string, value: string): string {
  const rendered = value.includes('\n')
    ? `"""\n${value}\n"""`
    : `"${value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`
  return writeTomlLine(toml, section, key, rendered)
}

function setTomlNumber(toml: string, section: string, key: string, value: number): string {
  return writeTomlLine(toml, section, key, String(value))
}
