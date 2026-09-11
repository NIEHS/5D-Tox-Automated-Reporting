import { useEffect, useState } from "react";
import { api, SessionSummary } from "../api";
import { ErrorBox, IdentityBox, Spinner, StepProps } from "./shared";

// The landing / dispatch surface at `/`. NOT part of a workflow — it is where you
// pick a test article (session) and then choose a workstream. Highlighting a
// session reveals its identifiers + a Choose button; once a session is chosen the
// three workstream pillars appear, gated by derived readiness.
export function Landing({
  dtxsid,
  setDtxsid,
  state,
  refresh,
  gotoIngest,
  gotoReport,
  gotoConfigure,
}: StepProps) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newId, setNewId] = useState("");
  // The row currently highlighted (reveals details + Choose). Distinct from the
  // committed `dtxsid`: highlighting previews, Choose commits.
  const [highlighted, setHighlighted] = useState<string | null>(dtxsid);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const r = await api.listSessions();
      setSessions(r.sessions);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  // Committing a session (Choose / create) sets it as the active dtxsid and
  // refreshes derived state so the pillars gate correctly.
  async function chooseSession(id: string) {
    setDtxsid(id);
    setHighlighted(id);
    await refresh();
  }

  function createNew() {
    const id = newId.trim();
    if (!id) return;
    // Creation is implicit: the session dir is made on first upload. Selecting it
    // here and entering data prep is where the folder gets created.
    void chooseSession(id).then(() => gotoIngest());
  }

  const chosen = dtxsid; // the committed session
  const phase = state?.phase ?? null;
  const artifacts = state?.artifacts ?? {};
  // Document workstream unlocks once the data pool is APPROVED (integrated +
  // animal report, no validation errors, not stale). If data later goes stale a
  // reprocess/re-validate drops the phase and this re-locks.
  const documentUnlocked = phase === "APPROVED";

  return (
    <div className="landing">
      <div className="landing-header">
        <h1>5D-Tox</h1>
        <p className="help">
          Choose a test article to work on, then pick a workstream.
        </p>
      </div>

      <div className="landing-body">
        {/* ── Test-article chooser ─────────────────────────────────── */}
        <section className="landing-sessions">
          <h2>Test articles</h2>

          <div className="field-row">
            <label>
              New test article (DTXSID)
              <input
                type="text"
                placeholder="DTXSID50469320"
                value={newId}
                onChange={(e) => setNewId(e.target.value)}
              />
            </label>
            <button
              className="primary"
              style={{ alignSelf: "flex-end" }}
              disabled={!newId.trim()}
              onClick={createNew}
            >
              Create &amp; start data prep
            </button>
          </div>

          <h3 style={{ marginTop: "1.25rem" }}>
            Existing {loading && <Spinner />}
          </h3>
          <ErrorBox error={error} />
          {sessions.length === 0 && !loading ? (
            <p className="muted">No test articles yet.</p>
          ) : (
            <ul className="session-list">
              {sessions.map((s) => {
                const isHi = s.dtxsid === highlighted;
                return (
                  <li
                    key={s.dtxsid}
                    className={isHi ? "session-item hi" : "session-item"}
                    onClick={() => setHighlighted(s.dtxsid)}
                    role="button"
                  >
                    <div className="session-item-row">
                      <code>{s.dtxsid}</code>
                      {s.dtxsid === chosen && (
                        <span className="badge ok" style={{ marginLeft: 8 }}>
                          selected
                        </span>
                      )}
                      <span className="muted" style={{ marginLeft: "auto" }}>
                        {s.sections} section{s.sections === 1 ? "" : "s"}
                      </span>
                    </div>
                    {isHi && (
                      <div className="session-item-detail">
                        <IdentityBox dtxsid={s.dtxsid} />
                        <button
                          className="primary"
                          onClick={(e) => {
                            e.stopPropagation();
                            void chooseSession(s.dtxsid);
                          }}
                        >
                          {s.dtxsid === chosen ? "Chosen" : "Choose"}
                        </button>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {/* ── Workstream pillars (once a session is chosen) ────────── */}
        <section className="landing-pillars">
          <h2>Workstreams</h2>
          {!chosen ? (
            <p className="muted">Choose a test article to see its workstreams.</p>
          ) : (
            <div className="pillars">
              <button
                className="pillar"
                onClick={gotoIngest}
                title="Prepare and approve the data pool"
              >
                <div className="pillar-title">Data prep</div>
                <div className="pillar-sub">
                  Upload, validate, integrate, approve the study data.
                </div>
                {phase && (
                  <div className="pillar-status">
                    <span className="badge">{phase}</span>
                  </div>
                )}
              </button>

              <button
                className="pillar"
                onClick={gotoReport}
                disabled={!documentUnlocked}
                title={
                  documentUnlocked
                    ? "Generate and review the report document"
                    : "Approve the data first — the document needs approved data."
                }
              >
                <div className="pillar-title">Document generation &amp; review</div>
                <div className="pillar-sub">
                  Process, review, and author the report.
                </div>
                <div className="pillar-status">
                  {documentUnlocked ? (
                    <span className="badge ok">ready</span>
                  ) : (
                    <span className="badge warn">needs approved data</span>
                  )}
                </div>
              </button>

              <button
                className="pillar"
                onClick={gotoConfigure}
                title="Set authors, publication details, and document structure"
              >
                <div className="pillar-title">Configure the report</div>
                <div className="pillar-sub">
                  Authors, publication details, and document structure.
                </div>
              </button>

              <button
                className="pillar"
                disabled
                title="Knowledge graph construction — coming soon"
              >
                <div className="pillar-title">Knowledge graph construction</div>
                <div className="pillar-sub">
                  Build and curate the literature knowledge graph.
                </div>
                <div className="pillar-status">
                  <span className="badge">coming soon</span>
                </div>
              </button>
            </div>
          )}
          {chosen && artifacts.hasKnowledgeBase === false && (
            <p className="muted" style={{ marginTop: "0.75rem" }}>
              Note: no knowledge base present — graph-grounded document sections
              will be unavailable.
            </p>
          )}
        </section>
      </div>
    </div>
  );
}
