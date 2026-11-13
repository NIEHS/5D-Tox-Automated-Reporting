import { useState } from "react";
import { ReportQuery, REPORT_QUERIES } from "./reportQueries";
import { findRelationship } from "./relationships";
import { runQuery, QueryResult } from "../duckdb";
import type { AsyncDuckDB } from "@duckdb/duckdb-wasm";
import { Spinner } from "./shared";

// A tiny inline SVG lineage graph: the query's tables as boxes, connected where
// a curated join exists between them. Read-only — it documents WHERE the data
// comes from, not an editable canvas.
function LineageGraph({ tables }: { tables: string[] }) {
  const boxW = 108;
  const boxH = 26;
  const gap = 34;
  const width = tables.length * boxW + (tables.length - 1) * gap || boxW;
  const height = boxH + 8;
  const y = 4;
  const centers = tables.map((_, i) => i * (boxW + gap) + boxW / 2);

  return (
    <svg className="lineage" viewBox={`0 0 ${width} ${height}`} width="100%" height={height}>
      {tables.map((t, i) => {
        if (i === 0) return null;
        const rel = findRelationship(tables[i - 1], t);
        if (!rel) return null;
        return (
          <line
            key={`e${i}`}
            x1={centers[i - 1] + boxW / 2 - 2}
            y1={y + boxH / 2}
            x2={centers[i] - boxW / 2 + 2}
            y2={y + boxH / 2}
            className="lineage-edge"
          />
        );
      })}
      {tables.map((t, i) => (
        <g key={t}>
          <rect
            x={centers[i] - boxW / 2}
            y={y}
            width={boxW}
            height={boxH}
            rx={5}
            className="lineage-box"
          />
          <text x={centers[i]} y={y + boxH / 2 + 4} className="lineage-text">
            {t}
          </text>
        </g>
      ))}
    </svg>
  );
}

function ResultPreview({ result }: { result: QueryResult }) {
  const cols = result.columns;
  const rows = result.rows.slice(0, 6);
  return (
    <div className="card-result">
      <table>
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((v, j) => (
                <td key={j} className={typeof v === "number" ? "num" : undefined}>
                  {v === null || v === undefined ? (
                    <span className="null-cell">null</span>
                  ) : (
                    String(v)
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="card-result-foot">
        {result.rowCount} row{result.rowCount === 1 ? "" : "s"}
        {result.rowCount > rows.length && ` (showing first ${rows.length})`}
      </div>
    </div>
  );
}

function ReportCard({
  q,
  db,
  onOpenInConsole,
  onOpenInBuilder,
}: {
  q: ReportQuery;
  db: AsyncDuckDB;
  onOpenInConsole: (sql: string) => void;
  onOpenInBuilder: (tables: string[]) => void;
}) {
  const [result, setResult] = useState<QueryResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showSql, setShowSql] = useState(false);

  async function run() {
    if (running) return;
    setRunning(true);
    setError(null);
    try {
      setResult(await runQuery(db, q.sql, 500));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="report-card">
      <div className="card-head">
        <span className="card-badge">{q.section}</span>
        <h3>{q.title}</h3>
      </div>
      <p className="card-desc">{q.description}</p>

      <LineageGraph tables={q.tables} />

      <div className="card-actions">
        <button className="primary" onClick={run} disabled={running}>
          {running ? <Spinner label="Running…" /> : "Run"}
        </button>
        <button className="chip-btn" onClick={() => setShowSql((s) => !s)}>
          {showSql ? "Hide SQL" : "Show SQL"}
        </button>
        <button className="chip-btn" onClick={() => onOpenInConsole(q.sql)}>
          Open in console
        </button>
        <button
          className="chip-btn"
          onClick={() => onOpenInBuilder(q.tables)}
          title="Load this query's tables (auto-joined) into the visual builder"
        >
          Open in builder
        </button>
      </div>

      {showSql && <pre className="card-sql">{q.sql}</pre>}
      {error && <div className="error-box">{error}</div>}
      {result && <ResultPreview result={result} />}
    </div>
  );
}

interface Props {
  db: AsyncDuckDB;
  onOpenInConsole: (sql: string) => void;
  onOpenInBuilder: (tables: string[]) => void;
}

export function ReportGallery({ db, onOpenInConsole, onOpenInBuilder }: Props) {
  // group cards by section, preserving REPORT_QUERIES order
  const sections: string[] = [];
  for (const q of REPORT_QUERIES) if (!sections.includes(q.section)) sections.push(q.section);

  return (
    <div className="report-gallery">
      <p className="help">
        Every table and chart in the report, and the query that assembles its data
        from this session's canonical tables. Run any card to preview its rows.
      </p>
      {sections.map((sec) => (
        <div key={sec} className="gallery-section">
          <div className="gallery-section-head">{sec}</div>
          <div className="card-grid">
            {REPORT_QUERIES.filter((q) => q.section === sec).map((q) => (
              <ReportCard
                key={q.id}
                q={q}
                db={db}
                onOpenInConsole={onOpenInConsole}
                onOpenInBuilder={onOpenInBuilder}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
