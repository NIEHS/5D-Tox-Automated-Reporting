"""
overleaf_sync.py — transport between the app and an Overleaf project (ADR-0005).

Overleaf exposes a project as a git remote (git-bridge).  This module is the
thin transport shell that pushes the generated report bundle to that remote and
pulls human edits back.  Until the NIEHS Overleaf admin grants git-bridge
access, the same client points at a LOCAL "stand-in" remote — a bare git repo on
disk that behaves identically — so the entire round-trip can be built and tested
with zero dependency on Overleaf.  When access lands, only the remote URL
changes; nothing else here moves.

The three roles
---------------
  - **stand-in remote** (`.overleaf-standin/<dtxsid>.git`, a *bare* repo) — plays
    "the Overleaf project."  Later: the real git-bridge URL.
  - **working clone** (`.overleaf-clone/<dtxsid>/`) — the app's local checkout of
    that project.  push commits the freshly-generated bundle here and sends it
    up; pull brings committee edits down here, where the reconciler diffs them
    against the baseline.
  - **the dev document** (`documents/<dtxsid>/`, tracked in the main repo) — the
    app's generated source, copied into the clone on push.

Both `.overleaf-standin/` and `.overleaf-clone/` are gitignored dev scaffolding,
NOT product artifacts.

What this module does NOT do
----------------------------
It does not interpret edits.  push/pull/simulate just move bytes through git and
hand back commit shas + the edited files; mapping an edited region back to a
node (git-diff x sentinel attribution) is the reconciler's job, built on top.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
# subprocess — drive plain `git` (the transport IS git; later the remote is the
#              git-bridge URL + PAT instead of a local path).
# shutil/tempfile/pathlib — mirror the bundle into the clone; throwaway clone
#              for the simulated committee edit.

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

# NOTE: this module imports NO app code — the document directory it pushes is
# passed in by the caller (doc_dir=), so the library stays domain-agnostic.

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# parent.parent: this module lives one level down in the roundtrip/ package, so
# the dev-scaffolding roots below still resolve under the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent

# Gitignored dev scaffolding roots (overridable in tests via `root=`).
_STANDIN_ROOT = _REPO_ROOT / ".overleaf-standin"
_CLONE_ROOT = _REPO_ROOT / ".overleaf-clone"

# We pin an explicit branch so first-push / clone behaviour is deterministic
# regardless of the host git's init.defaultBranch.
_BRANCH = "main"

# Identities stamped on commits so provenance is legible in the stand-in's log.
# The app's pushes look like the app; the simulated edits look like the
# committee (the reconciler later tags overrides source="overleaf").
_APP_AUTHOR = ("rlm-bmdx app", "app@rlm-bmdx.local")
_COMMITTEE_AUTHOR = ("NIEHS Committee", "committee@niehs.example")

# Files in the dev document that are app-internal and must NOT be sent to the
# "Overleaf project" (everything else — report.tex, niehs.cls, figures/,
# README.md — is the bundle the committee sees).
_NOT_FOR_OVERLEAF = {".rlm-sync.json"}

# Per-session binding linking a report to its Overleaf project: the human-facing
# project URL (for the "Open in Overleaf" link) and the git remote we push/pull
# (the GitHub repo Overleaf syncs with, or a git-bridge URL).  Stored alongside
# the session cache so it survives across runs.
_SESSIONS_DIR = _REPO_ROOT / "sessions"
_BINDING_FILENAME = "_overleaf_binding.json"


# ---------------------------------------------------------------------------
# Helpers (private)
# ---------------------------------------------------------------------------

def _git(
    args: "list[str]",
    cwd: Path,
    author: "tuple[str, str] | None" = None,
    *,
    strip: bool = True,
) -> str:
    """
    Run a git command in `cwd` and return its stdout.

    `author`, when given, sets committer + author identity for that single
    invocation via -c flags — deterministic and independent of global git
    config (which may be unset in CI).  `strip` defaults True (sha/status
    output); pass strip=False when capturing file CONTENT (e.g. `git show`,
    where a trailing newline is significant).  Raises with captured stderr on
    failure.
    """
    cmd = ["git"]
    if author is not None:
        name, email = author
        cmd += [
            "-c", f"user.name={name}", "-c", f"user.email={email}",
            "-c", f"committer.name={name}", "-c", f"committer.email={email}",
        ]
    cmd += args
    result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed in {cwd}:\n{result.stderr.strip()}"
        )
    return result.stdout.strip() if strip else result.stdout


def _standin_path(dtxsid: str, root: Path) -> Path:
    """Path of the bare stand-in remote for a session."""
    return root / ".overleaf-standin" / f"{dtxsid}.git"


def _clone_path(dtxsid: str, root: Path) -> Path:
    """Path of the app's working clone for a session."""
    return root / ".overleaf-clone" / dtxsid


