import { HttpResponse, delay, http } from 'msw'
import { API_V2 } from '../client'
import type {
  ChemicalGroup,
  CreateStudyRequest,
  CreationCheck,
  DeletePreview,
  ErrorEnvelope,
  ExistingStudyState,
  RecordIdentityRequest,
  StudiesList,
  StudyDetail,
  StudyRow,
  StudyState,
} from '../types'
import {
  M1_CHECK_BPA,
  M1_CHECK_PFHXSAM,
  M1_CHEMICALS,
  M1_CHEM_NOT_FOUND,
  M1_CHEM_UNREACHABLE,
  M1_CREATED_BPA,
  M1_DELETE_PREVIEW_PFHXSAM,
  M1_DETAILS,
  M1_REFUSAL_CHANGED,
  M1_REFUSAL_MEMBER,
  M1_REFUSAL_STUDY_EXISTS,
  M1_REFUSAL_SUFFIX,
  M1_STUDIES,
  REFUSAL_INVALID_STUDY_ID,
  STATES_BY_ID,
  STATE_APPROVED,
  STATE_COMPANION,
  STATE_EMPTY,
  STRUCTURE_PNG_BASE64,
} from './fixtures'
import { casrnCheckDigitOk } from '../../kit/checkId'
import { running } from './runs'

/**
 * M1 Studies, mocked (docs/ui-redesign/modules/m1/contract.md §2). A small
 * in-memory store over the fixtures, so that creating, deleting and filling
 * an identity show in the list, the study page and the state, as they would
 * on the backend. The rules here (which kind may be deleted, the token) are
 * the BACKEND's, played by the mock; no screen repeats them.
 *
 * Mock-only ids, for the browser demo:
 * - DTXSID0000000001: PubChem knows no such chemical (identity_not_found);
 * - DTXSID0000000002: the lookup service cannot be reached (identity_lookup_unreachable);
 * - DTXSID1111111111: the creation check answers, but the format changed by the time of Create (format_changed);
 * - DTXSID3333333333: PubChem finds the chemical but gives no CAS number (the person is asked for it).
 */

const SESSION_ID = /^DTXSID[A-Za-z0-9_-]{1,64}$/
const STUDY_ID = /^DTXSID\d+$/

export function m1Envelope(body: ErrorEnvelope): Response {
  return HttpResponse.json(body, { status: body.error.status })
}

function refusal(code: string, status: number, say: string, message: string, details: Record<string, unknown> = {}, fix: string | null = null) {
  return m1Envelope({ error: { code, status, message, say, fix: fix as never, details } })
}

const clone = <T,>(x: T): T => structuredClone(x)

interface Db {
  /** chemical groups in the list's order (ids only) */
  chemicals: { dtxsid: string; name: string | null; casrn: string | null; ids: string[] }[]
  unassigned: string[]
  details: Map<string, StudyDetail>
  /** ids whose state the mock answers itself (created, changed, or constructed) */
  states: Map<string, ExistingStudyState>
  deleted: Set<string>
  /** bumped by every change to a study: the delete preview's token follows it */
  version: Map<string, number>
}

/**
 * The state of the list's sessions that have no state fixture of their own:
 * CONSTRUCTED from the nearest real answer, so a page that opens them agrees
 * with the list.
 */
function constructedStates(): Map<string, ExistingStudyState> {
  const m = new Map<string, ExistingStudyState>()
  const nb: ExistingStudyState = {
    ...clone(STATE_APPROVED),
    id: 'DTXSID50469320_nb',
    kind: 'other',
    identity: { ...STATE_APPROVED.identity!, dtxsid: 'DTXSID50469320_nb' },
  }
  if (nb.pins.definition) {
    nb.pins.definition = {
      ...nb.pins.definition, pinned: true, name: 'eras/niehs-2026', source: 'era', mode: 'track',
      pinned_by: 'default', pinned_at: '2026-10-13T13:45:31+00:00', hash: 'cdbd602e773aee83',
    }
  }
  m.set(nb.id, nb)
  m.set('DTXSID1020431_published', {
    ...clone(STATE_COMPANION),
    id: 'DTXSID1020431_published',
    relations: { ...clone(STATE_COMPANION).relations, twin: 'DTXSID1020431' },
    identity: { name: '1,4-Dichlorobenzene', casrn: '106-46-7', dtxsid: 'DTXSID1020431_published', short_name: null },
  })
  for (const id of ['DTXSID_TEST', 'DTXSID8031865_scratch']) {
    m.set(id, { ...clone(STATE_EMPTY), id, kind: 'other', identity: { name: null, casrn: null, dtxsid: id, short_name: null } })
  }
  return m
}

