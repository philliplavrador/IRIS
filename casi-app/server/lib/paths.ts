/**
 * Path resolution for the CASI project root.
 * Uses CASI_ROOT env var if set, otherwise resolves relative to this file.
 */
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

export function getCasiRoot(): string {
  // __dirname is server/lib/, go up 3 levels: lib -> server -> casi-app -> CASI
  return process.env.CASI_ROOT || resolve(__dirname, '..', '..', '..')
}

export function getProjectsDir(): string {
  return resolve(getCasiRoot(), 'projects')
}
