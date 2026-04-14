import express from 'express'
import cors from 'cors'
import { createServer } from 'http'
import { WebSocketServer, WebSocket } from 'ws'
import { spawn } from 'child_process'
import { createBroadcaster } from './lib/broadcast.js'
import { getIrisRoot, getProjectsDir } from './lib/paths.js'
import { PlotWatcher, ReportWatcher } from './services/watchers.js'
import { isDaemonHealthy, daemonGet, forwardDaemonError } from './services/daemon-client.js'
import { registerAgentRoutes } from './routes/agent.js'
import { registerProjectRoutes } from './routes/projects.js'
import { registerMemoryRoutes } from './routes/memory.js'

const PORT = 4001
const IRIS_ROOT = getIrisRoot()

const app = express()
app.use(cors())
app.use(express.json())

// Serve plot images from IRIS projects directory
app.use('/plots', express.static(`${getProjectsDir()}`, {
  setHeaders: (res) => {
    res.setHeader('Cache-Control', 'no-cache')
  }
}))

const server = createServer(app)

// WebSocket with debounced broadcasting
const wss = new WebSocketServer({ server, path: '/ws' })
const clients = new Set<WebSocket>()

wss.on('connection', (ws) => {
  clients.add(ws)
  ws.on('close', () => clients.delete(ws))
})

const broadcast = createBroadcaster(clients)

// Watchers
const plotWatcher = new PlotWatcher(broadcast)
const reportWatcher = new ReportWatcher(broadcast)

// Register routes
registerAgentRoutes(app, broadcast)
registerProjectRoutes(app, { plotWatcher, reportWatcher })
registerMemoryRoutes(app)

// Config, ops, sessions — pass through to daemon or serve directly
app.get('/api/config', async (_req, res) => {
  try {
    const { daemonGet } = await import('./services/daemon-client.js')
    const config = await daemonGet('/api/config')
    res.json(config)
  } catch {
    res.json({})
  }
})

app.get('/api/ops', async (_req, res) => {
  try {
    const ops = await daemonGet('/api/ops')
    res.json(ops)
  } catch {
    res.json([])
  }
})

// GET /api/ops/:name — single-op signature + default params (MED #5).
// Proxies to the daemon so 404s for unknown ops round-trip cleanly.
app.get('/api/ops/:name', async (req, res) => {
  try {
    const sig = await daemonGet(`/api/ops/${encodeURIComponent(req.params.name)}`)
    res.json(sig)
  } catch (err) {
    forwardDaemonError(res, err)
  }
})

app.get('/api/agent-rules', async (_req, res) => {
  try {
    const { readFile } = await import('fs/promises')
    const { resolve } = await import('path')
    const raw = await readFile(resolve(getIrisRoot(), 'configs', 'agent_rules.yaml'), 'utf-8')
    // Extract the rules value (block scalar or single-line)
    const blockMatch = raw.match(/^rules:\s*\|\s*\n((?:[ \t]+.+\n?)*)/m)
    if (blockMatch) {
      res.json({ rules: blockMatch[1].replace(/^  /gm, '').trim() })
    } else {
      const lineMatch = raw.match(/^rules:\s+(.+)$/m)
      res.json({ rules: lineMatch ? lineMatch[1].trim() : '' })
    }
  } catch {
    res.json({ rules: '' })
  }
})

app.post('/api/agent-rules', async (req, res) => {
  try {
    const { writeFile } = await import('fs/promises')
    const { resolve } = await import('path')
    const { rules } = req.body as { rules: string }
    const indented = rules.split('\n').map(line => `  ${line}`).join('\n')
    const content = `# Global behavior rules applied to every IRIS project.\n# Edit this file directly or use the IRIS webapp settings.\n\nrules: |\n${indented}\n`
    await writeFile(resolve(getIrisRoot(), 'configs', 'agent_rules.yaml'), content, 'utf-8')
    res.json({ ok: true })
  } catch (err: any) {
    res.status(500).json({ error: err.message })
  }
})

app.get('/api/sessions', async (_req, res) => {
  try {
    const { daemonGet } = await import('./services/daemon-client.js')
    const sessions = await daemonGet('/api/sessions')
    res.json(sessions)
  } catch {
    res.json([])
  }
})

// Auto-start Python daemon
async function startDaemon(): Promise<void> {
  if (await isDaemonHealthy()) {
    console.log('[daemon] Already running')
    return
  }

  console.log('[daemon] Starting Python daemon...')
  const daemon = spawn('uv', ['run', 'iris-daemon'], {
    cwd: IRIS_ROOT,
    shell: true,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, IRIS_ROOT, VIRTUAL_ENV: undefined as unknown as string },
  })

  daemon.stdout.on('data', (d: Buffer) => {
    const line = d.toString().trim()
    if (line) console.log(`[daemon] ${line}`)
  })
  daemon.stderr.on('data', (d: Buffer) => {
    const line = d.toString().trim()
    if (line) console.error(`[daemon] ${line}`)
  })
  daemon.on('exit', (code) => {
    console.error(`[daemon] Exited with code ${code}`)
  })

  // Poll until healthy (30s timeout)
  for (let i = 0; i < 60; i++) {
    await new Promise((r) => setTimeout(r, 500))
    if (await isDaemonHealthy()) {
      console.log('[daemon] Healthy and ready')
      return
    }
  }
  console.error('[daemon] Failed to start within 30s — continuing without daemon')
}

// Start
async function main() {
  // Start daemon (non-blocking if it fails)
  startDaemon().catch((err) => console.error('[daemon] Start error:', err))

  server.listen(PORT, () => {
    console.log(`IRIS server running at http://localhost:${PORT}`)
    console.log(`WebSocket at ws://localhost:${PORT}/ws`)
    console.log(`IRIS_ROOT: ${IRIS_ROOT}`)
  })
}

main()
