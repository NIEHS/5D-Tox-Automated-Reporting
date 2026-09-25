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

// One entry of the tree-DERIVED section catalog merged with live readiness
// (GET /api/workflow/{dtxsid}/sections). The Sections screen renders its rows
// from THIS — the section identity (kind/approvable/instance_of) is derived from
// the document tree, not hardcoded in the client. `kind` is the producer class
// ("llm" | "programmatic" | "derived" | "authored"); `instance_of` is the family
// ("bm2" | "genomics") for concrete instances, null for singletons/group
// narratives; `present` is whether the section has content on disk.
export interface SectionInfo {
  key: string;
  kind: string;
  approvable: boolean;
  instance_of: string | null;
  // The DocNode region this section lives in ("front" | "body" | null). Lets the
  // Sections screen group the front-matter rows apart from body sections.
  region?: string | null;
  enabled: boolean;
  approved: boolean;
  blocked_by: string[];
  present: boolean;
}

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

// Configurator: a saved report VIEW — a render-time lens (structure + data
// filters + chart allowlist) over the one report. The server normalizes the
// `filters` block to its canonical nested shape on save; the UI edits the
// friendlier per-area form and lets the server validate. `charts` is presence-
// sensitive: absent/null ⇒ render all, [] ⇒ render none.
export interface ReportView {
  document?: unknown;
  filters?: Record<string, unknown>;
  charts?: string[] | null;
  methods?: unknown;
}

// --- Session interpretation chat (ADR-0022) ---
export interface ChatReference { token: string; title: string; year?: number | null; venue?: string; doi?: string }
export interface ChatUnresolved { where: string; token: string; issue: string; sentence: string }
export interface ChatToolCall { tool: string; input?: unknown; output_chars?: number }
export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  at?: string;
  references?: ChatReference[];
  unresolved_citations?: ChatUnresolved[];
  tool_trace?: ChatToolCall[];
  model_used?: string;
}
export interface ChatThreadSummary { id: string; title: string; created_at: string; updated_at: string; message_count: number }
export interface ChatThread extends ChatThreadSummary { messages: ChatMessage[]; sources: unknown[] }
export interface ChatTurnResult {
  answer: string;
  references: ChatReference[];
  unresolved_citations: ChatUnresolved[];
  tool_trace: ChatToolCall[];
  model_used: string;
  rounds: number;
  thread_id: string;
}
export interface ChatEvent { event: string; data: Record<string, any> }

// --- Document structure (visual editor) ---
// A node entry exactly as it appears in the document YAML. `children` nests;
// a top-level entry with `region` (and no type) is a region container.
export interface DocEntry {
  id?: string;
  type?: string;
  title?: string;
  region?: string;
  children?: DocEntry[];
  [key: string]: unknown;
}
export interface CatalogType {
  allowed_children: string[];
  requires: string[];
  orientable: boolean;
  breakable: boolean;
  editable: boolean;
  captionable: boolean;
  headingless: boolean;
  subtypable: boolean;
  freeform: boolean;
}
export interface DocumentCatalog {
  types: Record<string, CatalogType>;
  node_keys: string[];
  regions: string[];
  vocab: {
    platforms: string[];
    data_keys: string[];
    narrative_keys: string[];
    methods_keys: string[];
    subtypes: string[];
    orientations: string[];
  };
}