function freshDb(list: StudiesList = M1_STUDIES): Db {
  return {
    chemicals: list.chemicals.map((c) => ({ dtxsid: c.dtxsid, name: c.name, casrn: c.casrn, ids: c.sessions.map((r) => r.id) })),
    unassigned: list.unassigned.map((r) => r.id),
    details: new Map(Object.values(clone(M1_DETAILS)).map((d) => [d.id, d])),
    states: constructedStates(),
    deleted: new Set(),
    version: new Map(),
  }
}

let db = freshDb()

/** Forget every change to the mock studies; called between tests. */
export function resetM1Db(): void {
  db = freshDb()
}

/** Start the mock store empty (acceptance criterion 10). */
export function emptyM1Db(): void {
  db = { ...freshDb(), chemicals: [], unassigned: [], details: new Map() }
}

/** A change made elsewhere (another tab brought in a file): the preview's token no longer matches. */
export function touchMockStudy(id: string): void {
  db.version.set(id, (db.version.get(id) ?? 0) + 1)
}

/** Remove a study from the store, as another tab's delete would. */
export function removeMockStudy(id: string): void {
  dropStudy(id)
}

function exists(id: string): boolean {
  return db.details.has(id) && !db.deleted.has(id)
}

function rowOf(d: StudyDetail): StudyRow {
  const row: StudyRow & { detail?: unknown } = { ...d }
  delete row.detail
  return withRunGuard(row)
}

/** The backend derives `actions.delete` from the run lock too. */
function withRunGuard<T extends StudyRow>(row: T): T {
  const since = running.get(row.id)
  if (!since || !row.actions.delete.allowed) return row
  const time = new Date(since).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  return {
    ...row,
    actions: { ...row.actions, delete: { allowed: false, code: 'run_in_flight', say: `Process is running on this study (since ${time}). Wait for it to finish.` } },
  }
}

function list(): StudiesList {
  const chemicals: ChemicalGroup[] = []
  for (const c of db.chemicals) {
    const sessions = c.ids.filter(exists).map((id) => rowOf(db.details.get(id)!))
    if (sessions.length === 0) continue
    const primary = sessions.find((r) => r.kind === 'study' || r.kind === 'report')?.id ?? null
    chemicals.push({ dtxsid: c.dtxsid, name: c.name, casrn: c.casrn, primary, can_create: primary === null, sessions })
  }
  return {
    chemicals,
    unassigned: db.unassigned.filter(exists).map((id) => rowOf(db.details.get(id)!)),
    generated_at: new Date().toISOString(),
  }
}

function detailOf(id: string): StudyDetail {
  const d = db.details.get(id)!
  const row = withRunGuard(d)
  return row.detail.members ? { ...row, detail: { ...row.detail, members: row.detail.members.filter((m) => exists(m.id)) } } : row
}

function idRefusal(id: string): Response | null {
  if (!SESSION_ID.test(id)) {
    return m1Envelope({ error: { ...REFUSAL_INVALID_STUDY_ID.error, message: `invalid session id '${id}'`, say: `'${id}' is not a study id. A study's id is the chemical's DTXSID: 'DTXSID' followed by digits, for example DTXSID50469320.` } })
  }
  return null
}

function strictIdRefusal(id: string): Response | null {
  const bad = idRefusal(id)
  if (bad) return bad
  if (!STUDY_ID.test(id)) {
    return m1Envelope({ error: { ...M1_REFUSAL_SUFFIX.error, message: `study id '${id}' must match ^DTXSID\\d+$` } })
  }
  return null
}

function notFound(id: string) {
  return refusal('study_not_found', 404, `There is no study ${id}. It may have been deleted.`, `no session ${id}`, {}, 'M1')
}

function checkFor(dtxsid: string): CreationCheck {
  const base = dtxsid === 'DTXSID50469320' ? M1_CHECK_PFHXSAM : M1_CHECK_BPA
  const existing = exists(dtxsid) ? { id: dtxsid, kind: db.details.get(dtxsid)!.kind } : null
  const related = [...db.details.values()]
    .filter((d) => exists(d.id) && d.id !== dtxsid && d.chemical_dtxsid === dtxsid)
    .map((d) => ({ id: d.id, kind: d.kind, say: d.kind === 'companion' ? "The published book's content" : d.kind === 'member' ? 'Part of a report over several studies' : 'Other session, made by a tool' }))
  const format = clone(base.format)
  // the mock's format hash: the contract's, or a stand-in where it gives none
  if (!format.hash || format.hash.startsWith('[')) format.hash = `mock-${format.definition}`
  return { ...clone(base), dtxsid, exists: existing !== null, existing, related_sessions: related, format }
}

