import { API_V2, getJson, sendJson } from './client'
import type {
  ChemicalLookup,
  CreateStudyRequest,
  CreationCheck,
  DeletePreview,
  DeleteResult,
  DryRun,
  RecordIdentityRequest,
  StudiesList,
  StudyDetail,
  StudyRow,
} from './types'

/**
 * M1 Studies: the endpoints of docs/ui-redesign/modules/m1/contract.md §2.
 * Owned by the orchestrator (MODULES.md §4.6); added at M1's request.
 */

const enc = encodeURIComponent

export const m1Paths = {
  studies: () => `${API_V2}/studies`,
  study: (id: string) => `${API_V2}/studies/${enc(id)}`,
  creationCheck: (dtxsid: string) => `${API_V2}/studies/${enc(dtxsid)}/creation-check`,
  chemical: (dtxsid: string) => `${API_V2}/chemicals/${enc(dtxsid)}`,
  structure: (dtxsid: string) => `${API_V2}/chemicals/${enc(dtxsid)}/structure.png`,
  identity: (id: string) => `${API_V2}/studies/${enc(id)}/identity`,
  deletePreview: (id: string) => `${API_V2}/studies/${enc(id)}/delete-preview`,
  delete: (id: string) => `${API_V2}/studies/${enc(id)}/delete`,
}

/** §2.1 every session, grouped by chemical. */
export function getStudies(signal?: AbortSignal): Promise<StudiesList> {
  return getJson<StudiesList>(m1Paths.studies(), signal)
}

/** §2.2 one session: its row and its detail. 404 `study_not_found` creates nothing. */
export function getStudy(id: string, signal?: AbortSignal): Promise<StudyDetail> {
  return getJson<StudyDetail>(m1Paths.study(id), signal)
}

/** §2.4 whether a study of this DTXSID can be created, and the format it would get. No side effect. */
export function getCreationCheck(dtxsid: string, signal?: AbortSignal): Promise<CreationCheck> {
  return getJson<CreationCheck>(m1Paths.creationCheck(dtxsid), signal)
}

/** §2.5 the chemical lookup (PubChem); takes a few seconds. */
export function lookupChemical(dtxsid: string, signal?: AbortSignal): Promise<ChemicalLookup> {
  return getJson<ChemicalLookup>(m1Paths.chemical(dtxsid), signal)
}

/** §2.6 create a study with a confirmed identity; 201 with the new row. */
export function createStudy(body: CreateStudyRequest): Promise<StudyRow> {
  return sendJson<StudyRow>('POST', m1Paths.studies(), body)
}

/** §2.7 fill a missing identity. */
export function recordIdentity(id: string, body: RecordIdentityRequest): Promise<StudyRow> {
  return sendJson<StudyRow>('PUT', m1Paths.identity(id), body)
}

/** §2.8 the delete dry run, as served (the token beside the §4.3 object). */
export function getDeletePreview(id: string, signal?: AbortSignal): Promise<DeletePreview> {
  return getJson<DeletePreview>(m1Paths.deletePreview(id), signal)
}

/**
 * §2.8 as the kit's <ConfirmAct> takes it: the §4.3 object with the token and
 * the text to type inside it (R4 asks for that place; until then the client
 * moves them there).
 */
export async function getDeleteDryRun(id: string, signal?: AbortSignal): Promise<DryRun> {
  const p = await getDeletePreview(id, signal)
  return { ...p.confirm, preview_token: p.preview_token, type_to_confirm: p.type_to_confirm }
}

/** §2.9 delete, with the id the person typed and the token of the list they reviewed. */
export function deleteStudy(id: string, confirmId: string, previewToken: string): Promise<DeleteResult> {
  return sendJson<DeleteResult>('POST', m1Paths.delete(id), { confirm_id: confirmId, preview_token: previewToken })
}
