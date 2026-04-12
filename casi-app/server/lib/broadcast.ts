/**
 * Debounced WebSocket broadcast.
 * Batches rapid-fire messages within a 50ms window.
 */
import { WebSocket } from 'ws'

export function createBroadcaster(clients: Set<WebSocket>) {
  let pending: Array<{ type: string; data: unknown }> = []
  let timer: ReturnType<typeof setTimeout> | null = null

  return function broadcast(type: string, data: unknown) {
    pending.push({ type, data })

    if (!timer) {
      timer = setTimeout(() => {
        const batch = pending
        pending = []
        timer = null

        const msg = JSON.stringify(
          batch.length === 1 ? batch[0] : { type: 'batch', data: batch }
        )

        for (const ws of clients) {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(msg)
          }
        }
      }, 50)
    }
  }
}