function previewFor(id: string): DeletePreview {
  const d = db.details.get(id)!
  const base = clone(M1_DELETE_PREVIEW_PFHXSAM)
  const token = `sha256:mock-${id}-v${db.version.get(id) ?? 0}`
  if (id === 'DTXSID50469320') return { ...base, type_to_confirm: id, preview_token: token }
  const state = STATES_BY_ID[id] ?? db.states.get(id)
  const approved = (state?.sections ?? []).filter((s) => s.approved).map((s) => s.key)
  const others = (d.relations.others ?? []).map((o) => ({ what: 'others', say: `The other session of this chemical, ${o}` }))
  const companion = d.relations.companion ? [{ what: 'companion', say: `The published book's content, ${d.relations.companion}` }] : []
  // CONSTRUCTED from the contract's PFHxSAm preview, in its shape
  return {
    confirm: {
      ...base.confirm,
      deletes: base.confirm.deletes.map((x) =>
        x.what === 'sections'
          ? { what: 'sections', say: `${state?.sections.filter((s) => s.has_file).length ?? 0} report sections; ${approved.length === 0 ? 'none is approved' : `${approved.length} approved`}` }
          : x.what === 'pins'
            ? { what: 'pins', say: 'The method profile and document definition pins, if any' }
            : x.what === 'files'
              ? { what: 'files', say: "The study's data files, and the originals they were converted from" }
              : x,
      ),
      keeps: [
        { what: 'output', say: `The deliverables already written to output/${id}/` },
        ...(d.format?.source === 'study' ? [{ what: 'study_definition', say: `The study definition under templates/studies/${id}/ (not part of the study)` }] : []),
        ...companion,
        ...others,
      ],
      approvals_lost: approved,
      cost: d.published ? { say: `This study reproduces ${d.published.report}. It can be rebuilt only from the command line (tooling.build_published_reports), not from this interface.` } : null,
    },
    type_to_confirm: id,
    preview_token: token,
  }
}

function deleteGuard(id: string): Response | null {
  const d = db.details.get(id)!
  if (d.kind === 'companion') {
    return refusal('read_only_session', 409, "This is the published book's own content, made by a tool. It can't be changed or deleted here.", `${id} is published content`)
  }
  if (d.kind === 'member') {
    const parent = d.relations.parent ?? ''
    const key = db.details.get(parent)?.relations.members.find((m) => m.id === id)?.key ?? 'member'
    return m1Envelope({
      error: { ...M1_REFUSAL_MEMBER.error, message: `${id} is listed in ${parent}/studies.json`, say: `This is the ${key} study of the report ${parent}. Deleting it would break that report.`, details: { parent, key } },
    })
  }
  const since = running.get(id)
  if (since) {
    const time = new Date(since).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
    return refusal('run_in_flight', 409, `Process is running on this study (since ${time}). Wait for it to finish.`, `process lock held for ${id} since ${since}`, { started_at: since }, 'P1')
  }
  return null
}

function dropStudy(id: string) {
  db.deleted.add(id)
  db.states.delete(id)
  for (const d of db.details.values()) {
    d.relations.others = d.relations.others.filter((o) => o !== id)
    if (d.relations.companion === id) d.relations.companion = null
    if (d.relations.twin === id) d.relations.twin = null
  }
}

function stateFor(id: string): StudyState | undefined {
  if (db.deleted.has(id)) return { id, exists: false }
  const own = db.states.get(id)
  if (!own) return undefined
  const since = running.get(id)
  return since ? { ...own, run: { in_flight: true, started_at: since, last: own.run?.last ?? null } } : own
}

function setIdentity(id: string, identity: { name: string; casrn: string | null }) {
  const base = STATES_BY_ID[id] ?? db.states.get(id)
  if (base) db.states.set(id, { ...clone(base), identity: { ...(base.identity ?? { dtxsid: id, short_name: null }), name: identity.name, casrn: identity.casrn } })
}

/** The identity source recorded for a confirmed identity; `casrn_from: "person"` when the person typed the CAS number. */
function identitySourceOf(identity: CreateStudyRequest['identity'], now: string): StudyRow['identity']['source'] {
  return {
    kind: 'lookup',
    service: identity.source.service,
    confirmed_at: now,
    casrn_from: identity.source.casrn_from === 'person' ? 'person' : 'lookup',
  }
}

/**
 * Mock-only id for the browser demo: PubChem finds the chemical but gives no
 * CAS number (the person is asked for one).
 */
