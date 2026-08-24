import { useEffect, useRef, useState } from "react";
// xterm's stylesheet — the @duckdb/duckdb-wasm-shell package bundles the xterm
// JS but NOT its CSS. Without this the terminal has no layout: it collapses to a
// single cell in the corner (with the raw <textarea> resize grip showing). This
// one import is what actually makes the shell render at full size.
import "xterm/css/xterm.css";
import { StepProps, ErrorBox, Spinner } from "./shared";
import { makeDuckDB, loadSessionParquet, shellModuleUrl } from "../duckdb";

// The DuckDB shell (ADR-0016 Phase C): the real duckdb.org/shell xterm terminal,
// embedded in-app and running ENTIRELY IN THE BROWSER against the session's data.
// The session's per-table Parquet is fetched once and registered as views, then
// the shell's embed() takes over — every query after that is local wasm, no
// server round-trip.
export function Query({ dtxsid }: StepProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [status, setStatus] = useState<string>("idle");
  const [error, setError] = useState<string | null>(null);
  const [tables, setTables] = useState<string[]>([]);
  // Guard against double-embed under React 18 StrictMode's dev double-invoke.
  const startedRef = useRef(false);

  useEffect(() => {
    if (!dtxsid) {
      setError("No session selected — pick a session in data-prep first.");
      return;
    }
    if (startedRef.current) return;
    startedRef.current = true;

    const container = containerRef.current;
    if (!container) return;

    let cancelled = false;
    let resizeObserver: ResizeObserver | null = null;

    // The shell's xterm FitAddon fits ONCE, at embed(), to the container's size
    // and never re-fits (it registers no ResizeObserver / resize listener). So
    // if we embed before the container has laid out, xterm collapses to a single
    // cell in the corner. Wait until the container reports a real size first.
    const waitForLayout = () =>
      new Promise<void>((resolve) => {
        const check = () => {
          if (cancelled) return resolve();
          if (container.clientWidth > 50 && container.clientHeight > 50) {
            resolve();
          } else {
            requestAnimationFrame(check);
          }
        };
        check();
      });

    (async () => {
      try {
        setStatus("loading shell…");
        // The shell module is dynamically imported so its (large) bundle only
        // loads when the user opens this step.
        const shell = await import("@duckdb/duckdb-wasm-shell");

        await waitForLayout();
        if (cancelled) return;

        setStatus("starting duckdb-wasm…");
        await shell.embed({
          shellModule: shellModuleUrl,
          container,
          backgroundColor: "#1e1e1e",
          // resolveDatabase is OUR hook: build the DB offline, load the session's
          // Parquet, and hand the ready DB to the shell.
          resolveDatabase: async (progress) => {
            const db = await makeDuckDB(progress);
            if (cancelled) return db;
            setStatus("loading session tables…");
            const loaded = await loadSessionParquet(db, dtxsid);
            if (!cancelled) {
              setTables(loaded);
              setStatus("ready");
            }
            // Debug handle so an automated check can query the same in-browser DB
            // the shell uses (the xterm display is hard to assert against).
            (window as unknown as { __wizardDb?: unknown }).__wizardDb = db;
            return db;
          },
        });

        // The shell wires its re-fit to `container.onresize` (see shell.mjs:
        // `props.container.onresize = runtime.resizeHandler`). But a plain <div>
        // never fires resize events — only window/body do — so that handler is
        // effectively dead and the terminal keeps its embed-time (possibly
        // collapsed) size. Bridge it: observe the container with a ResizeObserver
        // and invoke its onresize handler ourselves whenever the box changes.
        // Fire once now too, so the terminal fits to the settled layout.
        if (!cancelled && "ResizeObserver" in window) {
          const fire = () => {
            const h = (container as HTMLDivElement & { onresize?: unknown })
              .onresize;
            if (typeof h === "function") {
              (h as (e?: unknown) => void)(new Event("resize"));
            }
          };
          fire();
          resizeObserver = new ResizeObserver(fire);
          resizeObserver.observe(container);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
          setStatus("failed");
        }
      }
    })();

    return () => {
      cancelled = true;
      if (resizeObserver) resizeObserver.disconnect();
    };
  }, [dtxsid]);

  return (
    <div className="step">
      <h2>Query console</h2>
      <p className="muted">
        A DuckDB SQL shell running in your browser against this session's data —{" "}
        {dtxsid || "no session"}. Try{" "}
        <code>SELECT * FROM measurement LIMIT 10;</code> or{" "}
        <code>SELECT organ, sex, count(*) FROM gene_set GROUP BY 1, 2;</code>
      </p>

      <ErrorBox error={error} />

      {status !== "ready" && !error && (
        <p className="muted">
          <Spinner label={status} />
        </p>
      )}

      {tables.length > 0 && (
        <p className="muted" style={{ fontSize: "0.78rem" }}>
          Loaded tables: {tables.join(", ")}
        </p>
      )}

      <div
        ref={containerRef}
        className="duckdb-shell"
        style={{
          height: "60vh",
          minHeight: 360,
          border: "1px solid var(--line, #333)",
          borderRadius: 6,
          overflow: "hidden",
          marginTop: "0.5rem",
        }}
      />
    </div>
  );
}
