"""
test_jats_stylecheck.py — the PMC StyleChecker gate over the JATS surface.

ADR-0004 makes the NLM StyleChecker the export's golden oracle (ADR-0002
discipline): render a fixture report, validate against the authoritative
external validator, drive errors to zero.  This runs that validator fully
offline through lxml/libxslt (assets/stylechecker/, v5.48).

The JATS generator is still a TRACER BULLET (prose spine only), but the metadata
completeness work (ADR-0004 migration step 1: journal-meta, article-categories,
pub-date, article-type, fpage/elocation) is now BUILT, so the tracer output has
ZERO StyleChecker errors and KNOWN_GAPS is empty — the ratchet has become a plain
errors==0 gate.  It stays a ratchet by construction: if a future StyleChecker
rule or a generator change reintroduces a metadata error, add it to KNOWN_GAPS
only as a deliberate, documented triage step, then drive it back to empty.
"""

from pathlib import Path

import pytest

from jats_generator import generate_jats
from jats_stylecheck import (
    JATS_DTD_DIR,
    STYLECHECKER_DIR,
    dtd_validate,
    stylecheck,
)
from report_data import scaffold_report_data


# ADR-0004 migration step 1 (article-meta completeness) is now BUILT — the
# front-matter metadata layer in jats_generator (journal-meta, article-type,
# article-categories, pub-date, elocation-id) satisfies every StyleChecker
# metadata rule, so the baseline is empty and the ratchet is now a plain
# errors==0 gate.  A new gap would land here again only if a future rule (or a
# generator regression) reintroduced a metadata error to triage.
KNOWN_GAPS = frozenset()


@pytest.fixture(scope="module")
def scaffold() -> dict:
    # Same pure-scaffold fixture the html/latex renderer tests consume.
    return scaffold_report_data(
        chemical_name="Perfluorohexanesulfonamide",
        casrn="41997-13-1",
        dtxsid="DTXSID50469320",
    )


def test_stylechecker_assets_present():
    """The gate is worthless if the vendored transform isn't there."""
    for name in (
        "nlm-stylechecker.xsl",
        "stylecheck-match-templates.xsl",
        "stylecheck-helper-templates.xsl",
        "stylecheck-named-tests.xsl",
        "style-reporter.xsl",
    ):
        assert (STYLECHECKER_DIR / name).exists(), f"missing vendored {name}"


def test_no_stylechecker_errors_beyond_known_gaps(scaffold):
    """The prose spine must introduce no NEW StyleChecker errors.

    This is the real gate: it fails on any error outside the enumerated
    metadata baseline, so a regression in what the tracer *does* emit is caught
    immediately even while the metadata work is pending.
    """
    result = stylecheck(generate_jats(scaffold), style="article")
    unexpected = sorted(set(result.errors) - KNOWN_GAPS)
    assert not unexpected, (
        "New StyleChecker errors outside the documented ADR-0004 metadata "
        f"baseline:\n  " + "\n  ".join(unexpected)
    )


def test_known_gaps_are_not_stale(scaffold):
    """Keep the baseline honest: once a gap is fixed upstream, its entry must
    be deleted so the ratchet actually tightens (and eventually empties)."""
    result = stylecheck(generate_jats(scaffold), style="article")
    fixed = sorted(KNOWN_GAPS - set(result.errors))
    assert not fixed, (
        "These KNOWN_GAPS no longer occur — delete them from KNOWN_GAPS so the "
        f"gate ratchets toward zero:\n  " + "\n  ".join(fixed)
    )


def test_reporter_renders_html(scaffold):
    """The stage-2 style-reporter.xsl produces a versioned HTML report."""
    result = stylecheck(generate_jats(scaffold), style="article")
    html = result.html_report()
    assert "5.48" in html and "</html>" in html.lower()


# ---------------------------------------------------------------------------
# DTD content-model validation — the check the PMC Article Previewer runs and
# the StyleChecker does NOT (StyleChecker = tagging conformance, DTD = content
# model).  A real Previewer upload once failed with "body content does not
# follow the DTD" when a <table-wrap> was emitted after a <sec>; these guard
# that regression offline.
# ---------------------------------------------------------------------------

def test_jats_dtd_assets_present():
    """The DTD gate is worthless without the vendored module set."""
    assert (JATS_DTD_DIR / "JATS-archivearticle1-3.dtd").exists(), \
        "missing vendored JATS entry DTD"
    # A handful of the transitively-included modules must be present too, or the
    # parse silently degrades to "no DTD found".
    for name in ("JATS-common1-3.ent", "JATS-section1-3.ent", "mathml2.dtd"):
        assert (JATS_DTD_DIR / name).exists(), f"missing vendored DTD module {name}"


def _real_session_jats() -> str:
    from latex_export import load_session_data
    data = load_session_data(
        dtxsid="DTXSID50469320",
        chemical_name="Perfluorohexanesulfonamide",
        casrn="41997-13-1",
    )
    return generate_jats(data)


def test_scaffold_is_dtd_valid(scaffold):
    """The metadata + narrative spine validates against the real JATS 1.3 DTD."""
    errors = dtd_validate(generate_jats(scaffold))
    assert not errors, "scaffold JATS is not DTD-valid:\n  " + "\n  ".join(errors)


def test_real_session_is_dtd_valid():
    """The full report WITH data tables (the case that broke the Previewer:
    <table-wrap>s interleaved among <sec> siblings) must be DTD-valid — every
    table now sits in a proper nested <sec>, honoring body's (block)*, sec*."""
    errors = dtd_validate(_real_session_jats())
    assert not errors, "real-session JATS is not DTD-valid:\n  " + "\n  ".join(errors)


def test_dtd_validate_catches_body_ordering_violation():
    """Negative control: dtd_validate actually REJECTS a <table-wrap> after a
    <sec> in <body> — proving the guard has teeth (the exact Previewer error)."""
    bad = (
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE article PUBLIC "-//NLM//DTD JATS (Z39.96) Journal Archiving '
        'and Interchange DTD v1.3 20210610//EN" "JATS-archivearticle1-3.dtd">\n'
        '<article article-type="research-article" dtd-version="1.3"><front>'
        '<journal-meta><journal-id journal-id-type="publisher-id">x</journal-id>'
        '<journal-title-group><journal-title>T</journal-title></journal-title-group>'
        '<issn pub-type="epub">2768-5632</issn></journal-meta><article-meta>'
        '<article-categories><subj-group subj-group-type="heading"><subject>S'
        '</subject></subj-group></article-categories><title-group><article-title>'
        'T</article-title></title-group><pub-date date-type="pub" '
        'publication-format="electronic"><year>2026</year></pub-date>'
        '<elocation-id>e1</elocation-id></article-meta></front>'
        '<body><sec id="s1"><title>A</title><p>x</p></sec>'
        '<table-wrap id="T1"><label>Table 1</label><caption><p>c</p></caption>'
        '<table><tbody><tr><td>x</td></tr></tbody></table></table-wrap>'
        '</body></article>'
    )
    errors = dtd_validate(bad)
    assert any("body" in e for e in errors), (
        "dtd_validate should reject a <table-wrap> after a <sec> in <body>; "
        f"got: {errors}"
    )