def _mirror_bundle(src_doc_dir: Path, clone_dir: Path) -> None:
    """
    Make the clone's working tree mirror the dev document bundle.

    Clears everything in the clone except its .git, then copies every entry of
    the dev document except the app-internal sidecar — so the "Overleaf project"
    receives exactly the bundle (report.tex, niehs.cls, figures/, README.md) and
    deletions upstream propagate.
    """
    for entry in clone_dir.iterdir():
        if entry.name == ".git":
            continue
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    for entry in src_doc_dir.iterdir():
        if entry.name in _NOT_FOR_OVERLEAF or entry.name == ".git":
            continue
        dest = clone_dir / entry.name
        if entry.is_dir():
            shutil.copytree(entry, dest)
        else:
            shutil.copy2(entry, dest)


def _has_staged_changes(repo: Path) -> bool:
    """True if `git commit` would have something to record."""
    # diff --cached --quiet exits 1 when there ARE staged changes.
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=str(repo),
        capture_output=True, text=True,
    )
    return result.returncode != 0


# ---------------------------------------------------------------------------
# Public API — report ↔ Overleaf project binding
# ---------------------------------------------------------------------------

def get_binding(dtxsid: str, *, sessions_dir: "Path | None" = None) -> dict:
    """
    Return a report's Overleaf binding {project_url?, git_remote?}, or {} if
    unbound / unreadable.  Used by the UI to enable the "Open in Overleaf" link
    and by push/pull to find the remote without it being passed each call.
    """
    base = Path(sessions_dir) if sessions_dir is not None else _SESSIONS_DIR
    path = base / dtxsid / _BINDING_FILENAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def set_binding(
    dtxsid: str,
    *,
    project_url: "str | None" = None,
    git_remote: "str | None" = None,
    baseline_commit: "str | None" = None,
    sessions_dir: "Path | None" = None,
) -> dict:
    """
    Merge fields into a report's binding and persist it.

    Only the provided fields are updated, so the UI can set the project URL
    without clobbering a remote, and a Send can record `baseline_commit` (the
    sha it just pushed — the reconciler diffs pulled-back edits against it, and
    Send's staleness guard compares the remote head to it) without touching the
    rest.  Returns the merged binding.
    """
    base = Path(sessions_dir) if sessions_dir is not None else _SESSIONS_DIR
    binding = get_binding(dtxsid, sessions_dir=sessions_dir)
    if project_url is not None:
        binding["project_url"] = project_url
    if git_remote is not None:
        binding["git_remote"] = git_remote
    if baseline_commit is not None:
        binding["baseline_commit"] = baseline_commit
    path = base / dtxsid / _BINDING_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(binding, indent=2) + "\n")
    return binding


# ---------------------------------------------------------------------------
# Public API — transport (local stand-in today, real remote when set)
# ---------------------------------------------------------------------------

def init_standin(dtxsid: str, *, root: Path = _REPO_ROOT) -> Path:
    """
    Create (idempotently) the bare stand-in remote for a session.

    Pins the bare repo's HEAD to `main` so later clones check out the right
    branch even before the first push has created it.  Returns the remote path.
    """
    standin = _standin_path(dtxsid, root)
    if not (standin / "HEAD").exists():
        standin.parent.mkdir(parents=True, exist_ok=True)
        _git(["init", "--bare", "-q", str(standin)], cwd=standin.parent)
        _git(["symbolic-ref", "HEAD", f"refs/heads/{_BRANCH}"], cwd=standin)
    return standin


