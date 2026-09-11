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

// --- Section authoring (Phase 6) ---

// One entry of the server-DERIVED readiness map
// (GET /api/workflow/{dtxsid}/section-readiness). The UI renders enable/lock/
// blocked-by from THIS — never a client-side ready.* flag.
export interface SectionReadiness {
  enabled: boolean;
  blocked_by: string[];
  approved: boolean;
}
export type SectionReadinessMap = Record<string, SectionReadiness>;

// Report-grain publish gate (Phase 3a currency BLOCK). GET
// /api/workflow/{dtxsid}/publish-readiness. A data reprocess withdraws FINAL
// from the report's LLM sections and stamps a `regenerated` reason; publishing
// is blocked until each is re-accepted. Rendered ENTIRELY from this — never
// guessed.
export interface PublishBlocker {
  section_key: string;
  reason: string;
}
export interface PublishReadiness {
  can_publish: boolean;
  blocking: PublishBlocker[];
}

// A section's editable content as loaded from GET /api/session/{dtxsid}.
// Configurator: human-set report front-matter.
export interface FrontMatterAuthor {
  name: string;
  affiliation?: string;
  role?: string;
}
export interface FrontMatterContributor {
  name: string;
  role?: string;
}
export interface FrontMatter {
  authors?: FrontMatterAuthor[];
  contributors?: FrontMatterContributor[];
  publication?: {
    report_number?: string;
    doi?: string;
    report_date?: string;
  };
}

export interface SectionData {
  paragraphs?: string[];
  // Materialized apical result sections carry their prose as `narrative` (a
  // paragraph list) alongside `tables_json`; report_data reads it directly.
  narrative?: string[];
  approved?: boolean;
  version?: number;
  stale?: boolean;
  // Stamped when a data reprocess regenerated this section (currency-forced).
  // The per-section publish blocker carries the same reason; the UI decides
  // "Re-accept" from the parent-derived blockedReason prop, not from this field.
  regenerated?: { reason?: string } | null;
  [k: string]: unknown;
}

export interface SessionLoad {
  exists: boolean;
  background?: SectionData | null;
  methods?: SectionData | null;
  bmd_summary?: SectionData | null;
  summary?: SectionData | null;
  bm2_sections?: Record<string, SectionData>;
  genomics_sections?: Record<string, SectionData>;
  meta?: Record<string, unknown> | null;
  identity?: Record<string, unknown> | null;
  [k: string]: unknown;
}

// A materialize response (POST /api/preview/{dtxsid}/materialize).
export interface PreviewManifest {
  version: string;
  ts: string;
  deliverable: string;
  files: Record<string, string>;
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

  getIdentity: (dtxsid: string) =>
    fetch(`/api/wizard/${encodeURIComponent(dtxsid)}/identity`).then((r) =>
      jsonOrThrow<{ identity: Record<string, string> }>(r)
    ),

