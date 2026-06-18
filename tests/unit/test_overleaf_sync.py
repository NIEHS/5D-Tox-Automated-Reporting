r"""
test_overleaf_sync.py — the local Overleaf stand-in transport (ADR-0005).

What this proves
----------------
  - push_document mirrors the dev document bundle into a working clone and
    pushes it to a bare local "stand-in" remote, returning the baseline sha.
  - The app-internal sidecar (.rlm-sync.json) is NOT sent to the "Overleaf
    project"; the bundle files are.
  - simulate_overleaf_edit (a throwaway committee clone) edits one sentinel
    region and pushes it back.
  - pull_document brings that edit down to the app's clone — so the clone's
    report.tex now carries the committee edit while the baseline did not.
    That pair (baseline sha, edited clone) is exactly the reconciler's input.

Everything runs against a tmp `root`, so no real .repo-standin/ /
.repo-clone/ are touched and the test needs no network or Overleaf.
"""

import subprocess

import pytest

import roundtrip.transport as ovs


_DTXSID = "DTXSIDTEST"

# A minimal report.tex with two anchored regions — enough to exercise sentinel-
# scoped editing without generating a full report.
_REPORT = (
    "\\documentclass{niehs}\n\\begin{document}\n"
    "%% rlm:begin node summary\n"
    "ORIGINAL SUMMARY\n"
    "%% rlm:end node summary\n\n"
    "%% rlm:begin node background\n"
    "ORIGINAL BACKGROUND\n"
    "%% rlm:end node background\n"
    "\\end{document}\n"
)


@pytest.fixture
def doc_dir(tmp_path):
    """A minimal dev document bundle, incl. the app-internal sidecar."""
    d = tmp_path / "documents" / _DTXSID
    d.mkdir(parents=True)
    (d / "report.tex").write_text(_REPORT)
    (d / "niehs.cls").write_text("% stub class\n")
    (d / "README.md").write_text("# Overleaf bundle\n")
    (d / "figures").mkdir()
    (d / "figures" / ".gitkeep").write_text("")
    (d / ".rlm-sync.json").write_text('{"dtxsid": "%s"}\n' % _DTXSID)
    return d


def _edit_summary(text: str) -> str:
    """Stand in for a committee edit inside the 'summary' sentinel region."""
    return text.replace("ORIGINAL SUMMARY", "COMMITTEE-EDITED SUMMARY")


def test_full_round_trip(tmp_path, doc_dir):
    root = tmp_path  # redirect stand-in + clone roots here

    # 1. App pushes the generated bundle → baseline in the stand-in remote.
    baseline = ovs.push_document(_DTXSID, doc_dir=doc_dir, root=root)
    assert baseline  # a sha

    # The bundle reached the clone; the app-internal sidecar did NOT.
    clone = root / ".repo-clone" / _DTXSID
    assert (clone / "report.tex").exists()
    assert (clone / "niehs.cls").exists()
    assert not (clone / ".rlm-sync.json").exists()

    # 2. Committee edits the 'summary' region in Overleaf and saves.
    edited = ovs.simulate_overleaf_edit(_DTXSID, _edit_summary, root=root)
    assert edited != baseline

    # 3. App pulls the edit back down.
    pulled_clone, head = ovs.pull_document(_DTXSID, root=root)
    assert head == edited

    # 4. The clone now carries the committee edit; background is untouched.
    report = ovs.read_clone_report(_DTXSID, root=root)
    assert "COMMITTEE-EDITED SUMMARY" in report
    assert "ORIGINAL SUMMARY" not in report
    assert "ORIGINAL BACKGROUND" in report

    # 5. The baseline revision still held the original — the diff the reconciler
    #    will consume is baseline..head.
    base_report = subprocess.run(
        ["git", "show", f"{baseline}:report.tex"],
        cwd=str(pulled_clone), capture_output=True, text=True,
    ).stdout
    assert "ORIGINAL SUMMARY" in base_report


def test_round_trip_reconciles_into_overrides(tmp_path, doc_dir):
    """The payoff: push -> committee edit -> pull -> reconcile writes the right
    override, attributing the edit to the 'summary' anchor (background untouched)."""
    import roundtrip.overrides as do

    root = tmp_path
    sessions = tmp_path / "sessions"  # keep the override store out of the real tree

    baseline = ovs.push_document(_DTXSID, doc_dir=doc_dir, root=root)
    ovs.simulate_overleaf_edit(_DTXSID, _edit_summary, root=root)
    ovs.pull_document(_DTXSID, root=root)

    summary = ovs.reconcile_from_clone(
        _DTXSID, baseline, root=root, sessions_dir=sessions,
    )
    assert summary["written"] == ["summary"]
    assert not summary["structural"]

    ov = do.get_override(_DTXSID, "summary", sessions_dir=sessions)
    assert "COMMITTEE-EDITED SUMMARY" in ov["latex_region"]
    # base_hash is the baseline region's hash → renderer reads "not stale".
    assert ov["base_hash"] == do.region_hash("ORIGINAL SUMMARY")
    # background had no edit → no override for it.
    assert do.get_override(_DTXSID, "background", sessions_dir=sessions) is None


