# 0037: The values left out of the apical analysis are data

- **Status:** Accepted (2026-11-20).
- **Deciders:** Dan Svoboda
- **Related:**
  - ADR-0032 (study workbooks drive the data), ADR-0035 (study parameters are
    recorded or stated), ADR-0036 (the report states the computation that ran);
  - `packages/bmdx-pipe/src/bmdx_pipe/excluded_values.py` (the file, the mark,
    the reasons), `pool_integrator.py` (`long_rows_to_pivot`: where a named
    value is left out);
  - `pipeline/pool_fingerprints.py` (every derivation reads the pool's
    excluded-values files), `pipeline/excluded_values.py` (the file check's
    pass), `workflow/steps.py` (`validate_step`);
  - `tables/table_builder_common.py` (`excluded_by_endpoint`,
    `note_excluded_cell`), the organ weight, clinical pathology and body weight
    builders; `narrative/methods_prompt.py` (`_excluded_values_guideline`);
  - `pipeline/processing_helpers.py` (`_build_apical_bmd_summary`: body weights
    by study day);
  - `templates/studies/DTXSID6020430/NIEHS-12_Excluded_Values_*.csv`;
  - `packages/bmdx-pipe/tests/test_excluded_values.py`,
    `tests/unit/test_excluded_values.py`.

## Context

The rebuilt NIEHS-12 printed two benchmark doses that differ from the book,
and both trace to a single value the book left out:

| Endpoint | Rebuilt | Published | The value |
|---|---|---|---|
| Mouse relative right kidney weight | 224.9 (130.6) | 161.5 (82.3) | control animal 4, right kidney 0.06 g (the other nine: 0.12 to 0.15 g) |
| Rat bile salts/acids | 141.0 (47.1) | 143.8 (45.9) | 10 ppm animal 202, recorded as 0 |

The book says so on the tables: "n = 9. One value was excluded as an outlier"
(Table 3), and "9.3 ± 3.0 (4)" for a group of five (Table 4). Refitting
without each value gives the published numbers.

The published method is not a rule: "Prior to analysis, values identified by
the outlier test of Dixon and Massey were examined by NIEHS staff. Values from
animals suspected of illness from causes other than experimental exposure and
values that the laboratory indicated as inadequate because of measurement
problems were eliminated from the analysis." The test only names candidates.
Applied as a rule at α = 0.01 it also removes two rat control values the book
kept (bile salts/acids, glucose), and no level of the test reproduces what the
book left out. The method profile already said "not automated"
(`apical.statistics.outliers: null`), and there was no way to state an
exclusion.

A person's judgment cannot be recomputed. The two things that judgment rested
on can be recorded: the laboratory's mark that a measurement was inadequate,
and the suspicion of an illness unrelated to exposure. With those as data, the
rule is deterministic.

## Decision

1. **Which values were left out is data the package carries.** A pool may hold
   an excluded-values file: a CSV with the columns `Animal ID`, `Endpoint`,
   `Observation Day`, `Reason`, `Note`. `Endpoint` is the column label of the
   study workbook's Data sheet. `Reason` is one of:
   - `measurement problem`: the laboratory indicated the measurement as
     inadequate;
   - `unrelated illness`: the animal was suspected of illness from causes other
     than exposure;
   - `as published`: for a rebuilt published report, the book left the value
     out and the package does not say which of the two it was. The `Note` must
     say where the book states it.

   Like every other fact about a study it is changed by replacing a file, not
   by editing in the application.

2. **The rule: a named value is left out, and the table says so.** The
   conversion of a study workbook (and of a long-format CSV) leaves the named
   value out of the pivot, so the statistics, the derived endpoints (relative
   weights, globulin, body weight gain) and the benchmark dose inputs are
   without it. The observation in the sidecar keeps no `value` and carries the
   mark `excluded` (the value, the reason, the note, the file). Every reader
   of a sidecar therefore treats it as a missing value; the readers that say
   why read the mark.

3. **Nothing is applied in part or by a guess.** The file check (`validate`)
   refuses, as errors that block combining the files, a row that does not read
   (no animal, no endpoint, an unknown reason, a missing note, a repeated row)
   and a row that names a value the derived files do not hold. Values of the
   tested apical platforms can be named (body weight, organ weight, clinical
   chemistry, hematology, hormones); internal dose values keep the method's own
   outlier rule (`internal_dose.outliers`).

4. **The files are derived from the workbooks and the excluded-values files
   together.** Every scan of the pool derives each workbook's files again with
   the excluded values then in the pool, whichever arrived first; the file
   check always scans. The file's rows are part of its fingerprint, so a
   dataset built before the file was added, or before a row changed, reads
   "out of date" (`workflow.integration_basis`).

5. **The report states it** (ADR-0036).
   - The affected cell is marked, and the table's last note reads as the book's
     does: "n = 9. One value was excluded as an outlier." For the other two
     reasons the note gives the reason. The note is printed whatever the
     definition's `table_notes: outlier_exclusions` says: that switch is for
     the exclusions a rule makes (the internal dose outlier test, which
     NIEHS-12 applies without a note).
   - The statistics paragraph of the Methods states how many values were
     eliminated, per reason, from the same marks.

6. **No outlier test decides an apical value.** `apical.statistics.outliers`
   stays `null` in every profile. A test may later be used to list candidates
   for a person to look at; it may not remove a value.

### Decided with it: body weights by study day in the BMD summary

The summary left out every body weight row except the derived gain. NIEHS-12
lists them ("Body Weight on Study Day 4" for the rats; days 2, 3 and 4 for the
mice), and no other book has a responsive study-day row that it leaves out.
Body weights by study day are now listed on the terms of every other endpoint,
named as NIEHS-12 names them. The last study day is not listed by its day: it
is the terminal body weight, which the method lists (NIEHS-02 to 06, RR-8, 12)
or leaves out (NIEHS-07 to 10).

## Consequences

- NIEHS-12 rebuilt with the two files prints the published benchmark doses for
  both endpoints and the published group means and n; its BMD summary has the
  four study-day rows.
- A package for a new study needs the file only when values were left out.
  Without it nothing is left out, and nothing says a value looks unusual: a
  list of candidates for a person to examine (the Dixon and Massey test as a
  screen) is not built.
- Other rebuilt books print exclusions too (NIEHS-06: "Liver weight from one
  animal was removed as an outlier in the 62 mg/kg group"; NIEHS-09: "One value
  for platelets in the 333 mg/kg group was excluded; it was an outlier"). Their
  files are not written yet; each needs the animal identified from the
  deposited workbook.
- The sidecar's `value` of a left-out observation is `None`. Code that needs
  the recorded value reads `excluded.value` (the value cross-check does).
- A study whose sessions were combined before this change is unaffected until
  a file is added.
