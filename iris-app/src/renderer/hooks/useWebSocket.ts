import { useEffect, useRef, useCallback } from 'react'

export function useWebSocket(
  url: string,
  onMessage: (data: { type: string; data: unknown }) => void
) {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const onMessageRef = useRef(onMessage)
  onMessageRef.current = onMessage

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN ||
        wsRef.current?.readyState === WebSocket.CONNECTING) return

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.type === 'batch' && Array.isArray(data.data)) {
        for (const item of data.data) {
          onMessageRef.current(item)
        }
      } else {
        onMessageRef.current(data)
      }
    }

    ws.onclose = () => {
      // Only reconnect if this is still the active connection
      // (avoids duplicate connections from React StrictMode double-mount)
      if (wsRef.current === ws) {
        wsRef.current = null
        reconnectTimer.current = setTimeout(connect, 2000)
      }
    }

    ws.onerror = () => {
      ws.close()
    }
  }, [url])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(reconnectTimer.current)
      const ws = wsRef.current
      wsRef.current = null
      ws?.close()
    }
  }, [connect])
}
