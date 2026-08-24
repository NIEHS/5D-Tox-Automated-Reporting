import { useEffect, useRef, useState } from "react";
import { StepProps, ErrorBox, Spinner } from "./shared";
import {
  makeDuckDB,
  loadSessionParquet,
  runQuery,
  getSchema,
  QueryResult,
  SchemaTable,
} from "../duckdb";
import { QueryBuilder } from "./QueryBuilder";
import { ReportGallery } from "./ReportGallery";
import type { AsyncDuckDB } from "@duckdb/duckdb-wasm";

type Mode = "sql" | "builder" | "report";

// The Query console (ADR-0016 Phase C): an ad-hoc SQL tool running ENTIRELY IN
// THE BROWSER against this session's data. duckdb-wasm loads the session's
// per-table Parquet into native tables once; every query after that is local
// wasm — no server round-trip. Results render as a formatted React table.
const EXAMPLE_QUERIES: { label: string; sql: string }[] = [
  { label: "All measurements", sql: "SELECT * FROM measurement LIMIT 100;" },
  {
    label: "Apical BMDs",
    sql: "SELECT endpoint, sex, bmd_num, bmd_status\nFROM apical_result\nWHERE bmd_num IS NOT NULL\nORDER BY bmd_num;",
  },
  {
    label: "Gene sets by organ",
    sql: "SELECT organ, sex, count(*) AS n\nFROM gene_set\nGROUP BY 1, 2\nORDER BY 1, 2;",
  },
  {
    label: "Genes in a GO term",
    sql: "SELECT gs.go_term, gsg.gene_symbol\nFROM gene_set_gene gsg\nJOIN gene_set gs\n  ON gsg.go_id = gs.go_id AND gsg.organ = gs.organ AND gsg.sex = gs.sex\nWHERE gs.go_term ILIKE '%division%'\nLIMIT 50;",
  },
];

const MAX_ROWS = 5000;

function toCsv(result: QueryResult): string {
  const esc = (v: unknown) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const head = result.columns.map(esc).join(",");
  const body = result.rows.map((r) => r.map(esc).join(",")).join("\n");
  return `${head}\n${body}`;
}

