import express from 'express'
import cors from 'cors'
import { createServer } from 'http'
import { WebSocketServer, WebSocket } from 'ws'
import { spawn } from 'child_process'
import { createBroadcaster } from './lib/broadcast.js'
import { getCasiRoot, getProjectsDir } from './lib/paths.js'
import { PlotWatcher, ReportWatcher } from './services/watchers.js'
import { isDaemonHealthy } from './services/daemon-client.js'
import { registerAgentRoutes } from './routes/agent.js'
import { registerProjectRoutes } from './routes/projects.js'

const PORT = 3001
const CASI_ROOT = getCasiRoot()

const app = express()
app.use(cors())
app.use(express.json())

// Serve plot images from CASI projects directory
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
    const { daemonGet } = await import('./services/daemon-client.js')
    const ops = await daemonGet('/api/ops')
    res.json(ops)
  } catch {
    res.json([])
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
  const daemon = spawn('uv', ['run', 'casi-daemon'], {
    cwd: CASI_ROOT,
    shell: true,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, CASI_ROOT, VIRTUAL_ENV: undefined as unknown as string },
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
    console.log(`CASI server running at http://localhost:${PORT}`)
    console.log(`WebSocket at ws://localhost:${PORT}/ws`)
    console.log(`CASI_ROOT: ${CASI_ROOT}`)
  })
}

main()
