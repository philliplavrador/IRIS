/**
 * Express routes for the IRIS memory tool surface.
 *
 * Phase 2 (REVAMP Task 2.4): thin proxy over the Python daemon's real
 * `/api/memory/events` and `/api/memory/sessions/*` endpoints. The legacy
 * L3 surface (`/memory/recall`, `/memory/propose_*`, `/memory/commit_*`,
 * etc.) was stubbed 503 in Phase 0 and is **not** proxied here anymore —
 * those endpoints come back online in Phases 3-10 as their server
 * modules land and the frontend re-adopts them.
 */
import type { Express, Request, Response } from 'express'
import { daemonGet, daemonPost } from '../services/daemon-client.js'

function forwardError(res: Response, e: unknown): void {
  const msg = e instanceof Error ? e.message : String(e)
  // Best-effort: daemon-client throws with the status code baked into the
  // message. We don't parse that here — just report 502 with the message
  // so the frontend shows the daemon's explanation verbatim.
  res.status(502).json({ error: msg })
}

export function registerMemoryRoutes(app: Express): void {
  // -- events ----------------------------------------------------------
  app.get('/api/memory/events', async (req: Request, res: Response) => {
    try {
      const qs = new URLSearchParams(req.query as Record<string, string>).toString()
      const path = `/api/memory/events${qs ? `?${qs}` : ''}`
      res.json(await daemonGet(path))
    } catch (e) {
      forwardError(res, e)
    }
  })

  app.get('/api/memory/events/:eventId', async (req: Request, res: Response) => {
    try {
      const eventId = String(req.params.eventId)
      res.json(await daemonGet(`/api/memory/events/${encodeURIComponent(eventId)}`))
    } catch (e) {
      forwardError(res, e)
    }
  })

  app.post('/api/memory/events/verify_chain', async (req: Request, res: Response) => {
    try {
      res.json(await daemonPost('/api/memory/events/verify_chain', req.body ?? {}))
    } catch (e) {
      forwardError(res, e)
    }
  })

  // -- sessions --------------------------------------------------------
  app.post('/api/memory/sessions/start', async (req: Request, res: Response) => {
    try {
      res.json(await daemonPost('/api/memory/sessions/start', req.body ?? {}))
    } catch (e) {
      forwardError(res, e)
    }
  })

  app.post('/api/memory/sessions/:sessionId/end', async (req: Request, res: Response) => {
    try {
      const sessionId = String(req.params.sessionId)
      res.json(
        await daemonPost(
          `/api/memory/sessions/${encodeURIComponent(sessionId)}/end`,
          req.body ?? {},
        ),
      )
    } catch (e) {
      forwardError(res, e)
    }
  })

  app.get('/api/memory/sessions/:sessionId', async (req: Request, res: Response) => {
    try {
      const sessionId = String(req.params.sessionId)
      res.json(await daemonGet(`/api/memory/sessions/${encodeURIComponent(sessionId)}`))
    } catch (e) {
      forwardError(res, e)
    }
  })
}
