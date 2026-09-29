// Pre-configured "visual queries" — one per report table/chart — that document
// how each report artifact's data is ASSEMBLED from the session's canonical
// tables. This is the report's data lineage made explicit: every card names a
// report output and shows the query (tables + joins + rules) that produces it.
//
// The SQL is validated against the reference session and encodes the report's
// real assembly rules, which are NOT obvious from the schema alone:
//   - apical dose-response tables aggregate per (endpoint, sex, dose) over
//     CORE ANIMALS only (biosampling animals are excluded from the summary N);
//   - Hormones subjects carry selection='Unknown', so they are not Core-filtered;
//   - gene-set / gene "top 10" tables are a per-(organ,sex) window rank by BMD;
//   - the apical BMD summary reads the fitted results in apical_result.
//
// `tables` drives the little lineage graph on each card (nodes + the joins between
// them); `sql` is the authoritative, runnable query.

export interface ReportQuery {
  id: string;
  title: string; // the report artifact this drives
  section: "Apical tables" | "BMD summary" | "Genomics tables" | "Genomics charts" | "Front matter";
  description: string; // what the query assembles + the rule it encodes
  tables: string[]; // tables involved (nodes in the card's lineage graph)
  sql: string;
}

// The apical dose-response tables share one shape; generate them per platform.
function doseResponse(
  id: string,
  title: string,
  platform: string,
  coreOnly: boolean,
  decimals = 2
): ReportQuery {
  const sel = coreOnly ? "\n  AND s.selection = 'Core Animals'" : "";
  return {
    id,
    title,
    section: "Apical tables",
    description: coreOnly
      ? `Per (endpoint, sex, dose) mean + N over Core Animals for the ${platform} platform — the dose-response summary table.`
      : `Per (endpoint, sex, dose) mean + N for the ${platform} platform (this platform's animals are not Core/Biosampling split).`,
    tables: ["measurement", "subject"],
    sql: `SELECT m.endpoint, s.sex, s.dose,
       count(*) AS n,
       round(avg(m.value_num), ${decimals}) AS mean
FROM measurement m
JOIN subject s ON m.subject_id = s.subject_id
WHERE m.platform = '${platform}'${sel}
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3;`,
  };
}

export const REPORT_QUERIES: ReportQuery[] = [
  // --- Front matter ---
  {
    id: "sample-counts",
    title: "Table 1 · Sample Counts",
    section: "Front matter",
    description:
      "Animal N per (platform, sex, dose) over Core Animals — the sample-counts table on the methods page.",
    tables: ["subject"],
    sql: `SELECT platform, sex, dose, count(*) AS n
FROM subject
WHERE selection = 'Core Animals'
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3;`,
  },

  // --- Apical dose-response tables ---
  doseResponse("t-body-weight", "Table 2 · Body Weights", "Body Weight", true),
  doseResponse("t-organ-weight", "Table 3 · Organ Weights", "Organ Weight", true, 3),
  doseResponse("t-clin-chem", "Table 4 · Clinical Chemistry", "Clinical Chemistry", true),
  doseResponse("t-hematology", "Table 5 · Hematology", "Hematology", true),
  doseResponse("t-hormones", "Table 6 · Hormones", "Hormones", false),
  doseResponse("t-tissue-conc", "Table 7 · Plasma Concentration", "Tissue Concentration", false, 3),

  // --- BMD summary ---
  {
    id: "apical-bmd-summary",
    title: "Table 8 · Apical BMD Summary",
    section: "BMD summary",
    description:
      "Fitted BMD / BMDL / LOEL / NOEL per responsive apical endpoint, sorted by potency — the apical benchmark-dose summary.",
    tables: ["apical_result"],
    sql: `SELECT platform, sex, endpoint,
       bmd_num AS bmd, bmdl_num AS bmdl,
       loel, noel, direction, model_name
FROM apical_result
WHERE bmd_num IS NOT NULL
ORDER BY bmd_num;`,
  },

  // --- Genomics tables ---
  {
    id: "gene-set-bmd",
    title: "Tables 9–10 · Gene-Set BMD (per organ)",
    section: "Genomics tables",
    description:
      "Top 10 GO gene sets by BMD within each (organ, sex) — the gene-set benchmark-dose tables. Rank is a window over the cutoff-agnostic superset.",
    tables: ["gene_set"],
    sql: `SELECT organ, sex, go_id, go_term, bmd, n_genes, n_genes_with_bmd
FROM gene_set
QUALIFY row_number() OVER (PARTITION BY organ, sex ORDER BY bmd) <= 10
ORDER BY organ, sex, bmd;`,
  },
  {
    id: "gene-bmd",
    title: "Tables 11–12 · Gene BMD (per organ)",
    section: "Genomics tables",
    description:
      "Top 10 genes by potency within each (organ, sex) — the per-gene benchmark-dose tables. `rank` is the stored top-N position.",
    tables: ["gene"],
    sql: `SELECT organ, sex, rank, gene_symbol, bmd, bmdl, fold_change, r_squared
FROM gene
WHERE rank <= 10
ORDER BY organ, sex, rank;`,
  },
  {
    id: "gene-set-members",
    title: "Gene-set membership (interpretation)",
    section: "Genomics tables",
    description:
      "Which genes belong to each GO gene set (per organ × sex) — the join that backs the gene-set interpretation prose.",
    tables: ["gene_set", "gene_set_gene"],
    sql: `SELECT gs.organ, gs.sex, gs.go_term, gsg.gene_symbol
FROM gene_set gs
JOIN gene_set_gene gsg
  ON gs.go_id = gsg.go_id AND gs.organ = gsg.organ AND gs.sex = gsg.sex
ORDER BY gs.organ, gs.sex, gs.go_term
LIMIT 500;`,
  },

  // --- Genomics charts ---
  {
    id: "gene-scatter-data",
    title: "Gene scatter chart data (per organ × sex)",
    section: "Genomics charts",
    description:
      "Per-gene BMD vs fold-change (with R²) — the point cloud behind the genomics gene scatter figures.",
    tables: ["gene"],
    sql: `SELECT organ, sex, gene_symbol, bmd, fold_change, r_squared
FROM gene
WHERE bmd IS NOT NULL
ORDER BY organ, sex, bmd;`,
  },
];
