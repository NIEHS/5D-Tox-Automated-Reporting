# 0030: The BMDS-era apical engine is NTP's own package, run under Wine

- **Status:** Accepted (2026-10-12). The engine is built and checked against
  NTP's recorded runs. Under Wine (8.0, with Wine's own `msvcrt`) it does **not**
  reproduce them exactly, so its self-check keeps it off (see "Under Wine"). The
  open choice is recorded there.
- **Amends:** [ADR-0027](0027-pinned-method-profiles.md) §3 (the implementation
  registry). An implementation can now depend on the machine: it is registered,
  and it runs only where the machine can run it.
- **Deciders:** Dan Svoboda
- **Related:**
  - `pipeline/bmds27/`;
  - `tests/unit/test_bmds27_oracle.py`;
  - `tests/integration/test_bmds27_wine.py`;
  - `tooling/bmds27_oracle.py`, `tooling/bmds27_conformance.py`.

## Context

The BMDS-era reports pin `ntp-5day-2021`. These are NIEHS-02 … NIEHS-10, plus RR-8. That profile asks for
`apical.bmd.engine: bmds_2_7_high_dose_drop`, which works like this:
- EPA's BMDS 2.7 is driven by NTP's modified Python `bmds` 0.11;
- the package's rules recommend a model;
- when nothing is recommended, the highest dose is dropped and the models are re-run.

Until now that engine was a registered name with no implementation. The tool
substituted ToxicR and said so (ADR-0027 §3), and the QC marked every one of those reports as not following its published
method.

Three ways to run it were weighed:

1. **pybmds (BMDS 3).** It is not BMDS 2.7. On identical NIEHS-10 inputs, only 29–64% of
   fits agree within 2%, depending on the model, and the Exponential-M2 model has no counterpart.
2. **Rebuilding BMDS 2.7 from source.** The 2.7 sources are no longer published
   (epa.gov is unreachable from here, and the GitHub repository holds BMDS 3 only).
3. **NTP's package as deposited.** CEBS holds the same zip, byte for byte, for every
   BMDS-era report: the Python package and EPA's 32-bit Windows executables. The
   package already has a seam for running somewhere other than Windows. Its
   `monkeypatch.py` replaces only the step that runs the executable: the input
   ("dfile") goes in, the output file comes out.

## Decision

**Run NTP's package as deposited, with the executables under Wine.**

- **The package is vendored** in `pipeline/bmds27/ntp_bmds/`. It is the deposit's code
  apart from four mechanical patches listed in `PROVENANCE.md` and checked by
  `test_bmds27_vendored.py`.
- **NTP's models, dfiles, output parser, rules, recommendation and high-dose
  dropping all run unchanged.** Only the executable step is ours
  (`runner.py`). It is a session subclass with the same seam as NTP's monkeypatch,
  and it has two executors:
  - **Wine:** the real executables;
  - **replay:** NTP's recorded outputs, looked up by dfile.
- **The executables are not committed.** They are found at `BMDS27_BIN` or extracted
  from a CEBS package zip, and every file is checked against its sha256.
- **The engine certifies itself before use.** `pipeline.bmds27.available()` needs
  three things:
  - Wine;
  - the verified binaries;
  - recorded NTP runs, one per executable, re-run and parsed to the same BMD, BMDL,
    AIC and p-values.
  
  Anything less leaves the engine unavailable *with the reason*. The method resolver
  then substitutes ToxicR as before, and the stated deviation names the reason
  (e.g. "Wine is not installed"). The QC `method` error stays until the engine runs.
- **Under this engine it is the source of record for apical BMDs, not a fill.**
  - Every row the method models takes the engine's value: the recommended model's
    BMD/BMDL, or NVM when no model was recommended.
  - A row the method does not model drops any `.bm2` value, because that came from
    BMDExpress, a different method.
  - The bm2↔ToxicR overlap check does not apply.
  - The full record is kept in `sessions/<id>/bmds27_runs.json`: every model of every
    round, with dfile and output. This is the session's version of NTP's Parameter
    workbooks.
- **The dataset is built from the per-animal values at full precision:** per dose
  group, N, mean and SD (n − 1). Groups with fewer than two animals are left out
  and noted.

## Evidence

The oracle is the Parameter workbooks deposited with NIEHS-02 … NIEHS-10. They hold
173 datasets and 8,109 model runs, each with its dfile and output. They are
stored as `tests/fixtures/reference/<R>/bmds27_runs.json.xz`. With the executable
step replayed:

- **The engine reproduces every recorded run.** The dfiles are byte-identical, and so
  are the rule bins, the recommendations, the BMDs, BMDLs and AICs, and the sequence
  of dropped doses.
