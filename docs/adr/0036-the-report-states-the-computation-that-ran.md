# 0036: The report states the computation that ran

- **Status:** Accepted (2026-11-17).
- **Deciders:** Dan Svoboda
- **Related:**
  - ADR-0027 (method profiles), ADR-0030 (the BMDS 2.7 engine), ADR-0035 (study
    parameters are recorded or stated);
  - `tables/apical_bmds.py` (`apical_bmd_method`, `platform_bmrs`, `bmd_terms`,
    `bmr_tag`: the record and what is read from it);
  - `narrative/methods_analysis.py` (the apical BMD paragraph and the eFDR
    subsection, built from records);
  - `pipeline/method_profile.py` (`MethodSettings.substitutions`);
  - `tables/table_builder_common.py` (`bmd_definition_footnote`),
    `rendering/render_common.py` (`ApicalTablePlan.bmr_tag`,
    `bmd_summary_legend`), the four emitters;
  - `rendering/bmd_appendix.py` (Table D-1 for the engine in force);
  - `rendering/latex_export.py` (`_resolve_go_cutoffs`);
  - `tests/unit/test_apical_bmd_method.py`, `tests/unit/test_bmd_appendix.py`.

## Context

A sweep of 2026-11-17 listed every place a report states something the
deposited data files did not provide. Its fourth group was the most serious:
the report described one computation and printed another.

- **Apical BMDs.** A printed BMD is the study's own BMDExpress result, or this
  tool's ToxicR fit at the settings that project records, or its fit at the
  method profile's benchmark response where the project records none. The
  Methods paragraph was written by the model from a guideline that described
  one engine, the profile's benchmark response and "constant variance" for
  every study.
- **A replaced engine.** RR-8 and NIEHS-02 to 10 pin a profile that names
  BMDS 2.7. That engine does not run here, so ToxicR model averaging runs in
  its place. The replacement was written to the log only. Appendix D, which
  those definitions title for the BMDS rules, printed this tool's acceptance
  criteria.
- **Benchmark response.** Every table's BMD legend and column header said "one
  standard deviation" as a literal. The February 2026 DTT method fits clinical
  chemistry at a 25% relative deviation.
- **NOEL.** The Methods defined it as the highest dose without a significant
  difference. The code takes the highest tested dose below the LOEL.
- **eFDR.** The Methods said for every study that eFDR results "are not
  included in this report's data package". NIEHS-12 and 13 print them in an
  appendix of the same report.
- **Gene-set cut-offs.** The export path used fixed cut-offs, not the pinned
  profile's, which Process applies and the Methods state.

## Decision

1. **One record of the apical BMD method.**
   `tables.apical_bmds.apical_bmd_method(integrated, method, platform_sexes)`
   gives, per group of assays and sexes that share settings:
   - `source`: `recorded` (the study's BMDExpress analysis; its BMDs are
     printed, and this tool's fit fills what it left without a BMD), `inferred`
     (no analysis recorded: this tool's fit at the profile's benchmark
     response) or `engine` (an engine that is the source of every BMD and runs
     with its own settings: BMDS 2.7);
   - the benchmark response, the variance and the models in force;
   - for `recorded`, the project's own notes (software, selection, models,
     variance; a missing note is `None`, not a default).

   Process builds it once, for the rows it models. It is a pure function of the
   integrated data and the method (invariant 3: derived, not stored as state).
2. **Statements about the computation are built from the record, not written
   by the model.**
   - The Methods' apical BMD paragraph (`narrative.methods_analysis`) is
     data-built, like Study Design. It states each source and its settings,
     the acceptance criteria the method applies, and the body-weight "ND" rule.
   - Each table's BMD column definition names the benchmark response(s) its
     BMDs were fit at (`bmd_definition_footnote`). The footnote record carries
     them, and the column headers' subscript is read from that record, so
     header and definition cannot disagree. One benchmark response keeps the
     published wording; several are each named; none recorded names none.
   - Every BMD summary entry carries its benchmark response; the summary's
     legend is built from them.
3. **A departure from the pinned method is stated in the report.**
   `MethodSettings.substitutions` records each one (`setting`, `asked`, `used`,
   `why`). The Methods name it in a paragraph of its own, and Table D-1 carries
   a note that the pinned method's rules were not applied. The machine's reason
   (a missing library) stays in the log.
4. **Table D-1 follows the engine in force.** ToxicR: the acceptance criteria.
   BMDS 2.7: the engine's own recommendation rules
   (`pipeline.bmds27.engine.recommendation_rules`).
5. **NOEL.** The statistics guideline states the rule the code applies: the
   highest dose below the LOEL, not determined when the LOEL is the lowest dose
   tested or there is no LOEL.
6. **eFDR.** The Methods' eFDR subsection is data-built. It says the report
   has the analysis and which table reports it, or that it has none. A report
   composed of several studies states its own (the report session holds the
   analysis).
7. **Gene-set cut-offs.** The export path takes them from the study's pinned
   method, as Process does.
8. **A cached Methods context without the record is refused** ("run Process
   again"), as ADR-0035 refuses one without dosing days.

## Consequences

- Every session must be processed again before it renders. The sections, BMD
  summary and Methods cache versions are bumped.
- A composed report (NIEHS-12, 13) states each study's BMD method under the
  study's name when the studies' methods differ; when they are the same it is
  stated once.
- The sections cache holds every sex. A table filtered to one sex by a view
  names the benchmark responses of both sexes of its assay if they differ. No
  study has that today.
- Not changed, and still open:
  - a project that records a benchmark response but no variance note is fit
    with nonconstant variance; the report now says so, but whether to fit it
    at all without the note is a method decision;
  - the models a project records are not read: every fit averages the four
    BMDExpress default models (the same four in every project so far);
  - the books define the NOEL in the words the old guideline used and print
    the values the code computes; which is meant is a question for the client;
  - whether a departure from the pinned method should close the publish gate;
  - the narrative builders still write "(Table 2)" and "(Table 3)" as
    literals. The cross-reference tokens that would replace them are not
    resolved on the Word surface;
  - the genomic tables' legacy headers and the animal roster header still
    print "mg/kg" as a literal.
