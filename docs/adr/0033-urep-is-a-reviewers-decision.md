# 0033: An unreliable estimate of potency is a reviewer's decision

- **Status:** Accepted (2026-10-29).
- **Deciders:** Dan Svoboda
- **Supersedes:** the automatic UREP rule (`_is_anomalous_bmd`: a BMD below
  NOEL/10 became UREP with no one deciding), and the todo item "BMD anomaly
  detection: rules vs LLM".
- **Related:**
  - `pipeline/bmd_review.py` (the screen, the decisions, applying them);
  - `pipeline/process_integrated.py` (`_review_bmds`, after the ToxicR fills);
  - `pipeline/processing_helpers.py` (`_build_apical_bmd_summary`);
  - `narrative/unified_narrative.py` (`_urep_sentence`);
  - `rendering/render_common.py` (the legend and `UREP_NOTE`);
  - `workflow/engine.py` (`publish_readiness`);
  - `safeguards/inputs.py` (`bmd_review_invalid`), `safeguards/guarded.py`
    (`review_bmds`), `safeguards/publish.py` (`bmd_review_required`);
  - `tooling/generate_report.py` (`--bmd-review`), `web_routes/integrated_routes.py`
    (`/api/bmd-review/{dtxsid}`);
  - `tests/unit/test_bmd_review.py`.

## Context

NIEHS-07 to 10 print some apical BMDs as **UREP**, "an unreliable estimate of
potency". The reports define it as "a label based on review by a subject matter
expert and rejection of BMD modeling results". The Results then say, for each
one: "its value was much lower (approximately 75- to 230-fold) than would be
expected given the endpoint-specific NOEL and LOEL values". The fold range is
NOEL/BMD to LOEL/BMD.

Before this decision the application made a BMD UREP when it fell below NOEL/10,
with no one deciding. The 12 published books show that no single ratio
reproduces the experts' decisions:

- they **rejected** BMDs only 10-fold below the NOEL (NIEHS-07 globulin and
  A/G ratio, NIEHS-08 cholesterol);
- they **accepted** BMDs 25-fold below it (NIEHS-08 female alkaline phosphatase,
  6.461 against a NOEL of 160) and 11-fold below it (NIEHS-09 female TSH).

Two more problems with the automatic rule:

- **It skipped filled BMDs.** It looked only at `.bm2` BMDs. A BMD filled from
  the ToxicR recompute was never screened (NIEHS-08 male TSH: 13.6 against a NOEL
  of 160).
- **It could not reproduce the published UREPs.** Our BMDs come from other
  engines than the 2021 books' BMDS 2.7 fits. Not one of the 17 published UREPs
  is far below its NOEL in our builds.

A language model was the other option. The maintainer chose a rule plus a
reviewer (2026-10-29): the label is an expert's judgement, it decides what the
Abstract reports, and a model's answer would change from run to run.

## Decision

**The screen proposes; a reviewer decides.**

1. **The screen.** Every apical BMD is screened, whatever its source (`.bm2`,
   ToxicR fill, BMDS 2.7). One more than `ANOMALY_RATIO_THRESHOLD` (10) times
   below its NOEL is **flagged**; with no NOEL, its LOEL is used. Ten is the
   lowest fold any published UREP was rejected at. Each flag carries its fold
   range.
2. **The decision.** For each flag a reviewer records "unreliable" (UREP) or
   "reliable", with a reason. Decisions go in `bmd_reviews.json`, together with
   the BMD each was made on; replaced decisions are kept in its history.
   - A decision holds only for that BMD. A reprocess that changes the value makes
     the flag pending again.
   - The safeguards refuse a decision on an endpoint the last Process did not
     flag, a decision other than the two, and a decision with no reason
     (`bmd_review_invalid`).
3. **Applied once, on the rows.** Process screens the rows right after the
   ToxicR fills and applies the decisions there. Every surface then agrees: the
   Tables 2–7 BMD columns, the narratives, the BMD summary, the Abstract and the
   Summary.
   - **A rejected BMD** prints UREP, with its direction blanked in the summary.
     The Results say what the reports say, with its fold range. The summary
     table gets the reports' footnote.
   - **An accepted BMD** stays a number.
   - Process writes the flags to `bmd_flags.json`.
4. **The publish gate.** Publishing waits until each flag is decided
   (`bmd_review_pending`), and until a Process has applied each decision
   (`bmd_review_not_applied`). The refusal is `bmd_review_required`; `--draft`
   overrides it, as it overrides the other blocks.
5. **Where a reviewer decides.**
   - Command line: `--bmd-review decisions.json`. Every run lists the flags as
     "BMD review:" lines. The decisions are recorded after the run's Process,
     against the flags it just wrote, and Process runs again to apply them.
   - Published reproductions: `tooling.build_published_reports` passes a book's
     `templates/studies/<DTXSID>/bmd_review.json` when there is one.
   - Web routes: `GET`/`POST /api/bmd-review/{dtxsid}`, through
     `safeguards.guarded.review_bmds`.
   - The notebook calls `pipeline.bmd_review` unguarded.

## Consequences

- **No automatic UREP.** A book with no flagged BMD is unchanged. None of the 12
  rebuilt books had one; their published UREPs came from BMDS 2.7 fits we don't
  run.
- **A flag blocks publishing until reviewed.** Rendering with `--draft` still
  works.
- **Two published wordings now come from the application:** the reports' UREP
  legend ("a label based on review by a subject matter expert …") and their
  footnote.
- **Cache keys.** A study's caches change only when it has decisions: the
  sections and BMD-summary keys include them. The BMD summary's cache version
  was bumped once, when the automatic rule was removed.
