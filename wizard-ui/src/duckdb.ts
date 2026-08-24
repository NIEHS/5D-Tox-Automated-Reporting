// duckdb-wasm setup for the embedded shell.
//
// Bundle serving: we DON'T use duckdb-wasm's default getJsDelivrBundles() (it
// pulls the .wasm + worker from the jsDelivr CDN). Instead we import the eh
// bundle's binary + worker with Vite's `?url`, so they are copied into the build
// and served locally under /wizard/ — the app's own JS/wasm never depends on an
// external CDN.
//
// The parquet EXTENSION is the one runtime network dependency: the eh wasm core
// does not statically include parquet, so reading a .parquet autoloads
// `parquet.duckdb_extension.wasm` from extensions.duckdb.org (allowlisted in the
// sandbox / deployment). It is fetched ONCE, during loadSessionParquet, to
// materialize the data into NATIVE tables — after that the shell queries native
// tables and needs no extension. (extensions.duckdb.org is the only DuckDB host
// besides the CDN; keep the default extension repository.)
//
// We use the `eh` (exception-handling) bundle rather than `coi`: coi needs
// SharedArrayBuffer, which requires COOP/COEP cross-origin-isolation headers on
// the server — more moving parts than this embed needs.

import * as duckdb from "@duckdb/duckdb-wasm";

// Vite copies these into the bundle and returns a local hashed URL for each.
import eh_wasm from "@duckdb/duckdb-wasm/dist/duckdb-eh.wasm?url";
import eh_worker from "@duckdb/duckdb-wasm/dist/duckdb-browser-eh.worker.js?url";

// The shell's own wasm (xterm UI runtime), served locally too.
import shell_wasm from "@duckdb/duckdb-wasm-shell/dist/shell_bg.wasm?url";

export const shellModuleUrl = shell_wasm;

// Instantiate an AsyncDuckDB from the local wasm bundle (extension autoload left
// at its default ON, so read_parquet can pull the parquet extension once).
export async function makeDuckDB(
  onProgress?: (p: duckdb.InstantiationProgress) => void
): Promise<duckdb.AsyncDuckDB> {
  const worker = new Worker(eh_worker, { type: "module" });
  const logger = new duckdb.VoidLogger();
  const db = new duckdb.AsyncDuckDB(logger, worker);
  await db.instantiate(eh_wasm, null, onProgress);
  return db;
}

// Load a session's per-table Parquet into the DB as queryable views. Each table
// is fetched from the backend (GET /api/query/{dtxsid}/parquet/{table}),
// registered as an in-wasm file, and exposed as a view of the same name. Returns
// the list of tables actually loaded.
export async function loadSessionParquet(
  db: duckdb.AsyncDuckDB,
  dtxsid: string
): Promise<string[]> {
  const listResp = await fetch(
    `/api/query/${encodeURIComponent(dtxsid)}/parquet`
  );
  if (!listResp.ok) {
    throw new Error(`parquet list failed: ${listResp.status}`);
  }
  const { tables } = (await listResp.json()) as { tables: string[] };

  const conn = await db.connect();
  try {
    for (const table of tables) {
      const resp = await fetch(
        `/api/query/${encodeURIComponent(dtxsid)}/parquet/${encodeURIComponent(
          table
        )}`
      );
      if (!resp.ok) continue; // skip a table that isn't there
      const buf = new Uint8Array(await resp.arrayBuffer());
      const fname = `${table}.parquet`;
      await db.registerFileBuffer(fname, buf);
      // Materialize into a NATIVE table (not a view over the parquet). This reads
      // the parquet once, here — so the parquet extension autoload happens during
      // load, and every subsequent shell query runs against native tables with no
      // extension and no dependency on the registered buffer sticking around.
      await conn.query(
        `CREATE OR REPLACE TABLE "${table}" AS SELECT * FROM read_parquet('${fname}')`
      );
    }
  } finally {
    await conn.close();
  }
  return tables;
}
