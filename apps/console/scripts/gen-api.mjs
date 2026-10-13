// Regenerates src/api/schema.d.ts from the FastAPI OpenAPI document (the single source of truth).
import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, '..', '..', '..')
const py = [resolve(root, '.venv/Scripts/python.exe'), resolve(root, '.venv/bin/python'), 'python']
  .find((p) => p === 'python' || existsSync(p))
const spec = resolve(here, '..', 'openapi.json')
execFileSync(py, [resolve(root, 'scripts/export_openapi.py'), spec], { cwd: root, stdio: 'inherit' })
execFileSync('npx', ['openapi-typescript', spec, '-o', resolve(here, '..', 'src/api/schema.d.ts')],
  { cwd: resolve(here, '..'), stdio: 'inherit', shell: true })