def _ensure_clone(clone: Path, remote_url: str, *, is_external: bool) -> None:
    """
    Make `clone` a working checkout whose origin is `remote_url`, synced to the
    remote's current branch tip (so a commit pushed on top fast-forwards).

    Handles three cases:
      - clone already exists → (re)point origin if it changed (e.g. switching a
        stand-in clone over to the real Overleaf/GitHub remote) and hard-reset to
        origin/<branch> when the remote has it;
      - fresh clone of an EXTERNAL remote (real project) → `git clone` so we get
        its existing history + content;
      - fresh clone of the LOCAL stand-in (empty bare) → `git init` + remote add.
    """
    branch = _BRANCH

    def _onto_branch() -> None:
        # Put the clone on `branch`, synced to the remote tip if the remote has
        # it, else create `branch` (handles an EMPTY remote — no main yet — so
        # the first push can create it).  -f discards any local state from a
        # previous (stand-in) life.
        _git(["fetch", "-q", "origin"], cwd=clone)
        if f"origin/{branch}" in _git(["branch", "-r"], cwd=clone):
            _git(["checkout", "-q", "-f", "-B", branch, f"origin/{branch}"], cwd=clone)
        else:
            _git(["checkout", "-q", "-B", branch], cwd=clone)

    if (clone / ".git").exists():
        try:
            current = _git(["remote", "get-url", "origin"], cwd=clone)
        except RuntimeError:
            current = ""
        if current != remote_url:
            if current:
                _git(["remote", "set-url", "origin", remote_url], cwd=clone)
            else:
                _git(["remote", "add", "origin", remote_url], cwd=clone)
        _onto_branch()
        return

    if is_external:
        # Clone WITHOUT -b: a populated repo checks out its default branch; an
        # EMPTY one clones cleanly (no "branch not found"), and _onto_branch()
        # then settles us on `branch` either way.
        clone.parent.mkdir(parents=True, exist_ok=True)
        _git(["clone", "-q", remote_url, str(clone)], cwd=clone.parent)
        _onto_branch()
    else:
        clone.mkdir(parents=True, exist_ok=True)
        _git(["init", "-q", "-b", branch], cwd=clone)
        _git(["remote", "add", "origin", remote_url], cwd=clone)


def push_document(
    dtxsid: str,
    doc_dir: Path,
    *,
    remote: "str | None" = None,
    root: Path = _REPO_ROOT,
    message: str = "app: sync generated report",
) -> str:
    """
    Push a document bundle to the project remote (the "send to Overleaf").

    `doc_dir` is the directory whose contents are mirrored up — supplied by the
    caller (the app passes its documents/<dtxsid>/), so this library module
    stays domain-agnostic.  `remote` selects the target:
      - None (default) → the LOCAL stand-in bare repo (offline dev/testing);
      - a URL → the real project remote (a git-bridge URL, or a GitHub repo).
        The existing project is cloned so our push fast-forwards on top of its
        history; auth is the ambient git credential helper (no token in code).

    Mirrors doc_dir into the working clone, commits any change, and pushes.
    Returns the pushed commit sha — the baseline the reconciler diffs
    pulled-back edits against.
    """
    doc_dir = Path(doc_dir)
    if not doc_dir.exists():
        raise FileNotFoundError(
            f"No dev document at {doc_dir} — run sync_document({dtxsid!r}) first."
        )

    remote_url = remote if remote is not None else str(init_standin(dtxsid, root=root))
    clone = _clone_path(dtxsid, root)
    _ensure_clone(clone, remote_url, is_external=remote is not None)

    _mirror_bundle(doc_dir, clone)
    _git(["add", "-A"], cwd=clone)
    if _has_staged_changes(clone):
        _git(["commit", "-q", "-m", message], cwd=clone, author=_APP_AUTHOR)
    # -u sets upstream so later pull/push need no refspec.
    _git(["push", "-q", "-u", "origin", _BRANCH], cwd=clone)
    return _git(["rev-parse", "HEAD"], cwd=clone)


def pull_document(dtxsid: str, *, root: Path = _REPO_ROOT) -> "tuple[Path, str]":
    """
    Pull the stand-in remote into the working clone (bring committee edits down).

    Returns (clone_path, head_sha).  The clone's report.tex now reflects any
    edits pushed to the remote; the reconciler diffs it against the push baseline.
    """
    clone = _clone_path(dtxsid, root)
    if not (clone / ".git").exists():
        raise FileNotFoundError(
            f"No working clone at {clone} — call push_document({dtxsid!r}) first."
        )
    _git(["pull", "-q", "--no-rebase", "origin", _BRANCH], cwd=clone)
    return clone, _git(["rev-parse", "HEAD"], cwd=clone)


