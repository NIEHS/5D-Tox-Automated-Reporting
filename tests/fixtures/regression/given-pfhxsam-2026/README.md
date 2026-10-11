# Given PFHxSAm package — regression fixture (NOT a reference)

A session snapshot (copied to `sessions/DTXSID50469320` by the `given_pfhxsam`
fixture in `tests/conftest.py`) built from the PFHxSAm package originally
supplied to this project (`PFHxSAm.zip`, 2026-03-02).  Until 2026-10-06 it lived
at `tests/fixtures/golden/DTXSID50469320` and was paired with the published
NIEHS Report 10 (NBK589955) as its "reference report".  That pairing was wrong:

- The `.bm2` projects and `*_No0.txt` matrices are a **2026 re-analysis** of the
  NIEHS-10 study (BMDExpress 3.20.0156, February 2026 DTT method: zero-count
  probes removed → Williams → curve-fit prefilter 1.581 SD → ToxicR model
  averaging, BMR 25% RD; apical model averaging at 1 SD, clinical chemistry at
  25% RD) — see `assets/given-2026/MANIFEST.md`.
- NBK589955 was produced by a different analysis (apical: modified EPA BMDS
  2.7; genomics: BMDExpress 2.30 on all 2,654 probes, Williams + fold 1.5,
  lowest-AIC models, BMR 1 SD).

So BMD and genomics results from this fixture cannot be checked against the
published report.  The Individual Animal workbooks in `files/` are the CEBS
workbooks (byte-identical); the truth CSVs in `_originals/` were derived from
them without the Key sheet, so they carry no units.

Use it for: the workflow plumbing (upload → validate → integrate → routes),
value provenance (xlsx ↔ derived CSV), and regression of the given package.
For conformance to a published report use `tests/fixtures/reference/`.

`PFHxSAm.zip` is the package as supplied (it includes a copy of NBK589955).
