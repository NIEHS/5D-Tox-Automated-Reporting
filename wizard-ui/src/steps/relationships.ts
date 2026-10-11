// Curated join relationships for the visual query builder.
//
// The session DuckDB has NO foreign-key constraints (join discipline is by
// convention), and shared column NAMES are misleading: `dtxsid` is in every
// table (session scope, not a join), and `sex`/`organ`/`bmd` are shared
// ATTRIBUTES, not keys. So the real relationships are hand-authored here rather
// than auto-detected. This is the schema knowledge the graph builder needs — and
// the same knowledge a future "rendering domain" would encode.
//
// Every join is implicitly within one session (one dtxsid), so dtxsid is not
// part of the `on` columns — the DB holds a single session's data.

export interface Relationship {
  a: string; // table A
  b: string; // table B
  on: [string, string][]; // [colInA, colInB] pairs, AND-ed
  label?: string; // human description
}

export const RELATIONSHIPS: Relationship[] = [
  {
    a: "measurement",
    b: "subject",
    on: [["subject_id", "subject_id"]],
    label: "each measurement belongs to a subject",
  },
  {
    a: "measurement",
    b: "apical_result",
    on: [
      ["platform", "platform"],
      ["endpoint", "endpoint"],
    ],
    label: "a measured endpoint's fitted BMD",
  },
  {
    a: "apical_result",
    b: "endpoint",
    on: [
      ["platform", "platform"],
      ["endpoint", "label"],
    ],
    label: "apical result → endpoint dimension",
  },
  {
    a: "subject",
    b: "dose_group",
    on: [
      ["platform", "platform"],
      ["sex", "sex"],
      ["dose", "dose"],
    ],
    label: "a subject's dose group (design counts)",
  },
  {
    a: "gene_set_gene",
    b: "gene_set",
    on: [
      ["organ", "organ"],
      ["sex", "sex"],
      ["go_id", "go_id"],
    ],
    label: "a gene set's member genes",
  },
  {
    a: "gene_set_gene",
    b: "gene",
    on: [
      ["organ", "organ"],
      ["sex", "sex"],
      ["gene_symbol", "gene_symbol"],
    ],
    label: "member gene → per-gene BMD",
  },
  {
    a: "adversity_signature",
    b: "gene_set",
    on: [
      ["organ", "organ"],
      ["sex", "sex"],
    ],
    label: "adversity signatures ↔ gene sets (same organ × sex)",
  },
  {
    a: "experiment",
    b: "study",
    on: [["dtxsid", "dtxsid"]],
    label: "experiments belong to the study",
  },
];

// Look up the relationship connecting two tables (either direction), returning
// the `on` pairs oriented so [0] is a column in `fromTable` and [1] in `toTable`.
export function findRelationship(
  fromTable: string,
  toTable: string
): [string, string][] | null {
  for (const r of RELATIONSHIPS) {
    if (r.a === fromTable && r.b === toTable) return r.on;
    if (r.a === toTable && r.b === fromTable)
      return r.on.map(([x, y]) => [y, x] as [string, string]);
  }
  return null;
}

// The set of tables a given table can join to (for connection validation).
export function joinableTables(table: string): string[] {
  const out = new Set<string>();
  for (const r of RELATIONSHIPS) {
    if (r.a === table) out.add(r.b);
    if (r.b === table) out.add(r.a);
  }
  return [...out];
}
