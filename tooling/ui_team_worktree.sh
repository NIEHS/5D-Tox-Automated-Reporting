#!/usr/bin/env bash
# tooling/ui_team_worktree.sh — a sparse worktree for one agent of the new-UI team
# (docs/ui-redesign/TEAM.md).
#
#   /workspace/ui-team/<name>/              the worktree, on branch ui-<name>
#   /workspace/ui-team/_scratch/<name>/     its scratch SESSIONS_DIR / OUTPUT_DIR / screenshots
#
# The worktree branches from ui-redesign (or BASE) and takes the SAME sparse-checkout
# rules as the orchestrator's worktree (/workspace/rlm-bmdx-ui), so the walled old
# front-end is not on disk (docs/ui-redesign/WALL.md).  This is why agents must not
# use worktree isolation: that branches from main with a full checkout.  The
# untracked data the orchestrator's worktree links in (sessions/, .venv, …) is
# linked in the same way; sessions/ stays read-only by the team's rules.
#
# `remove` removes the worktree only; its branch is kept (the orchestrator merges
# or deletes branches deliberately).
#
# Usage:
#   tooling/ui_team_worktree.sh add NAME [BASE]
#   tooling/ui_team_worktree.sh relink NAME   (add the data links an older worktree lacks)
#   tooling/ui_team_worktree.sh remove NAME
#   tooling/ui_team_worktree.sh list
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT=/workspace/ui-team
CMD="${1:-}"
NAME="${2:-}"

usage() { echo "usage: $0 add NAME [BASE] | relink NAME | remove NAME | list" >&2; exit 2; }

# The orchestrator's links to untracked data, at any depth, as "path<TAB>target"
# (git's own and the dependency folders skipped; .claude/ has its own rules).
data_links() {
  (cd "$SRC" && find . \( -path ./.git -o -path ./.venv -o -path ./ui/node_modules -o -path ./.claude \) -prune \
       -o -type l -printf '%P\t%l\n')
}

# Link them into worktree $1: never over a path that exists, never where git
# tracks the path.
link_data() {
  local wt="$1" link target
  data_links | while IFS=$'\t' read -r link target; do
    [[ -e "$wt/$link" || -L "$wt/$link" ]] && continue
    git -C "$wt" ls-files --error-unmatch -- "$link" >/dev/null 2>&1 && continue
    mkdir -p "$wt/$(dirname "$link")"
    ln -s "$target" "$wt/$link"
  done
}

case "$CMD" in
  list)
    git -C "$SRC" worktree list | grep -F "$ROOT/" || true
    ;;
  add)
    [[ "$NAME" =~ ^[A-Za-z0-9_-]+$ ]] || usage
    BASE="${3:-ui-redesign}"
    WT="$ROOT/$NAME"
    BRANCH="ui-$NAME"
    [[ -e "$WT" ]] && { echo "$WT already exists" >&2; exit 1; }
    mkdir -p "$ROOT" "$ROOT/_scratch/$NAME"/{sessions,output}

    # Create without a checkout, give it the orchestrator's sparse rules, THEN
    # populate — so the walled paths are never written to disk, not even briefly.
    git -C "$SRC" worktree add --no-checkout -b "$BRANCH" "$WT" "$BASE"
    git -C "$WT" config --worktree core.sparseCheckout true
    git -C "$WT" config --worktree core.sparseCheckoutCone false
    cp "$(git -C "$SRC" rev-parse --git-path info/sparse-checkout)" \
       "$(git -C "$WT" rev-parse --git-path info/sparse-checkout)"
    git -C "$WT" reset --hard -q "$BRANCH"

    # The same links to untracked data as the orchestrator's worktree, at any
    # depth (assets/cebs/_bookshelf, the CEBS packages, …): the code reads them
    # by path. Each keeps its target; a path git tracks is never replaced.
    link_data "$WT"

    echo "worktree  $WT  (branch $BRANCH, from $BASE)"
    echo "scratch   $ROOT/_scratch/$NAME  (SESSIONS_DIR=…/sessions OUTPUT_DIR=…/output)"
    ;;
  relink)
    # Add the data links an older worktree lacks (nested ones came later).
    [[ "$NAME" =~ ^[A-Za-z0-9_-]+$ ]] || usage
    WT="$ROOT/$NAME"
    [[ -d "$WT" ]] || { echo "no worktree $WT" >&2; exit 1; }
    link_data "$WT"
    ;;
  remove)
    [[ "$NAME" =~ ^[A-Za-z0-9_-]+$ ]] || usage
    WT="$ROOT/$NAME"
    # Drop the data links `add` made (they read as untracked files); anything
    # else uncommitted still makes `git worktree remove` refuse, as it should.
    data_links | while IFS=$'\t' read -r link _; do
      [[ -L "$WT/$link" ]] && rm "$WT/$link"
    done
    git -C "$SRC" worktree remove "$WT"
    echo "removed $ROOT/$NAME (branch ui-$NAME kept)"
    ;;
  *) usage ;;
esac