export interface SectionData {
  paragraphs?: string[];
  // Materialized apical result sections carry their prose as `narrative` (a
  // paragraph list) alongside `tables_json`; report_data reads it directly.
  // Usually a list; a legacy card may store a single string, so the type admits
  // both and paragraphCount normalizes.
  narrative?: string[] | string;
  // Materials & Methods stores its prose per subsection (methods.json: sections[]
  // each with its own paragraphs) rather than as one top-level list.
  sections?: { key?: string; heading?: string; paragraphs?: string[] }[];
  // Apical BMD Summary: a derived endpoint table, not prose.
  endpoints?: unknown[];
  approved?: boolean;
  version?: number;
  stale?: boolean;
  // Stamped when a data reprocess regenerated this section (currency-forced).
  // The per-section publish blocker carries the same reason; the UI decides
  // "Re-accept" from the parent-derived blockedReason prop, not from this field.
  regenerated?: { reason?: string } | null;
  // Phase 3b inform-signal: a data-derived WORD (direction/trend) flipped under an
  // APPROVED programmatic section's wording after a reprocess. NON-blocking — the
  // numbers refreshed correctly, but the author's committed wording may now
  // contradict the data. Each entry is a "finding_id.slot" key. Absent = no flip.
  wording_review?: string[];
  // Front-matter status rows carry an explicit filled-vs-pending flag: their content
  // is boilerplate/authored, so a non-null object does NOT imply real content (an
  // empty About This Report is still an object). The row reads this, not `!!content`.
  has_content?: boolean;
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

// --- Knowledge-graph crawl config (the literature-crawl spec editor) ---
export interface CrawlConfig {
  max_depth: number;
  max_papers: number;
  max_api_calls: number;
  relevance_threshold: number;
  saturation_window: number;
  saturation_threshold: number;
  max_refs_per_paper: number;
  max_cites_per_paper: number;
  rate_limit_delay: number;
  topic_keywords: string[];
  organ_keywords: Record<string, string[]>;
}

// --- Corpus curation (organ vocabulary of the literature knowledge base) ---
export interface CorpusOrgan {
  organ: string;
  genes_count: number;
  papers_count: number;
  total: number;
  sources: string[];
  mapped_to: string | null; // canonical target; null present in net map ⇒ drop
}
export interface CorpusTweak {
  op: string;
  from: string;
  to: string | null;
  ts: string;
}

// The server-computed change-list vs the frozen original. Empty ⇒ unchanged.
export interface CrawlConfigDiff {
  [scalar: string]:
    | { original: number; current: number }
    | { added: string[]; removed: string[] }
    | {
        added?: Record<string, string[]>;
        removed?: Record<string, string[]>;
        changed?: Record<string, { added: string[]; removed: string[] }>;
      };
}

export interface CrawlConfigResponse {
  config: CrawlConfig;
  is_default: boolean;
  original: CrawlConfig;
  diff: CrawlConfigDiff;
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

  // Citations the verification layers could not resolve (Background inline/
  // reference-line issues persisted with the section; genomics [Pn] tokens the
  // assembly dropped, plus human-edit hazards). Empty for apical-only sessions.
  getCitationWarnings: (dtxsid: string) =>
    fetch(`/api/session/${encodeURIComponent(dtxsid)}/citation-warnings`).then((r) =>
      jsonOrThrow<{
        count: number;
        background: { where: string; token: string; issue: string; sentence: string }[];
        genomics: { kind: string; organ: string; sex?: string; issue: string; tokens: string[]; sentences?: string[] }[];
      }>(r)
    ),