def read_clone_report(dtxsid: str, *, root: Path = _REPO_ROOT) -> str:
    """Read report.tex from the working clone (convenience for the reconciler)."""
    return (_clone_path(dtxsid, root) / "report.tex").read_text()


def remote_head(dtxsid: str, *, root: Path = _REPO_ROOT) -> "str | None":
    """
    Fetch and return the remote's current branch-tip sha, or None if there's no
    working clone yet / the remote has no branch.

    Used by Send's staleness guard: if this differs from the recorded baseline,
    the committee has pushed edits we haven't fetched, so Send must refuse and
    ask the caller to Fetch first (reconcile-before-overwrite).
    """
    clone = _clone_path(dtxsid, root)
    if not (clone / ".git").exists():
        return None
    _git(["fetch", "-q", "origin"], cwd=clone)
    if f"origin/{_BRANCH}" not in _git(["branch", "-r"], cwd=clone):
        return None
    return _git(["rev-parse", f"origin/{_BRANCH}"], cwd=clone)


def report_at(dtxsid: str, sha: str, *, root: Path = _REPO_ROOT) -> str:
    """
    Read report.tex as of a specific commit in the working clone.

    Used to recover the GENERATED baseline (what the app pushed) for the
    reconciler to diff the edited working tree against.  strip=False so file
    content is byte-faithful.
    """
    return _git(["show", f"{sha}:report.tex"], cwd=_clone_path(dtxsid, root), strip=False)


def reconcile_from_clone(
    dtxsid: str,
    baseline_sha: str,
    *,
    root: Path = _REPO_ROOT,
    source: str = "overleaf",
    sessions_dir=None,
):
    """
    Reconcile the pulled-back edits against the push baseline and write overrides.

    Diffs report.tex at `baseline_sha` (the app's push) against the clone's
    current working tree (the pulled committee edits), attributes each change to
    its anchor, and persists overrides — the round-trip's payoff.  Returns the
    reconcile summary {written, structural, parse_warnings}.

    `sessions_dir` is forwarded to the override store (defaults to the real
    sessions/ via roundtrip.overrides); tests redirect it to a tmp dir.
    """
    from .reconcile import apply_reconcile

    baseline_tex = report_at(dtxsid, baseline_sha, root=root)
    edited_tex = read_clone_report(dtxsid, root=root)
    return apply_reconcile(
        dtxsid, baseline_tex, edited_tex, source=source, sessions_dir=sessions_dir
    )


def simulate_overleaf_edit(
    dtxsid: str,
    edit_fn,
    *,
    root: Path = _REPO_ROOT,
    message: str = "overleaf: committee edit",
) -> str:
    """
    Simulate a committee editing report.tex in Overleaf, for dev/testing.

    Clones the stand-in into a throwaway "committee" checkout (separate from the
    app's clone, mirroring how Overleaf is a separate party), applies
    `edit_fn(report_text) -> new_text`, commits as the committee, and pushes
    back.  A subsequent pull_document() then brings the edit down to the app's
    clone.  Returns the edited commit sha.
    """
    standin = _standin_path(dtxsid, root)
    if not (standin / "HEAD").exists():
        raise FileNotFoundError(
            f"No stand-in remote at {standin} — push_document({dtxsid!r}) first."
        )
    tmp = Path(tempfile.mkdtemp(prefix=f"overleaf-edit-{dtxsid}-"))
    try:
        _git(["clone", "-q", str(standin), str(tmp)], cwd=tmp.parent)
        report = tmp / "report.tex"
        report.write_text(edit_fn(report.read_text()))
        _git(["add", "-A"], cwd=tmp)
        _git(["commit", "-q", "-m", message], cwd=tmp, author=_COMMITTEE_AUTHOR)
        _git(["push", "-q", "origin", _BRANCH], cwd=tmp)
        return _git(["rev-parse", "HEAD"], cwd=tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
