import type { ChemicalGroup, StudyRow } from '../../api/types'

/**
 * The studies list's rows (S1): the backend's grouping turned into a tree
 * for antd's Table, and the search. Nothing here decides anything about a
 * session; it arranges what the backend sent, in the backend's order.
 */

export const UNASSIGNED_KEY = 'unassigned'

export interface ListRow {
  key: string
  /** the session this row shows; null for a chemical with no study, and for the unassigned group */
  row: StudyRow | null
  group: ChemicalGroup | null
  /** the report's key for a member study ("rat") */
  memberKey?: string | null
  children?: ListRow[]
}

function memberKeyOf(group: ChemicalGroup | null, row: StudyRow): string | null {
  if (!group || row.kind !== 'member') return null
  for (const s of group.sessions) {
    const m = s.relations.members.find((x) => x.id === row.id)
    if (m) return m.key
  }
  return null
}

export function buildRows(data: { chemicals: ChemicalGroup[]; unassigned: StudyRow[] }): ListRow[] {
  const rows: ListRow[] = data.chemicals.map((g) => {
    const primary = g.primary ? (g.sessions.find((s) => s.id === g.primary) ?? null) : null
    const rest = g.sessions.filter((s) => s !== primary)
    const children = rest.map((s) => ({ key: s.id, row: s, group: g, memberKey: memberKeyOf(g, s) }))
    return { key: `chem:${g.dtxsid}`, row: primary, group: g, children: children.length ? children : undefined }
  })
  if (data.unassigned.length > 0) {
    rows.push({
      key: UNASSIGNED_KEY,
      row: null,
      group: null,
      children: data.unassigned.map((s) => ({ key: s.id, row: s, group: null })),
    })
  }
  return rows
}

function hay(...xs: (string | null | undefined)[]): string {
  return xs.filter(Boolean).join(' ').toLowerCase()
}

function sessionMatches(r: StudyRow, q: string): boolean {
  return hay(r.id, r.identity.name, r.identity.casrn, r.chemical_dtxsid).includes(q)
}

/** Filter by name, CASRN or id. A hit in a child row keeps its group and expands it. */
export function searchRows(rows: ListRow[], query: string): { rows: ListRow[]; expand: string[] } {
  const q = query.trim().toLowerCase()
  if (!q) return { rows, expand: [] }
  const out: ListRow[] = []
  const expand: string[] = []
  for (const r of rows) {
    const own = (r.row && sessionMatches(r.row, q)) || (r.group && hay(r.group.name, r.group.casrn, r.group.dtxsid).includes(q))
    const childHit = (r.children ?? []).some((c) => c.row && sessionMatches(c.row, q))
    if (childHit) expand.push(r.key)
    if (own || childHit) out.push(r)
  }
  return { rows: out, expand }
}

