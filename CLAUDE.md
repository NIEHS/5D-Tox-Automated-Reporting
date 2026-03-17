# rlm-bmdx

## Master TODO

### CRITICAL

- [ ] **Domain model refactor: end-to-end testing** — The provider/platform/dataType refactor (replacing monolithic domain strings) is committed but NOT validated. Test the full pipeline:
  1. Upload → validate → confirm metadata → integrate → process flow
  2. Integrated data tree: verify both tox_study AND inferred experiments appear as doseResponseExperiments
  3. NTP stats (build_table_data): verify stats computed correctly from tox_study experiments
  4. BMD values: verify BMD/BMDL from inferred .bm2 files attach correctly
  5. Section cards: verify one card per platform with merged tox_study + inferred data
  6. Clinical observations: verify categorical data handled correctly (not pivoted, own section)
  7. Gene expression: verify genomics pipeline still works
  8. DOCX/PDF export: verify reports render with new platform labels
  9. Session restore: verify saved sessions load correctly with new fingerprint format

### HIGH

- [ ] **xlsx as source of truth (unified feature)** — Three interconnected customer action items (#2, #5, #6) merged into one feature. xlsx = source of truth for animal roster, dose assignments, missing animals. bm2 = source of truth for BMD/BMDL modeling. txt/csv = derived intermediates. Includes study file detection by internal sheet structure and footnotes for animals that didn't survive to terminal sacrifice.
- [ ] **Verify pairwise statistics vs reference report** — Spot-checking showed some values match (T3, T4 hormones) but need thorough comparison across all endpoints against reference report.

### MEDIUM

- [ ] **experimentDescription null for genomic data** — When the integrated data object is created, `experimentDescription` is null for genomic/gene expression experiments. The LLM metadata inference pipeline (`experiment_metadata.py`) should populate these but genomic experiments end up with all-null fields. May be a bug in `infer_experiment_metadata()` or in how genomic experiment signals are gathered/matched.
- [ ] **Decouple background generation from data analysis tabs** — Apical and genomics tabs should be independently accessible once pool is approved, without requiring background section generation/approval first. Pool approval + metadata approval should be sufficient to unlock data processing tabs.
- [ ] **Rework Data tab UX** — The current Data tab workflow (upload → validate → confirm metadata → integrate → process) is cryptic and hard to follow. Needs a clearer step-by-step flow with better status indicators, progress feedback, and guidance for new users.
- [ ] **Process-integrated performance and UX** — Processing takes 10+ minutes (pybmds fitting ~15 models per endpoint). Needs: (1) progress feedback in the spinner showing current step (NTP stats → section cards → BMDS modeling → genomics), (2) ability to cancel/abort processing, (3) don't auto-process on page reload if cache exists, (4) optional email notification on completion, (5) nuclear reset should be possible even while processing is in progress.
- [ ] **Typst template fidelity** — Typst-generated reports don't yet match NIEHS reference layout (Bookshelf_NBK589955.pdf, InDesign-produced). Use `diff_tables.py` for cell-level comparison and `pdf_text/` parser for detailed font/position metadata.
- [ ] **Move generate_results_narrative out of bmdx-pipe** — Narrative generation is presentation logic (report writing), not data processing. It belongs in rlm-bmdx (the web app), not bmdx-pipe (the pipeline library). The template-based approach also produces generic boilerplate — consider LLM-generated narratives that read more like scientist-written prose.

### LONG-TERM

- [ ] **BMDExpress 3 domain-agnostic refactor** — 8-phase plan to make bmdx-core a domain-agnostic dose-response framework. Phases: (1) terminology aliasing, (2) domain identity fields, (3) domain config schema, (4) import generalization, (5) prefilter/model gating, (6) annotation/grouping abstraction, (7) reference ranges, (8) new domain rollout. Repo: ~/Dev/Projects/BMDExpress-3, branch bmdx-core. Full plan in memory: `bmdx-domain-agnostic-plan.md`.