export const MOCK_NO_CASRN_ID = 'DTXSID3333333333'

export function createM1Handlers({ lookupDelayMs = 0 }: { lookupDelayMs?: number } = {}) {
  return [
    http.get(`${API_V2}/studies`, () => HttpResponse.json(list())),

    http.post(`${API_V2}/studies`, async ({ request }) => {
      const req = (await request.json()) as CreateStudyRequest
      const id = req.dtxsid
      const bad = strictIdRefusal(id)
      if (bad) return bad
      if (req.confirmed !== true) return refusal('identity_unconfirmed', 400, 'Confirm the chemical before creating the study.', 'confirmed is not true')
      if (!req.identity?.name || !req.identity.casrn) return refusal('identity_incomplete', 400, 'A name and a CASRN are needed.', 'identity incomplete')
      if (!/^\d{2,7}-\d{2}-\d$/.test(req.identity.casrn) || !casrnCheckDigitOk(req.identity.casrn)) {
        return refusal('invalid_casrn', 400, "This CASRN's check digit doesn't match; a digit is probably mistyped.", `CASRN ${req.identity.casrn} fails its check digit`, { casrn: req.identity.casrn })
      }
      if (exists(id)) {
        return m1Envelope({ error: { ...M1_REFUSAL_STUDY_EXISTS.error, message: `session ${id} already exists`, say: `A study of this chemical already exists (${id}). Open it instead.`, details: { existing_id: id } } })
      }
      const check = checkFor(id)
      if (id === 'DTXSID1111111111' || req.format_seen?.hash !== check.format.hash) {
        return refusal('format_changed', 409, 'The report format this id brings changed since you looked. Review it again.', `format hash ${req.format_seen?.hash} != ${check.format.hash}`)
      }
      const looked = M1_CHEMICALS[id]
      const casrnByPerson = req.identity.source?.casrn_from === 'person'
      if (casrnByPerson && looked?.identity.casrn) {
        return refusal('identity_changed', 409, 'The lookup now gives a CAS number for this chemical. Look it up again.', 'casrn_from person, but the lookup has a CASRN')
      }
      if (looked && (looked.identity.name !== req.identity.name || (!casrnByPerson && looked.identity.casrn !== req.identity.casrn))) {
        return refusal('identity_changed', 409, 'The lookup now gives a different chemical than the one you confirmed. Look it up again.', 'identity differs from the cached lookup')
      }
      const now = new Date().toISOString()
      const row: StudyRow = {
        ...clone(M1_CREATED_BPA),
        id,
        chemical_dtxsid: id,
        identity: { name: req.identity.name, casrn: req.identity.casrn, short_name: null, source: identitySourceOf(req.identity, now) },
        last_changed: now,
        format: { ...clone(check.format), brings: undefined } as StudyRow['format'],
        published: check.published,
        relations: { parent: null, members: [], companion: null, twin: null, others: check.related_sessions.map((r) => r.id) },
      }
      delete (row.format as { brings?: unknown }).brings
      delete (row.format as { hash?: unknown }).hash
      db.deleted.delete(id)
      db.details.set(id, { ...row, detail: { banner: null, format: { ...clone(check.format), pin: { mode: null, pinned_at: null, pinned_by: null }, chosen_by: 'id' } } })
      db.states.set(id, { ...clone(STATE_EMPTY), id, identity: { name: req.identity.name, casrn: req.identity.casrn, dtxsid: id, short_name: null } })
      const group = db.chemicals.find((c) => c.dtxsid === id)
      if (group) {
        group.ids = [id, ...group.ids.filter((x) => x !== id)]
        group.name = req.identity.name
        group.casrn = req.identity.casrn
      } else {
        db.chemicals.unshift({ dtxsid: id, name: req.identity.name, casrn: req.identity.casrn, ids: [id] })
      }
      return HttpResponse.json(row, { status: 201 })
    }),

    http.get(`${API_V2}/studies/:id/creation-check`, ({ params }) => {
      const id = String(params.id)
      return strictIdRefusal(id) ?? HttpResponse.json(checkFor(id))
    }),

    http.get(`${API_V2}/studies/:id/state`, ({ params }) => {
      const s = stateFor(String(params.id))
      // not ours: the shared state mock answers
      return s ? HttpResponse.json(s) : undefined
    }),

    http.get(`${API_V2}/studies/:id/delete-preview`, ({ params }) => {
      const id = String(params.id)
      const bad = idRefusal(id)
      if (bad) return bad
      if (!exists(id)) return notFound(id)
      return deleteGuard(id) ?? HttpResponse.json(previewFor(id))
    }),

    http.post(`${API_V2}/studies/:id/delete`, async ({ params, request }) => {
      const id = String(params.id)
      const bad = idRefusal(id)
      if (bad) return bad
      if (!exists(id)) return notFound(id)
      const guard = deleteGuard(id)
      if (guard) return guard
      const req = (await request.json()) as { confirm_id?: string; preview_token?: string }
      if (req.confirm_id !== id) return refusal('confirm_mismatch', 400, "The id you typed doesn't match this study's id. Nothing was deleted.", `confirm_id ${String(req.confirm_id)} != ${id}`)
      const token = previewFor(id).preview_token
      if (req.preview_token !== token) {
        return m1Envelope({ error: { ...M1_REFUSAL_CHANGED.error, message: `preview token ${String(req.preview_token)} does not match ${token}` } })
      }
      const kept = previewFor(id).confirm.keeps.filter((k) => k.what === 'output')
      dropStudy(id)
      return HttpResponse.json({ deleted: id, kept, say: `${id} was deleted.` })
    }),

    http.put(`${API_V2}/studies/:id/identity`, async ({ params, request }) => {
      const id = String(params.id)
      const bad = idRefusal(id)
      if (bad) return bad
      if (!exists(id)) return notFound(id)
      const d = db.details.get(id)!
      if (d.kind === 'companion' || d.kind === 'report') {
        return refusal('read_only_session', 409, "This is the published book's own content, made by a tool. It can't be changed or deleted here.", `${id} is ${d.kind}`)
      }
      if (d.identity.name) return refusal('identity_exists', 409, 'This study already has its chemical\'s identity. Changing it is not done here.', 'identity.json has a name')
      const req = (await request.json()) as RecordIdentityRequest
      if (req.confirmed !== true) return refusal('identity_unconfirmed', 400, 'Confirm the chemical before creating the study.', 'confirmed is not true')
      const now = new Date().toISOString()
      if (!req.identity?.name || !req.identity.casrn) return refusal('identity_incomplete', 400, 'A name and a CASRN are needed.', 'identity incomplete')
      d.identity = { ...d.identity, name: req.identity.name, casrn: req.identity.casrn, source: identitySourceOf(req.identity, now) }
      d.notes = d.notes.filter((n) => n.code !== 'identity_missing')
      const group = db.chemicals.find((c) => c.ids.includes(id))
      if (group && group.name === null) {
        group.name = req.identity.name
        group.casrn = req.identity.casrn
      }
      setIdentity(id, req.identity)
      touchMockStudy(id)
      return HttpResponse.json(rowOf(d))
    }),

    http.get(`${API_V2}/studies/:id`, ({ params }) => {
      const id = String(params.id)
      const bad = idRefusal(id)
      if (bad) return bad
      return exists(id) ? HttpResponse.json(detailOf(id)) : notFound(id)
    }),

    http.get(`${API_V2}/chemicals/:dtxsid`, async ({ params }) => {
      const id = String(params.dtxsid)
      const bad = strictIdRefusal(id)
      if (bad) return bad
      if (lookupDelayMs > 0) await delay(lookupDelayMs)
      if (id === 'DTXSID0000000002') return m1Envelope(M1_CHEM_UNREACHABLE)
      const found =
        M1_CHEMICALS[id] ??
        (id === MOCK_NO_CASRN_ID
          ? { ...clone(M1_CHEMICALS['DTXSID7020182']!), dtxsid: id, dtxsid_matched: true, structure_url: null, identity: { ...clone(M1_CHEMICALS['DTXSID7020182']!.identity), casrn: null } }
          : undefined)
      // PROPOSED (2026-10-16): a lookup without a CAS number says the person must give one
      if (found) return HttpResponse.json({ ...found, looked_up_at: new Date().toISOString(), ...(found.identity.casrn ? {} : { needs: ['casrn'] }) })
      return m1Envelope({
        error: { ...M1_CHEM_NOT_FOUND.error, message: `PubChem lookup failed for name '${id}'`, say: `PubChem has no chemical with the DTXSID ${id}. A single mistyped digit gives another chemical or none. Check the id on the CompTox dashboard.` },
      })
    }),

    http.get(`${API_V2}/chemicals/:dtxsid/structure.png`, ({ params }) => {
      const b64 = STRUCTURE_PNG_BASE64[String(params.dtxsid)]
      if (!b64) return refusal('structure_unavailable', 404, 'PubChem did not return a structure picture.', 'no PNG')
      const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))
      return new HttpResponse(bytes, { headers: { 'Content-Type': 'image/png' } })
    }),
  ]
}