- **One dataset needs full-precision means.** For NIEHS-10 female TSH, the change
  from control is an exact tie after two drops. Built from the animals, it matches.

`tooling/bmds27_conformance.py` compares the sessions' own datasets with NTP's:
- **NIEHS-07 … 10:** all 113 matched datasets are identical.
- **NIEHS-02 … 06:** N, mean and SD are identical, but NTP used whole-number mg/kg
  doses (65, 129, …, 1,033, the doses the published reports print). Our sessions
  carry the unrounded conversion (64.6, …).

Which endpoints NTP modelled:
- **Trend OR any pairwise significance**, among the dose groups that were modelled.
  That is not the "trend and pairwise" that NIEHS-10's Methods text states, and not
  the profile's `all_endpoints`.
- **Body-weight endpoints follow the era:**
  - the 2018 reports modelled terminal body weight;
  - the 2021 reports modelled body weight gain.
- **Exceptions are explained by groups that were not modelled.** Where an endpoint's
  only significance is in high-dose groups that were not modelled (early deaths),
  it was not modelled.

## Under Wine (measured 2026-10-12, Wine 8.0)

All 8,109 recorded dfiles were run through the executables, and the whole engine
was run on all 173 recorded datasets:

- **Per model:** 5,757 of 8,109 runs parse to NTP's BMD, BMDL and AIC exactly.
  - Linear, Power and Exponential-M2 mostly match.
  - Hill and Exponential M3–M5 often don't.
  - NIEHS-10's 1,339 runs break down as: 878 identical; 65 different in the last
    digits; 88 under 1% apart; 269 more than 1% apart; 29 where one side computed
    a BMD/BMDL and the other failed (−999); 10 with no output.
- **Per dataset (what a report prints):**
  - 158 of 173 have the same recommended model and BMD as NTP's;
  - 3 more are within 2%;
  - 12 differ materially (for example, NIEHS-02 male absolute liver weight:
    25.8 against NTP's 60.4).

**Cause.** The cause is not floating-point precision. The executables' own MinGW
startup sets the x87 control word to 64-bit precision with `fesetenv(FE_DFL_ENV)`
→ `fninit` (0x037F). It does so on Windows too; winedbg shows 0x027F at the entry
point and 0x037F by the first `exp`.

The cause is that the executables import `exp`, `log`, `pow`, `sin` and `cos` from
`msvcrt.dll`. Under Wine these are Wine's reimplementations, not Microsoft's. The
two differ in the last bits, and the BMDS optimizers amplify that wherever the
likelihood is flat. One example is Hill on NIEHS-10 female AST. Both fits reach
the same log-likelihood (−107.726422), but Wine's run leaves `n` off its bound,
which changes the parameter count and the AIC by 2.

The self-check (`certification.json`) therefore fails on Polynomial-2, Hill and
Exponential M3/M5, and the engine stays unavailable. Processing substitutes ToxicR
and states the reason.

**Options:**
1. **Microsoft's `msvcrt.dll` under Wine.** Run with `WINEDLLOVERRIDES=msvcrt=n,b`,
   using the 32-bit copy from a Windows machine, ideally the kind NTP ran on.
   This is the only route to exact reproduction, and it has to be verified.
2. **Accept Wine's `msvcrt` as a stated deviation.** This matches NTP on 161 of 173
   datasets, against 20 of 110 published BMDs agreeing for the ToxicR substitute.
3. **Keep the ToxicR substitute.**

## Consequences

- **On a machine with Wine,** the BMDS-era reports' apical BMDs come from the method
  their reports name. The QC `method` error clears for the engine.
- **Open, recorded rather than decided here:**
  - **Eligibility.** The registry has `trend_or_pairwise`, which only the bmds27 path
    applies. `ntp-5day-2021` names `all_endpoints`. Profiles are immutable (ADR-0027
    §2), so correcting this needs a new profile and a re-pin of the 10 sessions.
    Until then the substitute rule (`trend_and_pairwise`) is applied, and the
    deviation is stated.
  - **2018-era doses.** The session dose values are not the published ones. This is a
    data-integration issue, not an engine one.
  - **RR-8 used an older rule set.** 4 of its 22 datasets differ from this package.
    Its oracle is not part of the tests.
  - **Presentation of the Low-BMD caution (Table D-1 "nonreportable")** is to be
    settled against the published tables. The QC will do that once the engine runs.
- **Image requirements:** Wine with 32-bit support. For deploy, the executables
  staged at `BMDS27_BIN`.
