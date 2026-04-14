/**
 * HTTP client for the Python FastAPI daemon.
 * Replaces cli-bridge.ts subprocess spawning.
 */

const DAEMON_URL = process.env.IRIS_DAEMON_URL || 'http://localhost:4002'

export async function daemonGet<T = unknown>(path: string): Promise<T> {
  const res = await fetch(`${DAEMON_URL}${path}`)
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`Daemon GET ${path}: ${res.status} ${text}`)
  }
  return res.json() as Promise<T>
}

export async function daemonPost<T = unknown>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${DAEMON_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`Daemon POST ${path}: ${res.status} ${text}`)
  }
  return res.json() as Promise<T>
}

export async function daemonPatch<T = unknown>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${DAEMON_URL}${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`Daemon PATCH ${path}: ${res.status} ${text}`)
  }
  return res.json() as Promise<T>
}

export async function daemonDelete<T = unknown>(path: string): Promise<T> {
  const res = await fetch(`${DAEMON_URL}${path}`, { method: 'DELETE' })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`Daemon DELETE ${path}: ${res.status} ${text}`)
  }
  return res.json() as Promise<T>
}

export async function isDaemonHealthy(): Promise<boolean> {
  try {
    const res = await fetch(`${DAEMON_URL}/health`, { signal: AbortSignal.timeout(2000) })
    return res.ok
  } catch {
    return false
  }
}
