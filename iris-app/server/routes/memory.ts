/**
 * Express routes for the IRIS memory tool surface.
 *
 * Thin proxy layer over the Python daemon's `/api/memory/*` endpoints. The
 * frontend (curation ritual UI, memory inspector, profile confirmation) and
 * the Claude agent both hit these paths. Keeping them on the Express side
 * means a consistent `/api/*` surface for the React app and allows
 * per-request shaping if ever needed.
 */
import type { Express, Request, Response } from 'express'
import { daemonGet, daemonPost } from '../services/daemon-client.js'

type Proxy = (path: string, body?: unknown) => Promise<unknown>

const proxyPost: Proxy = (path, body) => daemonPost(path, body ?? {})

export function registerMemoryRoutes(app: Express): void {
  // -- retrieval ---------------------------------------------------------
  app.post('/api/memory/recall', async (req: Request, res: Response) => {
    try {
      const data = await proxyPost('/api/memory/recall', req.body)
      res.json(data)
    } catch (e: any) {
      res.status(502).json({ error: e.message })
    }
  })

  app.post('/api/memory/get', async (req, res) => {
    try {
      res.json(await proxyPost('/api/memory/get', req.body))
    } catch (e: any) { res.status(502).json({ error: e.message }) }
  })

  app.post('/api/memory/read_conversation', async (req, res) => {
    try {
      res.json(await proxyPost('/api/memory/read_conversation', req.body))
    } catch (e: any) { res.status(502).json({ error: e.message }) }
  })

  app.post('/api/memory/append_turn', async (req, res) => {
    try {
      res.json(await proxyPost('/api/memory/append_turn', req.body))
    } catch (e: any) { res.status(502).json({ error: e.message }) }
  })

  app.post('/api/memory/read_ledger', async (req, res) => {
    try {
      res.json(await proxyPost('/api/memory/read_ledger', req.body))
    } catch (e: any) { res.status(502).json({ error: e.message }) }
  })

  // -- proposals ---------------------------------------------------------
  const proposals = [
    'propose_decision',
    'propose_goal',
    'propose_fact',
    'propose_declined',
    'propose_profile_annotation',
    'propose_digest_edit',
  ]
  for (const name of proposals) {
    app.post(`/api/memory/${name}`, async (req, res) => {
      try {
        res.json(await proxyPost(`/api/memory/${name}`, req.body))
      } catch (e: any) { res.status(502).json({ error: e.message }) }
    })
  }

  // -- commit + pending + digest ----------------------------------------
  app.post('/api/memory/commit_session_writes', async (req, res) => {
    try {
      res.json(await proxyPost('/api/memory/commit_session_writes', req.body))
    } catch (e: any) { res.status(502).json({ error: e.message }) }
  })

  app.get('/api/memory/draft_digest', async (req, res) => {
    try {
      const qs = new URLSearchParams(req.query as Record<string, string>).toString()
      res.json(await daemonGet(`/api/memory/draft_digest?${qs}`))
    } catch (e: any) { res.status(502).json({ error: e.message }) }
  })

  app.get('/api/memory/pending', async (req, res) => {
    try {
      const qs = new URLSearchParams(req.query as Record<string, string>).toString()
      res.json(await daemonGet(`/api/memory/pending${qs ? '?' + qs : ''}`))
    } catch (e: any) { res.status(502).json({ error: e.message }) }
  })

  // -- pinned slice + maintenance ---------------------------------------
  app.post('/api/memory/build_slice', async (req, res) => {
    try {
      res.json(await proxyPost('/api/memory/build_slice', req.body))
    } catch (e: any) { res.status(502).json({ error: e.message }) }
  })

  app.post('/api/memory/rollover', async (req, res) => {
    try {
      res.json(await proxyPost('/api/memory/rollover', req.body))
    } catch (e: any) { res.status(502).json({ error: e.message }) }
  })

  app.post('/api/memory/regenerate_views', async (req, res) => {
    try {
      const project = req.query.project as string | undefined
      const path = project
        ? `/api/memory/regenerate_views?project=${encodeURIComponent(project)}`
        : '/api/memory/regenerate_views'
      res.json(await proxyPost(path))
    } catch (e: any) { res.status(502).json({ error: e.message }) }
  })

  app.post('/api/memory/profile_data', async (req, res) => {
    try {
      res.json(await proxyPost('/api/memory/profile_data', req.body))
    } catch (e: any) { res.status(502).json({ error: e.message }) }
  })

  // -- inspector listing + mutation -------------------------------------
  app.get('/api/memory/list_knowledge', async (req, res) => {
    try {
      const qs = new URLSearchParams(req.query as Record<string, string>).toString()
      res.json(await daemonGet(`/api/memory/list_knowledge?${qs}`))
    } catch (e: any) { res.status(502).json({ error: e.message }) }
  })

  for (const name of ['set_status', 'delete_row', 'supersede_fact', 'discard_pending', 'replace_draft']) {
    app.post(`/api/memory/${name}`, async (req, res) => {
      try {
        res.json(await proxyPost(`/api/memory/${name}`, req.body))
      } catch (e: any) { res.status(502).json({ error: e.message }) }
    })
  }

  app.get('/api/memory/list_digests', async (req, res) => {
    try {
      const qs = new URLSearchParams(req.query as Record<string, string>).toString()
      res.json(await daemonGet(`/api/memory/list_digests${qs ? '?' + qs : ''}`))
    } catch (e: any) { res.status(502).json({ error: e.message }) }
  })
}
