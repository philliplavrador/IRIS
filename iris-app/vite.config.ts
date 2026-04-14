import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  root: 'src/renderer',
  publicDir: false,
  server: {
    port: 4173,
    proxy: {
      '/api': 'http://localhost:4001',
      '/ws': {
        target: 'ws://localhost:4001',
        ws: true
      },
      '/plots': 'http://localhost:4001'
    }
  },
  build: {
    outDir: '../../dist',
    emptyOutDir: true
  }
})
