// Typed fetch wrappers for the wizard. Every real workflow step reuses an
// existing backend route; only /api/wizard/* is new. The wizard never derives
// phase itself — it reads GET /api/workflow/{dtxsid}/state after each mutation.

export type Phase =
  | "EMPTY"
  | "UPLOADED"
  | "VALIDATION_ERRORS"
  | "VALIDATED"
  | "INTEGRATED"
  | "APPROVED";

export interface WorkflowState {
  phase: Phase;
  legal_actions: string[];
  artifacts: Record<string, boolean>;
  completeness: Record<string, { complete: boolean; missing: string[] }>;
}

export interface ValidationIssue {
  severity: "error" | "warning" | string;
  kind?: string;
  message?: string;
  file_ids?: string[];
  candidates?: string[];
  [k: string]: unknown;
}

export interface ValidationReport {
  file_count: number;
  issues: ValidationIssue[];
  coverage_matrix: Record<string, unknown>;
  is_complete: boolean;
}

export interface Fingerprint {
  file_id: string;
  filename: string;
  file_type: string;
  platform: string;
  data_type: string;
  sexes: string[];
}

export interface SessionSummary {
  dtxsid: string;
  sections: number;
  section_keys: string[];
}

export interface ChartSection {
  label?: string;
  organ?: string;
  sex?: string;
  umap_png?: string;
  cluster_png?: string;
  umap_caption?: string;
  cluster_caption?: string;
}

// --- Summary-table shapes (ported from the legacy app's results tables) ---

export interface ApicalTableRow {
  label: string;
  doses?: number[];
  values?: Record<string, string>;
  n?: Record<string, number>;
  trend_marker?: string;
  emphasize?: boolean;
  is_n_row?: boolean;
  [k: string]: unknown;
}

export interface Section {
  platform: string;
  title: string;
  tables_json?: Record<string, ApicalTableRow[]>; // keyed by sex
  first_col_header?: string;
  caption?: string;
  table_type?: string;
  [k: string]: unknown;
}

export interface ApicalBmdRow {
  endpoint: string;
  sex: string;
  platform?: string;
  bmd: string;
  bmdl: string;
  loel?: number | null;
  noel?: number | null;
  direction: string;
  model_name?: string;
  [k: string]: unknown;
}

export interface GeneSetRow {
  go_id: string;
  go_term: string;
  bmd: number;
  bmdl: number;
  n_genes: number;
  n_up?: number;
  n_down?: number;
  direction?: string;
}

export interface TopGeneRow {
  gene_symbol: string;
  bmd: number;
  bmdl: number;
  fold_change?: number;
  direction?: string;
}

export interface GenomicsSection {
  organ: string;
  sex: string;
  total_probes?: number;
  total_responsive_genes?: number;
  gene_sets_by_stat?: Record<string, GeneSetRow[]>;
  top_genes?: TopGeneRow[];
  [k: string]: unknown;
}

export interface ProcessPayload {
  sections?: Section[];
  genomics_sections?: Record<string, GenomicsSection>;
  apical_bmd_summary?: ApicalBmdRow[];
  apical_bmd_summary_bmds?: ApicalBmdRow[];
  chart_images?: ChartSection[] | null;
  bmd_stats?: string[];
  bmd_stat_labels?: Record<string, string>;
  methods?: unknown;
  error?: string;
  [k: string]: unknown;
}

// --- Integrated-tree (slim structural view) ---

export interface TreeExperiment {
  name: string;
  platform: string | null;
  sex: string | null;
  organ: string | null;
  provider: string | null;
  probe_count: number;
  endpoints: string[];
  doses: number[];
}

export interface IntegratedTree {
  dtxsid: string;
  experiment_count: number;
  bmd_result_count: number;
  category_analysis_count: number;
  experiments: TreeExperiment[];
}

