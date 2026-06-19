---
name: bmdx-tests
description: Run rlm-bmdx tests unattended via a single stable command so no per-step approval is needed. Use when running the test suite, verifying a refactor step is behavior-preserving, or checking the api_process_integrated regression net (golden oracle + smoke). Modes - guard (default, the process_integrated net), smart (import-graph selection of impacted tests), full (whole suite minus known-broken), or passthrough paths/args.
---

# bmdx-tests

Scripted test runner for rlm-bmdx. One stable command prefix
(`.claude/skills/bmdx-tests/run-tests.sh`) so a single settings allow-list
entry suppresses approval prompts — runs are unattended.

## Why this exists

The repo has no bare `python` (use `.venv/bin/python`), e2e tests hang
unattended (they call `page.pause()`), and two unit tests are pre-broken by
deleted PNG fixtures unrelated to current work. Typing a slightly different
`pytest ...` string each time triggers a fresh approval. This wrapper fixes the
command shape so it only needs approving once.

## Usage

Invoke the script directly via Bash:

```bash
.claude/skills/bmdx-tests/run-tests.sh guard               # default
.claude/skills/bmdx-tests/run-tests.sh smart               # auto-diff vs HEAD
.claude/skills/bmdx-tests/run-tests.sh smart process_integrated.py  # explicit
.claude/skills/bmdx-tests/run-tests.sh full
.claude/skills/bmdx-tests/run-tests.sh tests/unit/test_overleaf_sync.py -q
```

### Modes

- **`guard`** (default) — the `api_process_integrated` regression net:
  `test_process_integrated.py` (structural smoke) +
  `test_process_integrated_golden.py` (byte-for-byte payload oracle). This is
  the safety net for the ADR-0002 decomposition; run it between **every**
  extraction step. Green = the extraction is behavior-preserving.
- **`smart`** — run only the tests whose import graph transitively reaches a
  changed file. `select_tests.py` builds a module-level import graph of the
  repo with `ast` and reverse-walks it from the changed modules, so an
  integration test that reaches a route module via `background_server.app` is
  still selected. Two forms:
  - **`smart`** (no args) — diffs the working tree against `HEAD` (override
    with `BMDX_TEST_BASE`) plus untracked `.py`. Conservative: because it sees
    *all* uncommitted changes, a dirty `conftest.py`/`pyproject.toml`/fixture
    in the tree forces a full-suite fallback. In this repo the working tree has
    a pre-existing modified `tests/conftest.py`, so the no-arg form falls back
    to `full` until that is committed — use the explicit form below for lean
    selection during the refactor.
  - **`smart <file...>`** — pass the exact files you changed this step. Precise
    selection regardless of unrelated working-tree noise. This is the form to
    use between refactor extractions: `smart process_integrated.py`.
  - Fallbacks: a `conftest.py`/test-config/`tests/fixtures/` change → run
    `full` (blast radius unbounded); a change touching no test's import graph →
    run `guard` as a floor.
- **`full`** — the whole suite. e2e is excluded by pyproject's
  `-m 'not e2e'`. Two known-unrelated failures
  (`test_render_semantic_parity::test_figure_numbers_agree_across_surfaces`,
  `test_latex_export::test_load_session_data_overlays_real_session_when_present`)
  are deselected because they depend on genomics figure PNGs deleted from the
  working tree before this session — not real regressions.
- **passthrough** — anything else is forwarded straight to `pytest` (after
  `-p no:cacheprovider`), e.g. a single file or `-k` expression.

Exit code is pytest's: `0` green, nonzero means look at the output.
`smart` selection is import-static: a purely dynamic reference (e.g. a
monkeypatch target named as a string) is not followed, which is why `guard`
remains the authoritative net for the decomposition work.

## Notes

- Always run from anywhere in the repo; the script `cd`s to the git root.
- To regenerate the golden fixture after an *intentional* contract change:
  `UPDATE_GOLDEN=1 .venv/bin/python -m pytest tests/integration/test_process_integrated_golden.py`
  then eyeball the diff. The wrapper does not do this — regeneration must be
  deliberate.