def test_re_push_is_idempotent(tmp_path, doc_dir):
    root = tmp_path
    first = ovs.push_document(_DTXSID, doc_dir=doc_dir, root=root)
    # No document change → nothing new to commit, push is a no-op, same HEAD.
    again = ovs.push_document(_DTXSID, doc_dir=doc_dir, root=root)
    assert first == again


def test_push_requires_doc_dir(tmp_path):
    with pytest.raises(FileNotFoundError):
        ovs.push_document(_DTXSID, doc_dir=tmp_path / "missing", root=tmp_path)


def test_pull_before_push_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        ovs.pull_document(_DTXSID, root=tmp_path)


def _set_report(doc_dir, marker: str) -> None:
    """Rewrite the doc bundle's report.tex with a distinct summary marker."""
    (doc_dir / "report.tex").write_text(_REPORT.replace("ORIGINAL SUMMARY", marker))


def test_commit_local_accumulates_unpushed_commits(tmp_path, doc_dir):
    """ADR-0005 Am.3: repeated Commit Local (no Push between) must ACCUMULATE
    local commits, not silently discard the earlier ones.

    Regression for the `_ensure_clone` hard-reset bug: it ran
    `checkout -f -B main origin/main` on every commit_document, so a second
    Commit Local reset HEAD back to the pushed tip and the first un-pushed
    commit vanished (ahead stuck at 1 forever).
    """
    root = tmp_path

    # Establish a pushed baseline so origin/main exists (the precondition that
    # made the old hard-reset destructive).
    _set_report(doc_dir, "V1 SUMMARY")
    ovs.push_document(_DTXSID, doc_dir=doc_dir, root=root)

    # Two Commit Locals, no Push between them — each a distinct edit.
    _set_report(doc_dir, "V2 SUMMARY")
    r2 = ovs.commit_document(_DTXSID, doc_dir, root=root)
    assert r2["committed"] and r2["ahead"] == 1

    _set_report(doc_dir, "V3 SUMMARY")
    r3 = ovs.commit_document(_DTXSID, doc_dir, root=root)
    assert r3["committed"]
    # The payoff: BOTH local commits are unpushed and present.  Pre-fix this
    # was 1 — the V2 commit was reset away by the V3 Commit Local.
    assert r3["ahead"] == 2

    # And V2's content survives one commit back in history (not overwritten out).
    clone = root / ".repo-clone" / _DTXSID
    parent = subprocess.run(
        ["git", "show", "HEAD~1:report.tex"],
        cwd=str(clone), capture_output=True, text=True,
    ).stdout
    assert "V2 SUMMARY" in parent
    head = ovs.read_clone_report(_DTXSID, root=root)
    assert "V3 SUMMARY" in head


def test_commit_local_does_not_swallow_committee_edits(tmp_path, doc_dir):
    """Commit Local is documented "No network": it must NOT fetch the committee's
    advanced remote and base the local commit on top of it.  Doing so silently
    bypassed the Push reconcile-before-overwrite guard and buried unreconciled
    committee edits in our history.
    """
    root = tmp_path

    # Baseline keeps the default "ORIGINAL SUMMARY" so the committee edit below
    # has a region to rewrite.
    ovs.push_document(_DTXSID, doc_dir=doc_dir, root=root)

    # Committee edits in Overleaf and pushes → origin/main advances.
    committee_sha = ovs.simulate_overleaf_edit(_DTXSID, _edit_summary, root=root)

    # App does a local-only Commit Local.
    _set_report(doc_dir, "V2 SUMMARY")
    ovs.commit_document(_DTXSID, doc_dir, root=root)

    # The committee's commit must NOT be an ancestor of our new HEAD — Commit
    # Local stayed offline and based the commit on our own last commit, leaving
    # the committee edit for the explicit Pull+reconcile flow.  Pre-fix the
    # hard-reset onto origin/main made committee_sha an ancestor (and silently
    # clobbered the committee text with our render).
    clone = root / ".repo-clone" / _DTXSID
    is_ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", committee_sha, "HEAD"],
        cwd=str(clone), capture_output=True, text=True,
    ).returncode
    assert is_ancestor != 0, "Commit Local must not fold in unreconciled committee edits"

    # The Push guard still sees the divergence and forces a Pull first.
    assert ovs.remote_head(_DTXSID, root=root) == committee_sha
