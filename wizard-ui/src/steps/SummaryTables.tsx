import {
  ApicalBmdRow,
  GenomicsSection,
  ProcessPayload,
  Section,
} from "../api";

// Dose keys in a row's `values`/`n` maps: integer string when whole, else float.
function doseKey(d: number): string {
  return Number.isInteger(d) ? String(d) : String(d);
}

function fmtNum(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") return Number.isFinite(v) ? v.toFixed(2) : "—";
  return String(v);
}

// --- A. Per-platform apical dose-response tables (from payload.sections) ---
function ApicalSectionTable({ section, doseUnit }: { section: Section; doseUnit: string }) {
  const tj = section.tables_json || {};
  const sexes = Object.keys(tj).filter((s) => (tj[s] || []).length > 0);
  if (sexes.length === 0) return null;

  return (
    <div className="summary-table">
      <h3>{section.caption || section.title || section.platform}</h3>
      {sexes.map((sex) => {
        const rows = tj[sex];
        const doses = rows[0]?.doses || [];
        return (
          <table key={sex}>
            <thead>
              <tr className="sex-header">
                <td colSpan={doses.length + 1}>{sex}</td>
              </tr>
              <tr>
                <th>{section.first_col_header || "Endpoint"}</th>
                {doses.map((d) => (
                  <th key={d}>
                    {d} {doseUnit}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i} className={row.emphasize ? "emphasize" : undefined}>
                  <td>
                    {row.label}
                    {row.trend_marker ? ` ${row.trend_marker}` : ""}
                  </td>
                  {doses.map((d) => (
                    <td key={d} className="num">
                      {row.values?.[doseKey(d)] ?? "—"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        );
      })}
    </div>
  );
}

// --- B/C. Apical BMD Summary (grouped by sex) ---
function ApicalBmdSummary({
  rows,
  title,
  withModel,
}: {
  rows: ApicalBmdRow[];
  title: string;
  withModel: boolean;
}) {
  if (!rows || rows.length === 0) return null;
  const bySex = new Map<string, ApicalBmdRow[]>();
  for (const r of rows) {
    const s = r.sex || "—";
    if (!bySex.has(s)) bySex.set(s, []);
    bySex.get(s)!.push(r);
  }
  const cols = withModel ? 7 : 6;
  return (
    <div className="summary-table">
      <h3>{title}</h3>
      <table>
        <thead>
          <tr>
            <th>Endpoint</th>
            <th>BMD</th>
            <th>BMDL</th>
            {withModel && <th>Model</th>}
            <th>LOEL</th>
            <th>NOEL</th>
            <th>Direction</th>
          </tr>
        </thead>
        <tbody>
          {[...bySex.entries()].map(([sex, srows]) => (
            <SexGroup key={sex} sex={sex} cols={cols}>
              {srows.map((r, i) => (
                <tr key={i}>
                  <td>{r.endpoint}</td>
                  <td className="num">{r.bmd ?? "—"}</td>
                  <td className="num">{r.bmdl ?? "—"}</td>
                  {withModel && <td>{r.model_name || "—"}</td>}
                  <td className="num">{fmtNum(r.loel)}</td>
                  <td className="num">{fmtNum(r.noel)}</td>
                  <td>{r.direction || "—"}</td>
                </tr>
              ))}
            </SexGroup>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SexGroup({
  sex,
  cols,
  children,
}: {
  sex: string;
  cols: number;
  children: React.ReactNode;
}) {
  return (
    <>
      <tr className="sex-header">
        <td colSpan={cols}>{sex}</td>
      </tr>
      {children}
    </>
  );
}

// --- D/E. Genomics gene-set + top-genes tables (per organ/sex section) ---
function GenomicsTables({
  section,
  statLabels,
}: {
  section: GenomicsSection;
  statLabels: Record<string, string>;
}) {
  const gsByStat = section.gene_sets_by_stat || {};
  const stat = Object.keys(gsByStat)[0];
  const geneSets = stat ? gsByStat[stat] : [];
  const label = (stat && statLabels[stat]) || stat || "";
  const topGenes = section.top_genes || [];
  const heading = `${section.organ} · ${section.sex}`;

  return (
    <div className="summary-table">
      <h3>{heading}</h3>
      {geneSets.length > 0 && (
        <>
          <p className="caption">Gene-set BMD ({label})</p>
          <table>
            <thead>
              <tr>
                <th>GO Term</th>
                <th>GO ID</th>
                <th>BMD</th>
                <th>BMDL</th>
                <th># Genes</th>
                <th>↑ / ↓</th>
              </tr>
            </thead>
            <tbody>
              {geneSets.map((g, i) => (
                <tr key={i}>
                  <td>{g.go_term}</td>
                  <td>
                    <code>{g.go_id}</code>
                  </td>
                  <td className="num">{fmtNum(g.bmd)}</td>
                  <td className="num">{fmtNum(g.bmdl)}</td>
                  <td className="num">{g.n_genes}</td>
                  <td className="num">
                    {g.n_up ?? 0} / {g.n_down ?? 0}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {topGenes.length > 0 && (
        <>
          <p className="caption">Top genes</p>
          <table>
            <thead>
              <tr>
                <th>Gene</th>
                <th>BMD</th>
                <th>BMDL</th>
                <th>Fold change</th>
                <th>Direction</th>
              </tr>
            </thead>
            <tbody>
              {topGenes.map((g, i) => (
                <tr key={i}>
                  <td>{g.gene_symbol}</td>
                  <td className="num">{fmtNum(g.bmd)}</td>
                  <td className="num">{fmtNum(g.bmdl)}</td>
                  <td className="num">{fmtNum(g.fold_change)}</td>
                  <td>{g.direction || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

export function SummaryTables({
  payload,
  doseUnit,
}: {
  payload: ProcessPayload;
  doseUnit: string;
}) {
  const sections = payload.sections || [];
  const bmdSummary = payload.apical_bmd_summary || [];
  const bmdSummaryBmds = payload.apical_bmd_summary_bmds || [];
  const statLabels = payload.bmd_stat_labels || {};
  const genomics = payload.genomics_sections || {};

  return (
    <div>
      <h3 style={{ marginTop: "2rem" }}>Summary statistics</h3>

      {sections.map((s, i) => (
        <ApicalSectionTable key={i} section={s} doseUnit={doseUnit} />
      ))}

      <ApicalBmdSummary
        rows={bmdSummary}
        title="Apical BMD summary (BMDExpress)"
        withModel={false}
      />
      <ApicalBmdSummary
        rows={bmdSummaryBmds}
        title="Apical BMD summary (BMDS / pybmds)"
        withModel={true}
      />

      {Object.keys(genomics).length > 0 && (
        <>
          <h3 style={{ marginTop: "2rem" }}>Genomics tables</h3>
          {Object.entries(genomics).map(([key, sec]) => (
            <GenomicsTables key={key} section={sec} statLabels={statLabels} />
          ))}
        </>
      )}
    </div>
  );
}
