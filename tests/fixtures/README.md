# Test fixtures

Three kinds, kept apart so a test's oracle is never mistaken for a reference:

| directory | what it is | oracle |
|---|---|---|
| `reference/<report>/` | a subset of a **published CEBS package** (original file names): the study's raw data plus the tables NIEHS published from it.  `MANIFEST.md` says what each one is a reference for. | the published tables — conformance tests (`test_reference_*`, `test_toxicokinetics`, `test_tissue_concentration_precision`, …) |
| `regression/<name>/` | session snapshots used for workflow plumbing and regression — e.g. `given-pfhxsam-2026`, the PFHxSAm package as supplied (a 2026 re-analysis, **not** the analysis behind any published report; see its README). | our own earlier behaviour |
| `golden/` | self-snapshots (`process_integrated_payload.json`, `DTXSID70191136`) frozen from our own output. | our own earlier output |

- `reference/NIEHS-13/` — rat study 108020004, the BMDExpress 3.20 analysis
  the pipeline targets: summary tables, the apical BMD summary, and the
  genomics Top-10 GO / genes / most-potent tables (from a slim extract of the
  genomic project — `tooling/slim_genomics_extract.py`).
- `reference/NIEHS-10/` — PFHxSAm, study C20022-01: summary tables, plasma
  concentrations and half-lives, hormones.  Not a BMD/genomics reference (BMDS
  2.7 / BMDExpress 2.30).

`tests/conftest.py`: `reference_session(report, dtxsid)` builds a session from a
reference package through the real ingest path; `given_pfhxsam` copies the
regression session in as `DTXSID50469320`.
