import { useCallback, useEffect, useState } from "react";
import { api, CrawlConfig, CrawlConfigDiff } from "../api";
import { invalidate } from "../useServerResource";
import { ErrorBox, Spinner, StepProps } from "./shared";

// The knowledge-graph crawl-config editor. rlm-bmdx's literature knowledge base is
// built by a Semantic Scholar citation-graph crawl governed by a stopping heuristic
// (GovernorConfig). Those parameters were hardcoded; this surface lets a human view
// and tweak them, tracked against a frozen "original" baseline. Config-only — it
// does not launch a crawl (that hits Semantic Scholar, a later step).

// The nine governor scalars, with the inline meaning carried over from the dataclass.
const SCALAR_FIELDS: {
  key: keyof CrawlConfig;
  label: string;
  help: string;
  step?: number;
}[] = [
  { key: "max_depth", label: "Max depth", help: "Max citation hops from any seed paper." },
  { key: "max_papers", label: "Max papers", help: "Hard cap on total papers in the graph." },
  { key: "max_api_calls", label: "Max API calls", help: "Hard cap on Semantic Scholar requests." },
  { key: "relevance_threshold", label: "Relevance threshold", help: "Don't expand papers scoring below this (0–1).", step: 0.05 },
  { key: "saturation_window", label: "Saturation window", help: "Check the last N papers for new concepts." },
  { key: "saturation_threshold", label: "Saturation threshold", help: "Stop if fewer than this fraction of concepts are new (0–1).", step: 0.01 },
  { key: "max_refs_per_paper", label: "Max refs / paper", help: "Max references pulled per paper." },
  { key: "max_cites_per_paper", label: "Max cites / paper", help: "Max citing papers pulled per paper." },
  { key: "rate_limit_delay", label: "Rate-limit delay (s)", help: "Seconds between API calls.", step: 0.5 },
];

function textToList(text: string): string[] {
  return text
    .split(/[\n,]/)
    .map((s) => s.trim())
    .filter(Boolean);
}
function listToText(list: string[]): string {
  return list.join(", ");
}

