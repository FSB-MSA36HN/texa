import { spawnSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const python = path.join(root, 'backend/.venv/bin/python')
const isolatedEnv = {
  ...process.env,
  TEXA_E2E_TEST_DSN: '1',
  TEXA_DB_DSN: 'postgresql://postgres@127.0.0.1:15433/texa_benchmark',
  TEXA_READER_DSN: 'postgresql://texa_reader:texa_reader@127.0.0.1:15433/texa_benchmark',
  TEXA_SOURCE_PROFILE: 'evaluation',
}

export function runFixtureControl(action: 'prepare' | 'restore') {
  const result = spawnSync(python, ['backend/tests/e2e_fixture.py', action], {
    cwd: root, env: isolatedEnv, stdio: 'inherit',
  })
  if (result.error) throw result.error
  if (result.status !== 0) throw new Error(`Isolated E2E fixture ${action} failed with exit ${result.status}`)
}