export function Query({ dtxsid }: StepProps) {
  const dbRef = useRef<AsyncDuckDB | null>(null);
  const startedRef = useRef(false);
  const [status, setStatus] = useState<string>("idle");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [schema, setSchema] = useState<SchemaTable[]>([]);

  const [mode, setMode] = useState<Mode>("sql");
  const [sql, setSql] = useState<string>(EXAMPLE_QUERIES[0].sql);
  const [running, setRunning] = useState(false);
  const [queryError, setQueryError] = useState<string | null>(null);
  const [result, setResult] = useState<QueryResult | null>(null);

  // One-time: spin up duckdb-wasm and load the session's Parquet into native
  // tables. Held in a ref so re-renders don't re-instantiate.
  useEffect(() => {
    if (!dtxsid) {
      setLoadError("No session selected — pick a session in data-prep first.");
      return;
    }
    if (startedRef.current) return;
    startedRef.current = true;

    let cancelled = false;
    (async () => {
      try {
        setStatus("starting duckdb-wasm…");
        const db = await makeDuckDB();
        if (cancelled) return;
        setStatus("loading session tables…");
        await loadSessionParquet(db, dtxsid);
        if (cancelled) return;
        const sch = await getSchema(db);
        if (cancelled) return;
        dbRef.current = db;
        setSchema(sch);
        setStatus("ready");
      } catch (e) {
        if (!cancelled) {
          setLoadError(e instanceof Error ? e.message : String(e));
          setStatus("failed");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [dtxsid]);

  async function runSql(text: string) {
    const db = dbRef.current;
    if (!db || running) return;
    setRunning(true);
    setQueryError(null);
    try {
      const r = await runQuery(db, text, MAX_ROWS);
      setResult(r);
    } catch (e) {
      setQueryError(e instanceof Error ? e.message : String(e));
      setResult(null);
    } finally {
      setRunning(false);
    }
  }

  function run() {
    void runSql(sql);
  }

  // The builder generates SQL; run it AND drop it into the editor so the user can
  // switch to SQL mode and tweak it (the escape hatch).
  function runFromBuilder(generated: string) {
    setSql(generated);
    void runSql(generated);
  }

  // A report-gallery card "open in console": load its SQL into the editor, switch
  // to SQL mode, and run it — so the user can iterate on a report's assembly query.
  function openInConsole(generated: string) {
    setSql(generated);
    setMode("sql");
    void runSql(generated);
  }

  function onEditorKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Cmd/Ctrl+Enter runs the query.
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      void run();
    }
  }

  function downloadCsv() {
    if (!result) return;
    const blob = new Blob([toCsv(result)], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${dtxsid || "query"}-result.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const ready = status === "ready";

  return (
    <div className="panel query-console">
      <div className="query-head">
        <h2>Query console</h2>
        {ready && (
          <div className="mode-toggle">
            <button
              className={mode === "sql" ? "active" : ""}
              onClick={() => setMode("sql")}
            >
              SQL
            </button>
            <button
              className={mode === "builder" ? "active" : ""}
              onClick={() => setMode("builder")}
            >
              Visual builder
            </button>
            <button
              className={mode === "report" ? "active" : ""}
              onClick={() => setMode("report")}
            >
              Report data
            </button>
          </div>
        )}
      </div>
      <p className="help">
        Ad-hoc SQL over this session's data — {dtxsid || "no session"} — running
        entirely in your browser (DuckDB-WASM).{" "}
        {mode === "sql"
          ? "Cmd/Ctrl+Enter to run."
          : mode === "builder"
          ? "Add tables, connect their join handles, tick columns, then run."
          : "The data-assembly query behind each report table and chart."}
      </p>

      <ErrorBox error={loadError} />

      {!ready && !loadError && (
        <p className="muted">
          <Spinner label={status} />
        </p>
      )}

      {ready && mode === "builder" && (
        <QueryBuilder schema={schema} onRun={runFromBuilder} running={running} />
      )}

      {ready && mode === "report" && dbRef.current && (
        <ReportGallery db={dbRef.current} onOpenInConsole={openInConsole} />
      )}

      {ready && mode === "sql" && (
        <div className="query-layout">
          <aside className="query-schema">
            <div className="query-schema-head">Tables</div>
            {schema.map((t) => (
              <details key={t.name}>
                <summary
                  onClick={(e) => {
                    // shift-click drops a SELECT for the table into the editor
                    if (e.shiftKey) {
                      e.preventDefault();
                      setSql(`SELECT * FROM ${t.name} LIMIT 100;`);
                    }
                  }}
                  title="Click to expand · Shift-click to query"
                >
                  {t.name}
                </summary>
                <ul>
                  {t.columns.map((c) => (
                    <li key={c.name}>
                      <span className="col-name">{c.name}</span>
                      <span className="col-type">{c.type}</span>
                    </li>
                  ))}
                </ul>
              </details>
            ))}
          </aside>

          <div className="query-main">
            <div className="query-examples">
              {EXAMPLE_QUERIES.map((q) => (
                <button
                  key={q.label}
                  className="chip-btn"
                  onClick={() => setSql(q.sql)}
                  title={q.sql}
                >
                  {q.label}
                </button>
              ))}
            </div>

            <textarea
              className="query-editor"
              value={sql}
              spellCheck={false}
              onChange={(e) => setSql(e.target.value)}
              onKeyDown={onEditorKey}
              rows={7}
            />

            <div className="query-actions">
              <button className="primary" onClick={run} disabled={running}>
                {running ? <Spinner label="Running…" /> : "Run (⌘/Ctrl+↵)"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Shared results — populated by the SQL editor OR the visual builder.
          Report mode's cards carry their own previews, so it's hidden there. */}
      {ready && mode !== "report" && (
        <>
          <div className="query-actions">
            <ErrorBox error={queryError} />
            {result && (
              <>
                <span className="muted">
                  {result.rowCount} row{result.rowCount === 1 ? "" : "s"}
                  {result.rowCount > result.rows.length &&
                    ` (showing first ${result.rows.length})`}
                </span>
                <button onClick={downloadCsv}>Export CSV</button>
              </>
            )}
          </div>

          {result && (
            <div className="query-results">
              <table>
                <thead>
                  <tr>
                    {result.columns.map((c) => (
                      <th key={c}>{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map((row, i) => (
                    <tr key={i}>
                      {row.map((v, j) => (
                        <td
                          key={j}
                          className={typeof v === "number" ? "num" : undefined}
                        >
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
              {result.rows.length === 0 && <p className="muted">No rows.</p>}
            </div>
          )}
        </>
      )}
    </div>
  );
}