  // --- Configurator: front-matter metadata (authors/contributors/publication) ---
  getFrontMatter: (dtxsid: string) =>
    fetch(`/api/document/${encodeURIComponent(dtxsid)}/front-matter`).then((r) =>
      jsonOrThrow<{ front_matter: FrontMatter }>(r)
    ),
  saveFrontMatter: (dtxsid: string, front_matter: FrontMatter) =>
    fetch(`/api/document/${encodeURIComponent(dtxsid)}/front-matter`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ front_matter }),
    }).then((r) => jsonOrThrow<{ ok: boolean; front_matter: FrontMatter }>(r)),

  // --- Configurator: document structure (session YAML, over the existing route) ---
  getDocumentConfig: (dtxsid: string, loadDefault = false) =>
    fetch(
      `/api/document-config/${encodeURIComponent(dtxsid)}${loadDefault ? "?default=1" : ""}`
    ).then((r) => jsonOrThrow<{ yaml: string; is_default: boolean }>(r)),
  saveDocumentConfig: async (dtxsid: string, yaml: string) => {
    const r = await fetch(`/api/document-config/${encodeURIComponent(dtxsid)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ yaml }),
    });
    // 422 carries the validation message — surface it as the error text.
    if (r.status === 422) {
      const body = await r.json().catch(() => ({}));
      throw new Error(body.error || body.detail || "Invalid document structure");
    }
    return jsonOrThrow<{ ok: boolean }>(r);
  },

  // Generate + persist Materials & Methods. /api/generate-methods extracts study
  // metadata (fingerprints/.bm2/animal report) + calls the LLM, returns the
  // structured methods; we save it as the `methods` section. Returns the result,
  // or null if generation produced nothing.
  generateMethods: async (
    dtxsid: string,
    identity: Record<string, unknown>
  ): Promise<Record<string, unknown> | null> => {
    const resp = await fetch(`/api/generate-methods`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ identity: { ...identity, dtxsid } }),
    });
    const result = await jsonOrThrow<Record<string, unknown>>(resp);
    if (!result || !result.sections) return null;
    await fetch(`/api/session/save-section`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dtxsid, section_type: "methods", data: result }),
    }).then((r) => jsonOrThrow<{ ok: boolean }>(r));
    return result;
  },

  // Generate the Background section from the compound identity alone (ATSDR/IRIS/
  // PubChem lookups + LLM). /api/generate streams SSE progress then a `complete`
  // event carrying the result; we consume the stream and resolve with the final
  // payload. Does NOT persist — the caller saves via saveSection.
  generateBackground: async (
    identity: Record<string, unknown>
  ): Promise<{ paragraphs?: string[]; references?: unknown[] } & Record<string, unknown>> => {
    const resp = await fetch(`/api/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ identity }),
    });
    if (!resp.ok || !resp.body) {
      throw new Error(`Background generation failed (${resp.status})`);
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let result: Record<string, unknown> | null = null;
    let errored: string | null = null;
    // Parse the SSE stream: events separated by a blank line, each with an
    // `event:` and a `data:` line. We only act on `complete` / `error`.
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const chunks = buf.split("\n\n");
      buf = chunks.pop() ?? ""; // keep the trailing partial event
      for (const chunk of chunks) {
        let ev = "message";
        let data = "";
        for (const line of chunk.split("\n")) {
          if (line.startsWith("event:")) ev = line.slice(6).trim();
          else if (line.startsWith("data:")) data += line.slice(5).trim();
        }
        if (ev === "complete" && data) {
          try {
            result = JSON.parse(data);
          } catch {
            /* ignore malformed */
          }
        } else if (ev === "error" && data) {
          try {
            errored = (JSON.parse(data) as { error?: string }).error ?? data;
          } catch {
            errored = data;
          }
        }
      }
    }
    if (errored) throw new Error(errored);
    if (!result) throw new Error("Background generation produced no result");
    return result;
  },

  isProcessed: (dtxsid: string) =>
    fetch(`/api/wizard/${encodeURIComponent(dtxsid)}/processed`).then((r) =>
      jsonOrThrow<{ processed: boolean }>(r)
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

  // Materialize apical result sections from the Process cache to disk as
  // provisional (unapproved) drafts, so they show in the document surface and the
  // deliverable renders complete. Idempotent; genomics is not materialized.
  materializeSections: (dtxsid: string) =>
    fetch(`/api/pool/materialize-sections/${encodeURIComponent(dtxsid)}`, {
      method: "POST",
    }).then((r) => jsonOrThrow<{ ok: boolean; materialized: string[] }>(r)),

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

  // --- Section authoring (Phase 6) ---

  // DERIVED per-section readiness — the replacement for the legacy imperative
  // ready.methods / ready.summary flags.
  getSectionReadiness: (dtxsid: string) =>
    fetch(`/api/workflow/${encodeURIComponent(dtxsid)}/section-readiness`).then(
      (r) => jsonOrThrow<SectionReadinessMap>(r)
    ),

  // DERIVED report-grain publish gate (currency BLOCK).
  getPublishReadiness: (dtxsid: string) =>
    fetch(`/api/workflow/${encodeURIComponent(dtxsid)}/publish-readiness`).then(
      (r) => jsonOrThrow<PublishReadiness>(r)
    ),

  loadSession: (dtxsid: string) =>
    fetch(`/api/session/${encodeURIComponent(dtxsid)}`).then((r) =>
      jsonOrThrow<SessionLoad>(r)
    ),

  // Persist section content WITHOUT changing approval (archive=False server-side).
  saveSection: (
    dtxsid: string,
    sectionType: string,
    data: Record<string, unknown>,
    extra: { bm2_slug?: string; organ?: string; sex?: string } = {}
  ) =>
    fetch(`/api/session/save-section`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dtxsid, section_type: sectionType, data, ...extra }),
    }).then((r) => jsonOrThrow<{ ok: boolean }>(r)),

  // Approve (lock) a section. The server also runs style-learning on approve.
  approveSection: (
    dtxsid: string,
    sectionType: string,
    data: Record<string, unknown>,
    extra: { bm2_slug?: string; organ?: string; sex?: string } = {}
  ) =>
    fetch(`/api/session/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dtxsid, section_type: sectionType, data, ...extra }),
    }).then((r) => jsonOrThrow<Record<string, unknown>>(r)),

  // Revise (release a blessed section back to editable) — preserves content and
  // runs the human-release down-ratchet. `reason` is the free-text "why are you
  // reopening this?" recorded on the version trail; empty is accepted server-side.
  unapproveSection: (
    dtxsid: string,
    sectionType: string,
    reason: string,
    extra: { bm2_slug?: string; organ?: string; sex?: string } = {}
  ) =>
    fetch(`/api/session/unapprove`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dtxsid, section_type: sectionType, reason, ...extra }),
    }).then((r) => jsonOrThrow<{ ok: boolean }>(r)),

  // --- Materialized preview (Phase 5) ---

  materializePreview: (
    dtxsid: string,
    surface = "docx",
    version?: string
  ) =>
    fetch(`/api/preview/${encodeURIComponent(dtxsid)}/materialize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ surface, version }),
    }).then((r) => jsonOrThrow<PreviewManifest>(r)),

  // URLs (not fetches) — used as iframe src / download href.
  previewViewUrl: (dtxsid: string, version = "default", surface = "html") =>
    `/api/preview/${encodeURIComponent(dtxsid)}/view?version=${encodeURIComponent(
      version
    )}&surface=${encodeURIComponent(surface)}`,

  previewDownloadUrl: (dtxsid: string, version = "default", surface = "docx") =>
    `/api/preview/${encodeURIComponent(
      dtxsid
    )}/download?version=${encodeURIComponent(version)}&surface=${encodeURIComponent(
      surface
    )}`,
};
