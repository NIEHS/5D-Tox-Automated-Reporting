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

import shutil
import subprocess
import tempfile
from pathlib import Path

from latex_export import DOCUMENTS_DIR

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent

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


# ---------------------------------------------------------------------------
# Helpers (private)
# ---------------------------------------------------------------------------

def _git(args: "list[str]", cwd: Path, author: "tuple[str, str] | None" = None) -> str:
    """
    Run a git command in `cwd` and return its stdout (stripped).

    `author`, when given, sets committer + author identity for that single
    invocation via -c flags — deterministic and independent of global git
    config (which may be unset in CI).  Raises with captured stderr on failure.
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
    return result.stdout.strip()


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
# Public API
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


def push_document(
    dtxsid: str,
    *,
    doc_dir: "Path | None" = None,
    root: Path = _REPO_ROOT,
    message: str = "app: sync generated report",
) -> str:
    """
    Push the dev document bundle to the stand-in remote (the "send to Overleaf").

    Ensures the remote + working clone exist, mirrors documents/<dtxsid>/ into
    the clone, commits any change, and pushes.  Returns the pushed commit sha —
    the baseline the reconciler diffs pulled-back edits against.
    """
    standin = init_standin(dtxsid, root=root)
    doc_dir = doc_dir or (DOCUMENTS_DIR / dtxsid)
    if not doc_dir.exists():
        raise FileNotFoundError(
            f"No dev document at {doc_dir} — run sync_document({dtxsid!r}) first."
        )

    clone = _clone_path(dtxsid, root)
    if not (clone / ".git").exists():
        clone.mkdir(parents=True, exist_ok=True)
        _git(["init", "-q", "-b", _BRANCH], cwd=clone)
        _git(["remote", "add", "origin", str(standin)], cwd=clone)

    _mirror_bundle(doc_dir, clone)
    _git(["add", "-A"], cwd=clone)
    if _has_staged_changes(clone):
        _git(["commit", "-q", "-m", message], cwd=clone, author=_APP_AUTHOR)
    # -u sets upstream on the first push so later pull/push need no refspec.
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
