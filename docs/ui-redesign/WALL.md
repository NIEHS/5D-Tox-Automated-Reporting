# The Chinese wall around the existing user interfaces

Set up 2026-10-14, at the maintainer's request, for the work of designing a new
user interface **from scratch**. The new design should come from the workflow, the
data and the people who use it, not be anchored on the screens built before. So
the existing front-ends are off limits, with two exceptions:
- the **Bookshelf**, which the maintainer is keeping;
- the **Jupyter notebook**, which the maintainer called a good reference: a direct
  view of the workflow and its code without the idiot-proofing. Idiot-proofing is
  the new interface's most important purpose (HANDOFF.md §2).

Only the maintainer lifts the wall. Until then:

## Do not open, search, list or run

| Path | What it is |
|---|---|
| `wizard-ui/` | the current browser front-end's source |
| `web_wizard/` | its built bundle |
| `web/` | the earlier browser front-end (retired) |
| `rendering/bits_compare_page.py`, `web_routes/compare_routes.py` | the Compare page |
| `docs/ui-state-management-plan.html`, `docs/plans/integrated-wizard-versioned-preview.md`, `docs/code-walkthrough.*`, `docs/architecture-map.*`, `docs/code-structure-report-*.html` | documents that describe those front-ends |
| `tests/e2e/` | browser tests of the old front-end |
| memory notes about the old screens: `expertise_ui_state.md`, `constraints_ui_work.md`, `feedback_state_derivation.md`, `project_wizard_step_granularity_revisit.md`, `project_data_review_page_revisit.md`, `project_approve_page_revisit.md`, `project_integrated_wizard_versioned_preview.md`, `project_document_configurator.md`, `project_process_step_phase_placement.md`, and their index, `walled_existing_ui_index.md` | what these notes held that the new design needs is restated, neutrally, in `HANDOFF.md` §2 and §10 |

This includes indirect looks:
- `rlm-code` symbol queries that land in those paths;
- `git log -p` or `git show` on them;
- serving `/`, `/workflow…` or `/Compare` and looking at the pages.

**Work in `/workspace/rlm-bmdx-ui`** (branch `ui-redesign`). It is a sparse
worktree, and the old front-end's source, its documents and the browser tests are
not checked out there. So a repository-wide `grep`, `rg` or `find` cannot land in
them, and its `rlm-code` index (`.rlm-code.duckdb` in the worktree) was built
without them. Untracked data (`sessions/`, `assets/`, `output/`, `.venv`, …) is
linked in from `/workspace/rlm-bmdx`. The app on port 9000 (and a workspace's on
9300) runs from the worktree and serves no old front-end.

The Claude Code settings in both checkouts deny reading and editing these paths
(`.claude/settings.local.json`). Shell commands that name them are blocked too.

What still reaches the old front-ends, and so is on you:
- the main checkout (`/workspace/rlm-bmdx`): don't search or browse it;
- git history, which the two checkouts share: no `git log -p`, `git show <commit>`
  or `git grep` beyond the worktree's own files;
- the two Compare files, which the app imports and so are checked out (denied).

Don't work around any of it, for instance by building a path indirectly.

## Allowed, and the material to design from

- **The Jupyter notebook** (`notebooks/workflow_walkthrough.ipynb`, written from
  `notebooks/_nb_cells_data.py` and `_nb_cells_report.py`). It is the workflow one
  step per cell, each step explained: purpose, implementation, reads → writes, how
  it fails. Use it to understand the workflow and what each step calls. Don't take
  its shape as the interface's: it deliberately leaves out the guarding. Its text
  names a few old browser screens in passing ("the Upload step", "Approve"); read
  those as names only.
- **The Bookshelf (kept):**
  - `rendering/bookshelf_preview.py`, `rendering/bookshelf_landing.py`;
  - `web_routes/bookshelf_routes.py`, `web_routes/supplemental_routes.py`;
  - the companion (`rendering/published_clone.py`, `tooling/published_clone.py`);
  - its pages at `/Bookshelf`.

  Its facsimile's right rail links to `/Compare/<id>`. That link can stay, or be
  pointed at whatever the new design compares with.
- **The UI-agnostic core:** `workflow/`, `pipeline/`, `document_model/`,
  `rendering/` (the emitters and `preview_surface`), `tables/`, `narrative/`,
  `genomics/`, `knowledge_base/`, `styling_export/`, `common/`.
- **The backend routes:** `web_routes/` other than `compare_routes.py`. They were
  shaped by the old front-ends; see `http-api.md`.
- **Command-line drivers:** `tooling/generate_report.py` (the reference driver of
  the whole workflow), `tooling/build_published_reports.py`, `tooling/workspace.sh`.
- **Documents:** `CONTEXT.md`, `docs/adr/`, `docs/headless-report-generation.md`,
  and this directory.
- **Tests** under `tests/unit` and `tests/integration`.

If something on the far side of the wall seems necessary, ask the maintainer
rather than looking.
