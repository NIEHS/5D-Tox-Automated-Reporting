# CEBS data packages: NIEHS 5-day biological potency reports

- `CHRONOLOGY.md`: how the packages and analysis methods evolved (start here)
- `<report>/MANIFEST.md`: per-package summary (key facts, package issues, file-by-file contents)
- `<report>/_characterization.json`, `_facts.json`: machine-readable extraction; `_bm2json/` holds .bm2 → JSON conversions; `_unzipped/` holds extracted zips
- `pages.json`: parsed CEBS listings; `jobs.tsv` / `missing.tsv`: download list and what is still outstanding
- Tooling: `characterize.py` (per-file extraction, content-based type detection), `facts.py`, `digest.py`, `manifest.py`, `bm2json.sh`, `dl.sh` (resumable: re-run to fetch `missing.tsv`)
- The originally supplied PFHxSAm package is characterised in `../given-2026/`
- Raw data (~7 GB) is gitignored; only the summaries, tooling, `pages.json`, `jobs.tsv` and `findings.json` are tracked. Re-fetch with `dl.sh`.
