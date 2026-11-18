# 0035: Every study parameter is recorded or stated; none is assumed

- **Status:** Accepted (2026-11-16).
- **Deciders:** Dan Svoboda
- **Supersedes:** the standard-design fallback of 2026-10-05
  (`pipeline.study_design`: `STANDARD_DESIGN`, `FALLBACK_*`, `design_or_standard`,
  `resolve_dose_unit`'s "else mg/kg"), and every `dose_unit="mg/kg"` default.
- **Related:**
  - `pipeline/study_parameters.py` (the one resolution, with provenance);
  - `pipeline/study_design.py` (the facts the experiments record; the wording);
  - `pipeline/process_integrated.py` (`_build_process_context` refuses);
  - `safeguards/inputs.py` (`require_study_parameters`, called by
    `safeguards.acts.require(..., method=True)`); `safeguards/refusals.py`
    (`study_parameters_incomplete`);
  - `workflow/engine.py` (`study_parameters`), `web_routes/pool_routes.py`
    (`/api/workflow/{dtxsid}/study-parameters`);
  - `workflow/steps.py` (`record_study_design`: merged; null withdraws);
  - `tooling/generate_report.py` (`--dose-unit` and `--design` state them);
  - `tests/unit/test_study_parameters.py`.

## Context

An independent review of `7b58a68` reproduced silent defaults in reports:
mixed ppm and mg/kg became mg/kg; a 5-day and a 28-day experiment became "five
days"; an inhalation study with no recorded unit read "by inhalation in corn
oil". The causes:

- a standard design (Sprague Dawley rats, gavage in corn oil, five days) filled
  any fact the data lacked;
- one branch handled both "none recorded" and "several recorded";
- defaults were repeated at every layer (`duration_days=5`, 23
  `dose_unit="mg/kg"` signatures, `or "mg/kg"` in the render paths);
- the route fallback followed the unit, not the recorded route.

The user decided: "we need to not have fallbacks at all. they're not
meaningful under current plans. we need to require explicit statement of
study parameters." Stated values live in one place, `study_design.json`.

## Decision

1. **The parameters.** These are the species, strain, route (and inhalation
   method), vehicle (not applicable to an inhaled study), study duration,
   dosing days, dosing schedule and dose unit.
   `pipeline.study_parameters.resolve` gives each parameter:
   - its value;
   - its source: `recorded` (the workbooks, the .bm2 metadata, the files' unit
     column), `stated` (`study_design.json`) or `inferred` (the metadata step's
     LLM);
   - the parameters that are missing;
   - the parameters the data record conflicting values for.

   It is a pure function. The engine derives it per call and never stores it
   (invariant 3).
2. **One place for stated values.** `study_design.json` `fields` holds the
   design facts. Integration puts them on every experiment; a workbook value is
   never overridden. The file also holds three parameters no deposited file
   records: `doseUnit`, `dosingDays` and `dosingSchedule`. They stay in the file
   and are not put on the experiments. A stated unit may pick among units the
   files disagree on. It may not contradict the one unit they record.
3. **Refusal, not default.** Process (`safeguards.acts.require` with `method`,
   and `_build_process_context` for the unguarded notebook) refuses a study
   with a missing or conflicting parameter. The refusal is
   `study_parameters_incomplete` (422) and names each parameter. A request's
   `dose_unit` that disagrees with the study's is refused: the request is not
   where the unit is stated.
4. **Required inputs downstream.** Builders take `dose_unit` and `design` as
   required inputs. A missing one raises: `required_unit`, and
   `require_design` in place of `design_or_standard`. A Methods context cached
   before this change has no dosing days. A render refuses it with "run Process
   again" and does not re-state the assumed wording.
5. **Dosing from the books.** The published sessions state the dosing as their
   Methods print it:
   - RR-8 to NIEHS-06: "once daily" on 4 days (study days 0–3, necropsy on day
     4). Before this change these read 5 days.
   - NIEHS-07 to 10: "once daily" on 5 days.
   - NIEHS-12 and 13: "6 hours plus T90 per day" on 5 days. Before this change
     these read "once daily".

## Consequences

- BPAF (DTXSID7037717), Triclosan (DTXSID5032498) and `DTXSID50469320_nb`
  record no dose unit and no dosing. Process refuses them until a person states
  those.
- Inferred (LLM) values are still accepted, labelled `inferred`. Whether to
  infer metadata at all is an open question for the team. Removing `inferred`
  from `ACCEPTED_SOURCES` makes such a value missing.
- The dosing schedule is stated per study. Whether it should become a program
  rule (in the method profile) is open.
- Two defects surfaced, now fixed:
  - the LaTeX path filtered organ-weight captions without a design, so it
    assumed rats;
  - the web path never set the report's dose unit, so its genomics results read
    mg/kg for ppm studies.
- The vehicle vocabulary has no "acetone:corn oil (1:99)". NIEHS-08 and 10
  print that vehicle, but their sessions state "corn oil". This is open.
