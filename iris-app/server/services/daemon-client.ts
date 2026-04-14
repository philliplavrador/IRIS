/**
 * HTTP client for the Python FastAPI daemon.
 * Replaces cli-bridge.ts subprocess spawning.
 */

const DAEMON_URL = process.env.IRIS_DAEMON_URL || 'http://localhost:4002'

/**
 * Thrown when the daemon returns a non-2xx response. Carries the upstream
 * status code and parsed body so Express route handlers can forward them
 * verbatim (instead of collapsing every failure to 502).
 */
export class DaemonHTTPError extends Error {
  status: number
  body: unknown
  path: string
  method: string

  constructor(method: string, path: string, status: number, body: unknown) {
    const summary =
      body && typeof body === 'object' && 'detail' in (body as Record<string, unknown>)
        ? String((body as Record<string, unknown>).detail)
        : typeof body === 'string'
          ? body
          : JSON.stringify(body)
    super(`Daemon ${method} ${path}: ${status} ${summary}`)
    this.name = 'DaemonHTTPError'
    this.status = status
    this.body = body
    this.path = path
    this.method = method
  }
}

async function parseBody(res: Response): Promise<unknown> {
  const text = await res.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method }
  if (body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' }
    init.body = JSON.stringify(body)
  }
  const res = await fetch(`${DAEMON_URL}${path}`, init)
  if (!res.ok) {
    const parsed = await parseBody(res)
    throw new DaemonHTTPError(method, path, res.status, parsed)
  }
  return (await res.json()) as T
}

export async function daemonGet<T = unknown>(path: string): Promise<T> {
  return request<T>('GET', path)
}

export async function daemonPost<T = unknown>(path: string, body: unknown): Promise<T> {
  return request<T>('POST', path, body ?? {})
}

export async function daemonPatch<T = unknown>(path: string, body: unknown): Promise<T> {
  return request<T>('PATCH', path, body ?? {})
}

export async function daemonDelete<T = unknown>(path: string): Promise<T> {
  return request<T>('DELETE', path)
}

export async function isDaemonHealthy(): Promise<boolean> {
  try {
    const res = await fetch(`${DAEMON_URL}/health`, { signal: AbortSignal.timeout(2000) })
    return res.ok
  } catch {
    return false
  }
}

/**
 * Express helper: if `err` is a `DaemonHTTPError`, forward its status + body
 * to the client. Otherwise, 502 with the error message. Route handlers use
 * this in their `catch` blocks so daemon 404s/409s/503s round-trip cleanly.
 */
export function forwardDaemonError(res: import('express').Response, err: unknown): void {
  if (err instanceof DaemonHTTPError) {
    const body =
      err.body !== null && err.body !== undefined
        ? err.body
        : { error: err.message }
    res.status(err.status).json(body)
    return
  }
  const msg = err instanceof Error ? err.message : String(err)
  res.status(502).json({ error: msg })
}