async function jsonOrThrow<T>(resp: Response): Promise<T> {
  const text = await resp.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    // non-JSON body
  }
  if (!resp.ok) {
    const msg = (data && (data.error || data.detail)) || text || resp.statusText;
    throw new Error(`${resp.status}: ${msg}`);
  }
  if (data && data.error) throw new Error(data.error);
  return data as T;
}

export const api = {
  listSessions: () =>
    fetch("/api/admin/sessions/summary").then((r) =>
      jsonOrThrow<{ sessions: SessionSummary[]; count: number }>(r)
    ),

  getState: (dtxsid: string) =>
    fetch(`/api/workflow/${encodeURIComponent(dtxsid)}/state`).then((r) =>
      jsonOrThrow<WorkflowState>(r)
    ),

  listFiles: (dtxsid: string) =>
    fetch(`/api/wizard/${encodeURIComponent(dtxsid)}/files`).then((r) =>
      jsonOrThrow<{ files: { name: string; size: number }[]; count: number }>(r)
    ),

  getFingerprints: (dtxsid: string) =>
    fetch(`/api/wizard/${encodeURIComponent(dtxsid)}/fingerprints`).then((r) =>
      jsonOrThrow<{ fingerprints: Fingerprint[]; count: number }>(r)
    ),

  getIntegratedTree: (dtxsid: string) =>
    fetch(`/api/integrated-tree/${encodeURIComponent(dtxsid)}`).then((r) =>
      jsonOrThrow<IntegratedTree>(r)
    ),

  uploadBm2: (dtxsid: string, files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return fetch(`/api/upload-bm2?dtxsid=${encodeURIComponent(dtxsid)}`, {
      method: "POST",
      body: fd,
    }).then((r) => jsonOrThrow<{ files: unknown[]; pool_invalidated: boolean }>(r));
  },

  uploadCsv: (dtxsid: string, files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return fetch(`/api/upload-csv?dtxsid=${encodeURIComponent(dtxsid)}`, {
      method: "POST",
      body: fd,
    }).then((r) => jsonOrThrow<{ files: unknown[]; pool_invalidated: boolean }>(r));
  },

  validate: (dtxsid: string) =>
    fetch(`/api/pool/validate/${encodeURIComponent(dtxsid)}`, {
      method: "POST",
    }).then((r) => jsonOrThrow<ValidationReport>(r)),

  resolve: (dtxsid: string, issueIndex: number, chosenFileId: string) =>
    fetch(`/api/pool/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        dtxsid,
        issue_index: issueIndex,
        chosen_file_id: chosenFileId,
      }),
    }).then((r) => jsonOrThrow<{ ok: boolean }>(r)),

  confirmMetadata: (
    dtxsid: string,
    metadata: Record<string, { platform?: string; data_type?: string }>
  ) =>
    fetch(`/api/pool/confirm-metadata/${encodeURIComponent(dtxsid)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ metadata }),
    }).then((r) => jsonOrThrow<{ ok: boolean; updated: number }>(r)),

  integrate: (
    dtxsid: string,
    identity: { name: string; casrn: string; dtxsid: string }
  ) =>
    fetch(`/api/pool/integrate/${encodeURIComponent(dtxsid)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ identity }),
    }).then((r) => jsonOrThrow<Record<string, unknown>>(r)),

  approve: (dtxsid: string) =>
    fetch(`/api/generate-animal-report/${encodeURIComponent(dtxsid)}`, {
      method: "POST",
    }).then((r) => jsonOrThrow<Record<string, unknown>>(r)),

  process: (dtxsid: string, params: Record<string, unknown>) =>
    fetch(`/api/process-integrated/${encodeURIComponent(dtxsid)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    }).then((r) => jsonOrThrow<ProcessPayload>(r)),

  reset: (dtxsid: string) =>
    fetch(`/api/pool/reset/${encodeURIComponent(dtxsid)}`, {
      method: "POST",
    }).then((r) => jsonOrThrow<{ ok: boolean; deleted: string[] }>(r)),
};