export function KnowledgeGraph({ dtxsid, back }: StepProps) {
  const [config, setConfig] = useState<CrawlConfig | null>(null);
  const [diff, setDiff] = useState<CrawlConfigDiff>({});
  const [isDefault, setIsDefault] = useState(true);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const load = useCallback(
    async (loadDefault = false) => {
      if (!dtxsid) return;
      setLoading(true);
      setError(null);
      try {
        const r = await api.getCrawlConfig(dtxsid, loadDefault);
        setConfig(r.config);
        setDiff(r.diff);
        setIsDefault(r.is_default);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    },
    [dtxsid]
  );

  useEffect(() => {
    void load();
  }, [load]);

  async function save() {
    if (!dtxsid || !config) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const r = await api.saveCrawlConfig(dtxsid, config);
      setDiff(r.diff);
      setIsDefault(false);
      await invalidate(dtxsid);
      setSaved(true);
    } catch (e) {
      // 422 validation message surfaces here; the previous config is intact.
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  async function reset() {
    if (!dtxsid) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const r = await api.resetCrawlConfig(dtxsid);
      setConfig(r.config);
      setDiff(r.diff);
      setIsDefault(true);
      await invalidate(dtxsid);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  function setScalar(key: keyof CrawlConfig, raw: string) {
    setConfig((prev) => (prev ? { ...prev, [key]: raw === "" ? 0 : Number(raw) } : prev));
  }
  function setTopicKeywords(text: string) {
    setConfig((prev) => (prev ? { ...prev, topic_keywords: textToList(text) } : prev));
  }
  function setOrganKeywords(organ: string, text: string) {
    setConfig((prev) =>
      prev
        ? { ...prev, organ_keywords: { ...prev.organ_keywords, [organ]: textToList(text) } }
        : prev
    );
  }

  if (!dtxsid) {
    return (
      <div className="panel">
        <h2>Knowledge graph construction</h2>
        <p className="help">Select a session first.</p>
      </div>
    );
  }

  return (
    <div className="panel">
      <h2>Knowledge graph construction</h2>
      <p className="help">
        The literature knowledge base is built by a citation-graph crawl of Semantic
        Scholar, governed by a stopping heuristic. Tweak that crawl configuration
        below — changes are tracked against the original, and saved to this session.
        Running the crawl is a later step.
      </p>

      <ErrorBox error={error} />
      {loading || !config ? (
        <Spinner label="Loading crawl configuration…" />
      ) : (
        <div className="kg-grid">
          <div className="configure-form">
            <p className="help" style={{ marginTop: 0 }}>
              {isDefault ? (
                <em>Showing the original crawl configuration — saving creates this session's copy.</em>
              ) : (
                <em>This session's saved crawl configuration.</em>
              )}
            </p>

            <div className="group-heading">Governor</div>
            <div className="kg-scalars">
              {SCALAR_FIELDS.map((f) => (
                <label key={f.key} className="field-row kg-field">
                  <span className="kg-label">{f.label}</span>
                  <input
                    type="number"
                    step={f.step ?? 1}
                    value={config[f.key] as number}
                    onChange={(e) => setScalar(f.key, e.target.value)}
                  />
                  <span className="kg-help">{f.help}</span>
                </label>
              ))}
            </div>

            <div className="group-heading">Topic keywords</div>
            <p className="help" style={{ marginTop: 0 }}>
              Terms used to score paper relevance (comma- or newline-separated).
            </p>
            <textarea
              className="query-editor"
              rows={4}
              spellCheck={false}
              value={listToText(config.topic_keywords)}
              onChange={(e) => setTopicKeywords(e.target.value)}
            />

            <div className="group-heading">Organ keywords</div>
            <p className="help" style={{ marginTop: 0 }}>
              Per-organ tagging terms.
            </p>
            {Object.keys(config.organ_keywords).map((organ) => (
              <label key={organ} className="field-row kg-organ">
                <span className="kg-label">{organ}</span>
                <input
                  type="text"
                  value={listToText(config.organ_keywords[organ])}
                  onChange={(e) => setOrganKeywords(organ, e.target.value)}
                />
              </label>
            ))}

            <div className="config-save">
              <button className="primary" onClick={save} disabled={saving}>
                {saving ? <Spinner label="Validating…" /> : "Save configuration"}
              </button>
              <button onClick={reset} disabled={saving}>
                Reset to original
              </button>
              {saved && <span className="badge ok">saved</span>}
            </div>
          </div>

          <ChangesPanel diff={diff} />
        </div>
      )}

      <div className="actions">
        <button onClick={back}>Back</button>
      </div>
    </div>
  );
}

// Renders the server-computed change-list vs the frozen original.
function ChangesPanel({ diff }: { diff: CrawlConfigDiff }) {
  const keys = Object.keys(diff);
  return (
    <aside className="kg-changes">
      <div className="group-heading">Changes vs original</div>
      {keys.length === 0 ? (
        <p className="help">Unchanged from the original crawl configuration.</p>
      ) : (
        <ul className="kg-change-list">
          {keys.map((key) => {
            const entry = diff[key] as Record<string, unknown>;
            // scalar change: {original, current}
            if ("current" in entry && "original" in entry) {
              return (
                <li key={key}>
                  <code>{key}</code>: {String(entry.original)} → <strong>{String(entry.current)}</strong>
                </li>
              );
            }
            // topic_keywords: {added, removed}
            if (key === "topic_keywords") {
              const e = entry as { added?: string[]; removed?: string[] };
              return (
                <li key={key}>
                  <code>topic_keywords</code>
                  {e.added && e.added.length > 0 && (
                    <div className="kg-added">+ {e.added.join(", ")}</div>
                  )}
                  {e.removed && e.removed.length > 0 && (
                    <div className="kg-removed">− {e.removed.join(", ")}</div>
                  )}
                </li>
              );
            }
            // organ_keywords: {added?, removed?, changed?}
            if (key === "organ_keywords") {
              const e = entry as {
                added?: Record<string, string[]>;
                removed?: Record<string, string[]>;
                changed?: Record<string, { added: string[]; removed: string[] }>;
              };
              return (
                <li key={key}>
                  <code>organ_keywords</code>
                  {e.added &&
                    Object.entries(e.added).map(([o, terms]) => (
                      <div key={o} className="kg-added">
                        + {o}: {terms.join(", ")}
                      </div>
                    ))}
                  {e.removed &&
                    Object.keys(e.removed).map((o) => (
                      <div key={o} className="kg-removed">
                        − {o} (removed)
                      </div>
                    ))}
                  {e.changed &&
                    Object.entries(e.changed).map(([o, c]) => (
                      <div key={o} className="kg-changed">
                        <em>{o}</em>
                        {c.added.length > 0 && <span className="kg-added"> +{c.added.join(", ")}</span>}
                        {c.removed.length > 0 && <span className="kg-removed"> −{c.removed.join(", ")}</span>}
                      </div>
                    ))}
                </li>
              );
            }
            return (
              <li key={key}>
                <code>{key}</code> changed
              </li>
            );
          })}
        </ul>
      )}
    </aside>
  );
}
