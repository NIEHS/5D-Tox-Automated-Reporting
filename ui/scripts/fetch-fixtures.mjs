// Regenerate the state and vocabulary mock fixtures FROM A RUNNING BACKEND
// (src/api/mocks/fixtures/real/). The fixtures are the backend's own answers,
// never hand-written: run the backend on a scratch copy of the sessions (never
// the real store), then:
//
//   node scripts/fetch-fixtures.mjs http://127.0.0.1:9512 ID [ID …]
//
// Each id is saved as state.<id>.json with its HTTP status (a malformed id is
// saved as the 400 envelope the backend answers). The list of ids the mocks
// serve, and why each one, is in src/api/mocks/fixtures/state.ts.
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const [base, ...ids] = process.argv.slice(2)
if (!base || ids.length === 0) {
  console.error('usage: node scripts/fetch-fixtures.mjs BACKEND_URL ID [ID …]')
  process.exit(2)
}
const out = resolve(dirname(fileURLToPath(import.meta.url)), '../src/api/mocks/fixtures/real')
mkdirSync(out, { recursive: true })

async function save(name, path) {
  const res = await fetch(new URL(path, base))
  const body = await res.json()
  writeFileSync(resolve(out, name), JSON.stringify({ status: res.status, body }, null, 2) + '\n')
  console.log(`${res.status} ${name}`)
}

for (const id of ids) await save(`state.${id}.json`, `/api/v2/studies/${encodeURIComponent(id)}/state`)
await save('vocabularies.json', '/api/v2/vocabularies')
