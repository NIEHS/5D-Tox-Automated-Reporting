import type {
  ChemicalLookup,
  CreationCheck,
  DeletePreview,
  DeleteResult,
  ErrorEnvelope,
  StudiesList,
  StudyDetail,
  StudyRow,
} from '../../../types'
import rawChemPfhxsam from './chemical.DTXSID50469320.json'
import rawChemBpa from './chemical.DTXSID7020182.json'
import rawChemPfoa from './chemical.DTXSID8031865.json'
import rawChemNotFound from './chemical.not-found.json'
import rawChemUnreachable from './chemical.unreachable.json'
import rawCreated from './created.DTXSID7020182.json'
import rawRefExists from './create.refusal.study_exists.json'
import rawRefSuffix from './create.refusal.study_id_has_suffix.json'
import rawCheckPfhxsam from './creation-check.DTXSID50469320.json'
import rawCheckBpa from './creation-check.DTXSID7020182.json'
import rawDeleted from './delete.DTXSID5032498.json'
import rawPreview from './delete-preview.DTXSID50469320.json'
import rawRefMember from './delete-preview.refusal.member_of_report.json'
import rawRefChanged from './delete.refusal.changed_since_preview.json'
import rawStudiesContract from './studies.contract.json'
import rawStudies from './studies.json'

/**
 * M1's mock fixtures, all in this one directory so that the backend's real
 * answers (docs/ui-redesign/contracts/m1/, when they come) are a swap.
 *
 * | file | from |
 * |---|---|
 * | studies.contract.json, chemical.*, creation-check.*, create.refusal.*, delete*.json, detail.contract.DTXSID50469320_nb.json | contract.md §4, verbatim (extracted by tools/extract_fixtures.py); chemical.DTXSID8031865.json is PubChem's own record for CID 9554 in the same shape |
 * | studies.json, detail.*.json, created.DTXSID7020182.json | BUILT (tools/build_world.py) from the contract's rows and the kit's real state fixtures, so the list, the study page and the state agree for every mocked id: rows for the other state fixtures and for the mouse study and NIEHS-13's published content are CONSTRUCTED in the contract's shape; `stands` follows the state fixture's phase with contract §3's wording; banners use spec §3's wording |
 * | structures.ts | PubChem's own structure PNGs |
 *
 * Bisphenol A (DTXSID7020182) is not in the list: it is what S2's create makes
 * (`created.DTXSID7020182.json`, the contract's row).
 */

interface Saved<T> {
  status: number
  body: T
}
const body = <T,>(raw: unknown): T => (raw as Saved<T>).body

export const M1_STUDIES: StudiesList = body(rawStudies)
/** contract §4.1 as written (abridged, five chemicals) */
export const M1_STUDIES_CONTRACT: StudiesList = body(rawStudiesContract)
export const M1_CREATED_BPA: StudyRow = body(rawCreated)

// the contract's own detail is kept for reference; the built one (same banner and pin) is served
const details = import.meta.glob<Saved<StudyDetail>>(['./detail.*.json', '!./detail.contract.*.json'], { eager: true, import: 'default' })
/** GET /api/v2/studies/{id}, by id */
export const M1_DETAILS: Record<string, StudyDetail> = Object.fromEntries(
  Object.values(details).map((d) => [d.body.id, d.body]),
)

export const M1_CHEMICALS: Record<string, ChemicalLookup> = {
  DTXSID50469320: body(rawChemPfhxsam),
  DTXSID7020182: body(rawChemBpa),
  /** real PubChem values for CID 9554 (fetched 2026-10-15), in the contract's shape: the "Look up the chemical" demo */
  DTXSID8031865: body(rawChemPfoa),
}
export const M1_CHEM_NOT_FOUND: ErrorEnvelope = body(rawChemNotFound)
export const M1_CHEM_UNREACHABLE: ErrorEnvelope = body(rawChemUnreachable)

/** The creation checks of contract §4.3 (exists) and §4.4 (new, default format). */
export const M1_CHECK_PFHXSAM: CreationCheck = body(rawCheckPfhxsam)
export const M1_CHECK_BPA: CreationCheck = body(rawCheckBpa)

export const M1_REFUSAL_STUDY_EXISTS: ErrorEnvelope = body(rawRefExists)
export const M1_REFUSAL_SUFFIX: ErrorEnvelope = body(rawRefSuffix)
export const M1_REFUSAL_MEMBER: ErrorEnvelope = body(rawRefMember)
export const M1_REFUSAL_CHANGED: ErrorEnvelope = body(rawRefChanged)

export const M1_DELETE_PREVIEW_PFHXSAM: DeletePreview = body(rawPreview)
export const M1_DELETED_TRICLOSAN: DeleteResult = body(rawDeleted)

export { STRUCTURE_PNG_BASE64 } from './structures'
