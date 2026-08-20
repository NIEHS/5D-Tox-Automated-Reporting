import { useEffect, useState } from "react";
import { api, SessionSummary } from "../api";
import { ErrorBox, Spinner, StepProps } from "./shared";

export function SessionPicker({ dtxsid, setDtxsid, next, refresh }: StepProps) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newId, setNewId] = useState("");

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

  async function choose(id: string) {
    setDtxsid(id);
    await refresh();
    next();
  }

  function createNew() {
    const id = newId.trim();
    if (!id) return;
    // Creation is implicit: the session dir is made on first upload. We just
    // select the id and move to the Upload step.
    void choose(id);
  }

  return (
    <div className="panel">
      <h2>Step 1 · Choose or create a session</h2>
      <p className="help">
        A session is a DTXSID-keyed working folder. Pick an existing one to
        continue, or enter a new DTXSID to start fresh — the folder is created
        when you upload the first file.
      </p>

      <div className="field-row">
        <label>
          New session DTXSID
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
          Create &amp; continue
        </button>
      </div>

      <h3 style={{ marginTop: "1.5rem" }}>
        Existing sessions {loading && <Spinner />}
      </h3>
      <ErrorBox error={error} />
      {sessions.length === 0 && !loading ? (
        <p className="muted">No sessions yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>DTXSID</th>
              <th>Sections</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((s) => (
              <tr key={s.dtxsid}>
                <td>
                  <code>{s.dtxsid}</code>
                  {s.dtxsid === dtxsid && (
                    <span className="badge ok" style={{ marginLeft: 8 }}>
                      selected
                    </span>
                  )}
                </td>
                <td>{s.sections}</td>
                <td style={{ textAlign: "right" }}>
                  <button onClick={() => choose(s.dtxsid)}>Open</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
