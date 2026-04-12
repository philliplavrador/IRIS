import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/renderer/__tests__/setup.ts'],
    include: ['src/renderer/__tests__/**/*.test.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      include: ['src/renderer/**/*.{ts,tsx}'],
      exclude: ['src/renderer/components/ui/**'],
    },
  },
})