  // --- Session interpretation chat (ADR-0022) ---
  listChatThreads: (dtxsid: string) =>
    fetch(`/api/chat/${encodeURIComponent(dtxsid)}/threads`).then((r) =>
      jsonOrThrow<{ threads: ChatThreadSummary[] }>(r)
    ),
  createChatThread: (dtxsid: string, title = "") =>
    fetch(`/api/chat/${encodeURIComponent(dtxsid)}/threads`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }).then((r) => jsonOrThrow<ChatThread>(r)),
  getChatThread: (dtxsid: string, threadId: string) =>
    fetch(`/api/chat/${encodeURIComponent(dtxsid)}/threads/${encodeURIComponent(threadId)}`).then((r) =>
      jsonOrThrow<ChatThread>(r)
    ),
  deleteChatThread: (dtxsid: string, threadId: string) =>
    fetch(`/api/chat/${encodeURIComponent(dtxsid)}/threads/${encodeURIComponent(threadId)}`, {
      method: "DELETE",
    }).then((r) => jsonOrThrow<{ ok: boolean }>(r)),
  // Ask one question; progress events (thinking / tool_call / tool_result) are
  // delivered to onEvent as they stream, and the promise resolves with the
  // `complete` payload (the persisted answer + its grounding) or rejects on `error`.
  sendChatMessage: async (
    dtxsid: string,
    threadId: string,
    message: string,
    onEvent?: (ev: ChatEvent) => void
  ): Promise<ChatTurnResult> => {
    const resp = await fetch(
      `/api/chat/${encodeURIComponent(dtxsid)}/threads/${encodeURIComponent(threadId)}/messages`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message }) }
    );
    if (!resp.ok || !resp.body) {
      let detail = `chat request failed (${resp.status})`;
      try {
        const j = await resp.json();
        detail = j.error ?? j.detail ?? detail;
      } catch {
        /* keep default */
      }
      throw new Error(detail);
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let result: ChatTurnResult | null = null;
    let errored: string | null = null;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const chunks = buf.split("\n\n");
      buf = chunks.pop() ?? "";
      for (const chunk of chunks) {
        let ev = "message";
        let data = "";
        for (const line of chunk.split("\n")) {
          if (line.startsWith("event:")) ev = line.slice(6).trim();
          else if (line.startsWith("data:")) data += line.slice(5).trim();
        }
        let parsed: Record<string, any> = {};
        try {
          parsed = data ? JSON.parse(data) : {};
        } catch {
          parsed = {};
        }
        if (ev === "complete") result = parsed as ChatTurnResult;
        else if (ev === "error") errored = parsed.error ?? data;
        else onEvent?.({ event: ev, data: parsed });
      }
    }
    if (errored) throw new Error(errored);
    if (!result) throw new Error("chat produced no answer");
    return result;
  },

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
  // --- Visual structure editor helpers (web_routes/structure_routes) ---
  getDocumentCatalog: () =>
    fetch(`/api/document-structure/catalog`).then((r) => jsonOrThrow<DocumentCatalog>(r)),
  parseDocumentConfig: (yamlText: string) =>
    fetch(`/api/document-structure/parse`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ yaml: yamlText }),
    }).then((r) => jsonOrThrow<{ document: DocEntry[] }>(r)),
  dumpDocumentConfig: (document: DocEntry[]) =>
    fetch(`/api/document-structure/dump`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document }),
    }).then((r) => jsonOrThrow<{ yaml: string }>(r)),
  validateDocumentConfig: (document: DocEntry[]) =>
    fetch(`/api/document-structure/validate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document }),
    }).then((r) => jsonOrThrow<{ ok: boolean; error?: string; node_id?: string | null }>(r)),

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

  // --- Configurator: report VIEWS (per-session data filters + chart allowlist) ---
  // A view is a saved lens over the one report; `default` is implicit and always
  // listed. Filters are a render-time projection (no reprocess).
  listViews: (dtxsid: string) =>
    fetch(`/api/views/${encodeURIComponent(dtxsid)}`).then((r) =>
      jsonOrThrow<{ views: string[]; default: string }>(r)
    ),
  getView: (dtxsid: string, name: string) =>
    fetch(
      `/api/views/${encodeURIComponent(dtxsid)}/${encodeURIComponent(name)}`
    ).then((r) => jsonOrThrow<{ view: ReportView }>(r)),
  saveView: async (dtxsid: string, name: string, view: ReportView) => {
    const r = await fetch(
      `/api/views/${encodeURIComponent(dtxsid)}/${encodeURIComponent(name)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ view }),
      }
    );
    if (r.status === 422) {
      const body = await r.json().catch(() => ({}));
      throw new Error(body.error || body.detail || "Invalid view");
    }
    return jsonOrThrow<{ saved: boolean }>(r);
  },
  deleteView: (dtxsid: string, name: string) =>
    fetch(
      `/api/views/${encodeURIComponent(dtxsid)}/${encodeURIComponent(name)}`,
      { method: "DELETE" }
    ).then((r) => jsonOrThrow<{ deleted: boolean }>(r)),

  // --- Configurator: DEFAULT (template) data-filter blocks, as YAML ---
  // The global counterpart to per-session views; edits the git-tracked template's
  // organs/sex/assays/genes/gene_sets/charts blocks (comments stripped on save).
  getReportFiltersDefault: () =>
    fetch(`/api/report-filters-default`).then((r) =>
      jsonOrThrow<{ yaml: string }>(r)
    ),
  saveReportFiltersDefault: async (yaml: string) => {
    const r = await fetch(`/api/report-filters-default`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ yaml }),
    });
    if (r.status === 422) {
      const body = await r.json().catch(() => ({}));
      throw new Error(body.error || body.detail || "Invalid filters");
    }
    return jsonOrThrow<{ saved: boolean }>(r);
  },

  // Generate + persist Materials & Methods. /api/generate-methods extracts study
  // metadata (fingerprints/.bm2/animal report) + calls the LLM, returns the
  // structured methods; we save it as the `methods` section. Returns the result,
  // or null if generation produced nothing.
  // Generate the Summary section (LLM synthesis of the APPROVED sections). Does
  // NOT persist — the caller saves via saveSection so the row can be approved.
  generateSummary: async (
    dtxsid: string,
    identity: Record<string, unknown>
  ): Promise<{ paragraphs: string[]; model_used?: string }> => {
    const resp = await fetch(`/api/generate-summary`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dtxsid, identity }),
    });
    return jsonOrThrow<{ paragraphs: string[]; model_used?: string }>(resp);
  },

  // The Apical Endpoint BMD Summary, DERIVED on demand from the session's
  // bm2_* result sections (deterministic). Approving it persists the table as
  // bmd_summary.json via saveSection/approveSection.
  getBmdSummary: (dtxsid: string) =>
    fetch(`/api/session/${encodeURIComponent(dtxsid)}/bmd-summary`).then((r) =>
      jsonOrThrow<{ endpoints: unknown[]; sorted_by?: string }>(r)
    ),

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

  // Tree-DERIVED section catalog merged with readiness — the row set the
  // Sections screen renders, replacing its hardcoded FRONT_MATTER + approvable
  // allowlist. Adding a section to the template adds it here.
  getSections: (dtxsid: string) =>
    fetch(`/api/workflow/${encodeURIComponent(dtxsid)}/sections`).then((r) =>
      jsonOrThrow<{ sections: SectionInfo[] }>(r)
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
    view?: string
  ) =>
    fetch(`/api/preview/${encodeURIComponent(dtxsid)}/materialize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // The endpoint reads `view` (the render lens); a view's filters/charts are
      // applied at materialize time. Omitted ⇒ the default view.
      body: JSON.stringify({ surface, view }),
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

  // --- Knowledge-graph crawl config (view / tweak / reset the crawl spec) ---
  getCrawlConfig: (dtxsid: string, loadDefault = false) =>
    fetch(
      `/api/crawl-config/${encodeURIComponent(dtxsid)}${loadDefault ? "?default=1" : ""}`
    ).then((r) => jsonOrThrow<CrawlConfigResponse>(r)),
  saveCrawlConfig: async (dtxsid: string, config: CrawlConfig) => {
    const r = await fetch(`/api/crawl-config/${encodeURIComponent(dtxsid)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config }),
    });
    // 422 carries the validation message — surface it as the error text.
    if (r.status === 422) {
      const body = await r.json().catch(() => ({}));
      throw new Error(body.error || body.detail || "Invalid crawl configuration");
    }
    return jsonOrThrow<{ ok: boolean; diff: CrawlConfigDiff }>(r);
  },
  resetCrawlConfig: (dtxsid: string) =>
    fetch(`/api/crawl-config/${encodeURIComponent(dtxsid)}/reset`, {
      method: "POST",
    }).then((r) => jsonOrThrow<CrawlConfigResponse & { ok: boolean; reset: boolean }>(r)),

  // --- Corpus curation (organ vocabulary) ---
  getCorpusOrgans: (dtxsid: string) =>
    fetch(`/api/corpus/${encodeURIComponent(dtxsid)}/organs`).then((r) =>
      jsonOrThrow<{ inventory: CorpusOrgan[]; canonical: string[]; is_curated: boolean }>(r)
    ),
  getCorpusHistory: (dtxsid: string) =>
    fetch(`/api/corpus/${encodeURIComponent(dtxsid)}/history`).then((r) =>
      jsonOrThrow<{ tweaks: CorpusTweak[] }>(r)
    ),
  mapCorpusOrgan: async (dtxsid: string, from: string, to: string | null) => {
    const r = await fetch(`/api/corpus/${encodeURIComponent(dtxsid)}/organs/map`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ from, to }),
    });
    if (r.status === 422) {
      const body = await r.json().catch(() => ({}));
      throw new Error(body.error || body.detail || "Invalid organ mapping");
    }
    return jsonOrThrow<{
      ok: boolean;
      tweak: CorpusTweak;
      net_map: Record<string, string | null>;
    }>(r);
  },
  materializeCorpus: (dtxsid: string) =>
    fetch(`/api/corpus/${encodeURIComponent(dtxsid)}/materialize`, {
      method: "POST",
    }).then((r) =>
      jsonOrThrow<{ ok: boolean; path: string; counts: Record<string, number>; applied_mappings: number }>(r)
    ),
  resetCorpus: (dtxsid: string) =>
    fetch(`/api/corpus/${encodeURIComponent(dtxsid)}/reset`, { method: "POST" }).then(
      (r) => jsonOrThrow<{ ok: boolean; removed: string[] }>(r)
    ),
};
