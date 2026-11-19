"""rendering.kept_render: a rendered report is kept until what it is rendered
from changes — a file of its session or of a study it is composed of, its
report definition, the code."""

import json
import threading

import pytest

from rendering import kept_render as kr

REPORT = "DTXSID0000555"


@pytest.fixture
def report(sessions_dir):
    (sessions_dir / REPORT).mkdir()
    (sessions_dir / REPORT / "studies.json").write_text(json.dumps({"rat": f"{REPORT}_rat"}))
    (sessions_dir / f"{REPORT}_rat").mkdir()
    (sessions_dir / f"{REPORT}_rat" / "bm2_body-weight.json").write_text("{}")
    return sessions_dir


def _builder(text="page"):
    calls = []

    def build():
        calls.append(1)
        return f"{text} {len(calls)}"
    return build, calls


def test_the_copy_is_served_until_something_it_was_rendered_from_changes(report):
    build, calls = _builder()
    assert kr.kept(REPORT, "bookshelf.html", build) == ("page 1", False)
    assert kr.kept(REPORT, "bookshelf.html", build) == ("page 1", True)
    assert len(calls) == 1
    # A study of the report changes: the next request renders again.
    (report / f"{REPORT}_rat" / "bm2_body-weight.json").write_text('{"approved": true}')
    assert kr.kept(REPORT, "bookshelf.html", build) == ("page 2", False)
    # A new file in the report's own session.
    (report / REPORT / "background.json").write_text("{}")
    assert kr.kept(REPORT, "bookshelf.html", build) == ("page 3", False)
    assert kr.kept(REPORT, "bookshelf.html", build) == ("page 3", True)


def test_what_no_render_reads_does_not_count(report):
    build, calls = _builder()
    kr.kept(REPORT, "bookshelf.html", build)
    for folder in ("history", "narrative_runs", "preview"):
        (report / REPORT / folder).mkdir()
        (report / REPORT / folder / "x.json").write_text("{}")
    assert kr.kept(REPORT, "bookshelf.html", build)[1] is True and len(calls) == 1


def test_the_code_and_the_variant_count(report, monkeypatch):
    build, calls = _builder()
    kr.kept(REPORT, "bookshelf.html", build, variant="a")
    assert kr.kept(REPORT, "bookshelf.html", build, variant="b")[1] is False
    monkeypatch.setattr(kr, "_code_stamp", "other code")
    assert kr.kept(REPORT, "bookshelf.html", build, variant="b")[1] is False
    assert len(calls) == 3


def test_bytes_are_kept_as_bytes_and_a_failure_is_not_kept(report):
    assert kr.kept(REPORT, "report.docx", lambda: b"PK\x03\x04") == (b"PK\x03\x04", False)
    assert kr.kept(REPORT, "report.docx", lambda: b"other") == (b"PK\x03\x04", True)
    assert kr.kept(REPORT, "report.pdf", lambda: None) == (None, False)
    assert kr.kept(REPORT, "report.pdf", lambda: b"%PDF") == (b"%PDF", False)

    def refused():
        raise RuntimeError("run Process again")
    with pytest.raises(RuntimeError):
        kr.kept(REPORT, "other.html", refused)
    assert kr.kept(REPORT, "other.html", lambda: "now") == ("now", False)


def test_a_change_during_the_render_is_not_hidden(report):
    """The copy is kept under the fingerprint taken before the render."""
    def build():
        (report / REPORT / "summary.json").write_text("{}")  # changed while rendering
        return "rendered before the change was read"
    kr.kept(REPORT, "bookshelf.html", build)
    assert kr.kept(REPORT, "bookshelf.html", lambda: "again") == ("again", False)


def test_two_requests_render_once(report):
    started, release, calls = threading.Event(), threading.Event(), []

    def build():
        calls.append(1)
        started.set()
        release.wait(5)
        return "page"
    out = []
    first = threading.Thread(target=lambda: out.append(kr.kept(REPORT, "bookshelf.html", build)))
    first.start()
    started.wait(5)
    second = threading.Thread(target=lambda: out.append(kr.kept(REPORT, "bookshelf.html", build)))
    second.start()
    release.set()
    first.join(5)
    second.join(5)
    assert len(calls) == 1 and sorted(o[1] for o in out) == [False, True]
