import type { Express } from 'express'
import { sendMessage, abortAgent } from '../agent-bridge.js'

type BroadcastFn = (type: string, data: unknown) => void

export function registerAgentRoutes(app: Express, broadcast: BroadcastFn): void {
  app.post('/api/agent/send', (req, res) => {
    const { prompt } = req.body
    sendMessage(prompt, broadcast).catch((err) => console.error('Agent error:', err))
    res.json({ ok: true })
  })

  app.post('/api/agent/abort', (_req, res) => {
    abortAgent()
    res.json({ ok: true })
  })
}
