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

Everything runs against a tmp `root`, so no real .overleaf-standin/ /
.overleaf-clone/ are touched and the test needs no network or Overleaf.
"""

import subprocess

import pytest

import overleaf_sync as ovs


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
    clone = root / ".overleaf-clone" / _DTXSID
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
