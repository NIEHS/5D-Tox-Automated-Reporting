#!/usr/bin/env bash
# bmdx-tests — scripted, unattended test runner for rlm-bmdx.
#
# Single stable command prefix so one settings allow-list entry suppresses
# per-run approval prompts.  Always uses the repo venv (no bare `python` on
# this box) and respects pyproject's `-m 'not e2e'` default (e2e calls
# page.pause() and hangs unattended).
#
# Usage:
#   run-tests.sh guard   # DEFAULT: the api_process_integrated regression net
#                        # (golden oracle + structural smoke) — run between
#                        # every refactor extraction step.
#   run-tests.sh smart   # import-graph selection: run only the tests that
#                        # transitively import a changed file (vs. the merge
#                        # base). Falls back to `full` when it can't bound the
#                        # blast radius (conftest/config/fixture change, etc.).
#   run-tests.sh full    # whole suite, minus 2 known-unrelated failures that
#                        # depend on genomics PNG fixtures deleted pre-session.
#   run-tests.sh <paths and pytest args...>   # explicit passthrough.
#
# Exit code is pytest's: 0 = green, nonzero = something to look at.
set -u -o pipefail

ROOT="$(git rev-parse --show-toplevel)" || exit 2
cd "$ROOT" || exit 2

PY=.venv/bin/python
if [[ ! -x "$PY" ]]; then
    echo "ERROR: $PY not found — run from the rlm-bmdx repo with its venv." >&2
    exit 2
fi

SELECTOR=".claude/skills/bmdx-tests/select_tests.py"
# `smart` diffs the working tree against this ref to find changed files.
# Default HEAD = "what I've edited but not yet committed" — the refactor
# step workflow. Override with BMDX_TEST_BASE (e.g. the branch's merge base)
# to select tests for everything that diverged.
SMART_BASE="${BMDX_TEST_BASE:-HEAD}"

# The api_process_integrated regression net (ADR-0002 decomposition guard).
GUARD_TESTS=(
    tests/integration/test_process_integrated.py
    tests/integration/test_process_integrated_golden.py
)

# Pre-existing failures unrelated to any current work: both depend on
# genomics figure PNGs deleted from the working tree before this session.
# Deselect them so a `full` run's signal reflects only real regressions.
KNOWN_BROKEN=(
    --deselect "tests/unit/test_render_semantic_parity.py::test_figure_numbers_agree_across_surfaces"
    --deselect "tests/unit/test_latex_export.py::test_load_session_data_overlays_real_session_when_present"
)

run_full() {
    echo ">>> bmdx-tests: FULL suite (e2e excluded, 2 known-broken deselected)"
    set -x
    "$PY" -m pytest "${KNOWN_BROKEN[@]}" -p no:cacheprovider
}

mode="${1:-guard}"
case "$mode" in
    guard)
        echo ">>> bmdx-tests: GUARD (api_process_integrated regression net)"
        set -x
        "$PY" -m pytest "${GUARD_TESTS[@]}" -p no:cacheprovider
        ;;
    smart)
        shift
        if [[ $# -gt 0 ]]; then
            # Explicit changed-file list: "I know exactly what I touched."
            # Precise selection regardless of pre-existing working-tree noise.
            changed=("$@")
            echo ">>> bmdx-tests: SMART — ${#changed[@]} explicit file(s)" >&2
        else
            # Auto: working tree vs SMART_BASE (default HEAD) + untracked .py.
            # NOTE: picks up ALL uncommitted changes, so any dirty conftest/
            # config in the tree will (correctly) force a full fallback.
            mapfile -t changed < <(
                { git diff --name-only "$SMART_BASE" -- ;
                  git ls-files --others --exclude-standard -- '*.py' ; } | sort -u
            )
            if [[ ${#changed[@]} -eq 0 ]]; then
                echo ">>> bmdx-tests: SMART — no changes vs ${SMART_BASE}; nothing to test." >&2
                exit 0
            fi
            echo ">>> bmdx-tests: SMART — ${#changed[@]} changed file(s) vs ${SMART_BASE}" >&2
        fi
        # Selector prints test paths on stdout (consumed here) and a summary on
        # stderr (shown live). Run it once; capture its real exit code.
        sel_out="$(mktemp)"
        trap 'rm -f "$sel_out"' EXIT
        REPO_ROOT="$ROOT" "$PY" "$SELECTOR" "${changed[@]}" >"$sel_out"
        sel_rc=$?
        mapfile -t selected <"$sel_out"
        if [[ $sel_rc -eq 3 ]]; then
            echo ">>> bmdx-tests: SMART selection inconclusive -> running FULL" >&2
            run_full
            exit $?
        fi
        if [[ ${#selected[@]} -eq 0 ]]; then
            echo ">>> bmdx-tests: SMART — change touches no test's import graph; running GUARD as a floor" >&2
            set -x
            "$PY" -m pytest "${GUARD_TESTS[@]}" -p no:cacheprovider
            exit $?
        fi
        echo ">>> bmdx-tests: SMART — running ${#selected[@]} selected test file(s)"
        set -x
        "$PY" -m pytest "${selected[@]}" -p no:cacheprovider
        ;;
    full)
        echo ">>> bmdx-tests: FULL suite (e2e excluded, 2 known-broken deselected)"
        set -x
        "$PY" -m pytest "${KNOWN_BROKEN[@]}" -p no:cacheprovider
        ;;
    *)
        echo ">>> bmdx-tests: passthrough -> pytest $*"
        set -x
        "$PY" -m pytest -p no:cacheprovider "$@"
        ;;
esac
