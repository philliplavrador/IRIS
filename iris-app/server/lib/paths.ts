/**
 * Path resolution for the IRIS project root.
 * Uses IRIS_ROOT env var if set, otherwise resolves relative to this file.
 */
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

export function getIrisRoot(): string {
  // __dirname is server/lib/, go up 3 levels: lib -> server -> iris-app -> IRIS
  return process.env.IRIS_ROOT || resolve(__dirname, '..', '..', '..')
}

export function getProjectsDir(): string {
  return resolve(getIrisRoot(), 'projects')
}
