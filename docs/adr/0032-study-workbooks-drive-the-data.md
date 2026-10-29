# 0032: The study workbooks drive the data

- **Status:** Accepted (2026-10-28).
- **Deciders:** Dan Svoboda
- **Settles:** for the fields the study workbooks record, the open questions of
  [ADR-0019](0019-metadata-vocabulary-policy.md) (authority order, conflict
  behaviour); completes [ADR-0017](0017-content-provenance-data-classification.md)
  (the xlsx is the anchor).
- **Related:**
  - bmdx-pipe: `study_workbook` (the reader), `study_structure` (the study and
    the check), `sample_sheet` (genomic samples → animals),
    `pool_integrator.study_workbook_to_pool_files`,
    `experiment_metadata.describe_from_structure`;
  - rlm-bmdx: `pipeline/pool_fingerprints.py`, `pipeline/value_validation.py`,
    `workflow/steps.py` (`validate_step`), `pipeline/study_design.py`,
    `safeguards/inputs.py` (`facts_contradict_workbook`),
    `tooling/cebs_to_pool.py`.

## Context

An NTP study workbook (`C20022-01_Individual_Animal_Body_Weight_Data.xlsx`: a
*Key to Column Labels* sheet and a *Data* sheet) is the study team's own record
of one platform: every animal with its dose, sex and group, every observation,
and in its Key sheet the study's number, title, units and dose unit. The other
files a study arrives with are derived from it: the truth CSVs (its Data sheet
split by sex), the BMDExpress pivots, the BMDExpress projects (`.bm2`), the
genomic samples.

ADR-0017 and ADR-0019 said the workbook is the anchor and that metadata is
read from the data before anything is inferred. In practice it was half-wired:

- **Four parsers.** The Data sheet was read in four places. Some read columns
  by position, which misread the male-only Tgx layout (RR-8, NIEHS-06: no Sex
  or Selection column) and the 2025 layout (NIEHS-12, 13: "Study Number", no
  Sex column). The sexes came out as body weights.
- **Workbooks did not stand alone.** The per-animal sidecars (core and
  biosampling animals, study days, terminal flags, units) were written only
  from a truth CSV. A study supplied as workbooks lost its attrition
  footnotes and its core-only statistics.
- **Workbooks ranked last.** Integration preferred `.bm2` > txt/csv > xlsx. The
  roster check used the union of every file's animals: no file had roster
  authority.
- **The language model came first for metadata.** `experimentDescription`
  (sex, species, strain, route) was the model's, and a stated design
  overwrote every experiment.
- **Published builds had no workbooks.** `cebs_to_pool` turned them into CSVs
  first.

The maintainer (2026-10-28): the spreadsheets are primary for metadata, and
they drive the structure of the rest of the data.

## Decision

**The study workbooks are the study's record. Everything else is derived from
them or checked against them.**

1. **One reader.** `read_study_workbook` reads a workbook once, every column
   by name. It fills a missing Sex column from the title, and says so.
2. **The workbook writes the pool's files.** At validation, a study workbook is
   converted into its platform's pivot and sidecar per sex (or, for clinical
   observations, a CSV per sex). This is the same code a truth CSV goes
   through, so the outputs are byte-identical. Any other source of that
   platform is set aside in `_originals/`. A set-aside CSV must agree with the
   workbook value by value (`pipeline.value_validation`); a divergence is an
   error. A derived file records its workbook (`derived_from`), so a pivot
   that lacks a group with no values (NIEHS-05's high dose died before its
   samples) is never mistaken for a lossy "inferred" file. The workbook
   itself is never merged: a platform with only its workbook stops
   integration.
3. **The study structure.** The workbooks together give:
   - the study number, title and dose unit;
   - the design the title states (species, strain, route, duration);
   - the dose groups and sexes;
   - every animal with its sex, dose and group;
   - per platform, its endpoints, units and days;
   - with the sample sheet, which animal each genomic sample came from.

   The workbooks must agree with each other. The structure is kept in the
   validation report and in `integrated.json` (`_meta.study_structure`).
4. **Every file is checked against it.** Each of these is an error:
   - an animal the study doesn't have;
   - an animal at another dose or of another sex than the workbooks give;
   - a dose group or sex the study doesn't have;
   - an endpoint the platform's workbook doesn't record;
   - a genomic sample at another dose or sex than its animal.

   An animal a file lacks is not a contradiction (biosampling animals, early
   deaths). A genomic sample that can't be traced to an animal is a warning:
   it is reported, never guessed.
5. **Metadata: the workbooks first.** Integration states what the workbooks
   record first: the design, each experiment's sex (from its animals), and a
   genomic experiment's organ (from its samples' tissue). The model infers
   only what is left. A person's approval and a stated design are laid over
   the rest, never over a workbook field. The safeguards refuse a statement
   that contradicts the workbooks (`facts_contradict_workbook`). Each field's
   source is kept in `_meta.metadata_provenance`.
6. **Published builds import the workbooks.** `cebs_to_pool` copies a standard
   workbook as published. It writes other layouts (database export, lab
   results, molar doses) as standard workbooks, the conversion noted on a
   "Conversion" sheet. It also copies the package's sample sheet. `--csv` keeps
   the CSV route for a study supplied that way.

A study with no workbook keeps the earlier behaviour: CSV-derived data, with
the `unverified_derived_data` warning.

## Consequences

- **The checks found a real mismatch.** The given PFHxSAm package's inferred
  hormone files name an endpoint "Triiodiodothyronine"; the workbook says
  "Triiodothyronine". That package now fails validation and is no longer the
  test reference: the workflow tests use NIEHS-10 (`niehs10` fixture).
- **The published tables follow the roster.** NIEHS-10's clinical chemistry,
  hematology and hormone tables now carry the 333 and 1,000 mg/kg columns
  ("–": every animal died), as the published Tables 4–6 do. The narrative
  reads a finding's direction from the highest dose that has values; before,
  an empty top dose turned every such finding to "increased" (which had
  already misstated NIEHS-05's cholinesterase, 285 → 104, as increased).
- **The 12 published books, rebuilt (2026-10-28).** Against a build of the
  same books from the code before this change, the integrated experiments
  and every table are the same, except NIEHS-10's added columns above.
  NIEHS-05's statistics gain the 1,222 mg/kg column its table already had.
  The other differences are the model's prose (Methods is regenerated when
  its endpoint list comes out in another order) and the order of
  experiments (male before female).
- **Every package checks clean.** On the 12 CEBS packages, the workbook route
  gives the same pivots and sidecars as the CSV route, and no file contradicts
  its study. Every genomic sample of NIEHS-02 … 10 traces to an animal of the
  right dose and sex, except two NIEHS-02 arrays the sample list omits. RR-8,
  NIEHS-12 and 13 publish no sample sheet in a readable form, so their samples
  are reported as untraced.
- **How each animal left the study** (2026-10-29). NIEHS-12 and 13's
  *Removal Reasons* workbooks give each animal's disposition and removal day.
  They have no platform: `cebs_to_pool` copies them, and the study structure
  puts the two facts on each animal (`animals[id].disposition`,
  `removal_day`). With them (`common.dispositions`):
  - a body weight attrition footnote says what the workbook says: "One female
    mouse was euthanized moribund on study day 4", not "was found dead";
  - the Animal Condition paragraph takes its early removals from them, in the
    same words, and reports the internal-dose animals removed off schedule
    first, as the reports do ("One internal concentration assessment animal
    in the 800 ppm group was found dead on study day 4"). Before, NIEHS-13
    said nothing about those deaths.

  A study without the workbook still infers its early removals from the body
  weight study days.
