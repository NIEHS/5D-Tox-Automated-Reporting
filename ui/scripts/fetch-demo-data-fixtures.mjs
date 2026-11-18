// Regenerate the mock fixtures of the demo path's "Combined data" and
// "Process" pages FROM A RUNNING BACKEND (src/api/mocks/fixtures/demoData/).
// The fixtures are the backend's own answers, never hand-written. Run the
// backend on a scratch store that holds the NIEHS-12 pair (the finished
// report DTXSID6020430 and its live copy; never the real store), then, with
// the live rat study at each stage in turn:
//
//   node scripts/fetch-demo-data-fixtures.mjs http://127.0.0.1:9510 validated   (after a reset)
//   node scripts/fetch-demo-data-fixtures.mjs http://127.0.0.1:9510 combined    (after Combine)
//   node scripts/fetch-demo-data-fixtures.mjs http://127.0.0.1:9510 processed   (after Process)
//   node scripts/fetch-demo-data-fixtures.mjs http://127.0.0.1:9510 finished    (the finished side, any time)
//
// Each answer is saved with its HTTP status. Which fixture the mocks serve
// when is in src/api/mocks/demoData.ts.
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const [base, stage] = process.argv.slice(2)
const STAGES = ['validated', 'combined', 'processed', 'finished']
if (!base || !STAGES.includes(stage)) {
  console.error(`usage: node scripts/fetch-demo-data-fixtures.mjs BACKEND_URL ${STAGES.join('|')}`)
  process.exit(2)
}
const out = resolve(dirname(fileURLToPath(import.meta.url)), '../src/api/mocks/fixtures/demoData')
mkdirSync(out, { recursive: true })

const LIVE = 'DTXSID6020430_live_rat'
const FINISHED = 'DTXSID6020430_rat'
const enc = encodeURIComponent

async function get(path) {
  const res = await fetch(new URL(path, base))
  return { status: res.status, body: await res.json() }
}

/** An act that must be refused before it starts (it then changes nothing). */
async function refused(path) {
  const res = await fetch(new URL(path, base), { method: 'POST' })
  if (res.ok) {
    await res.body?.cancel()
    throw new Error(`POST ${path} was not refused (${res.status}): an act was started`)
  }
  return { status: res.status, body: await res.json() }
}

async function save(name, path, method = 'GET') {
  const answer = method === 'GET' ? await get(path) : await refused(path)
  writeFileSync(resolve(out, name), JSON.stringify(answer, null, 2) + '\n')
  console.log(`${answer.status} ${name}`)
  return answer
}

async function study(id, tag) {
  await save(`state.${tag}.json`, `/api/v2/studies/${enc(id)}/state`)
  await save(`dataset.${tag}.json`, `/api/v2/studies/${enc(id)}/dataset`)
  const tables = await save(`tables.${tag}.json`, `/api/v2/studies/${enc(id)}/tables`)
  await save(`study-parameters.${tag}.json`, `/api/workflow/${enc(id)}/study-parameters`)
  await save(`knowledge-base.${tag}.json`, `/api/session/${enc(id)}/knowledge-base`)
  return tables.body.tables ?? []
}

if (stage === 'finished') {
  const tables = await study(FINISHED, 'finished')
  for (const t of tables) {
    await save(`sources.finished.${t.key}.json`, `/api/v2/studies/${enc(FINISHED)}/tables/${enc(t.key)}/sources`)
  }
  await save('sources.finished.unknown.json', `/api/v2/studies/${enc(FINISHED)}/tables/bm2_hematology/sources`)
  // The two reports of the pair: a report has no data of its own.
  await save('state.finished-report.json', '/api/v2/studies/DTXSID6020430/state')
  await save('state.live-report.json', '/api/v2/studies/DTXSID6020430_live/state')
  await save('dataset.live-report.json', '/api/v2/studies/DTXSID6020430_live/dataset')
  // The finished side is left as it is: both acts are refused before they start.
  await save('refusal.finished.integrate.json', `/api/v2/studies/${enc(FINISHED)}/integrate`, 'POST')
  await save('refusal.finished.process.json', `/api/v2/studies/${enc(FINISHED)}/process`, 'POST')
} else {
  const tables = await study(LIVE, `live.${stage}`)
  // Before the files are combined, the analysis is refused before it starts.
  if (stage === 'validated') await save('refusal.live.validated.process.json', `/api/v2/studies/${enc(LIVE)}/process`, 'POST')
  for (const t of tables) {
    await save(`sources.live.${t.key}.json`, `/api/v2/studies/${enc(LIVE)}/tables/${enc(t.key)}/sources`)
  }
}
