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
from jats_stylecheck import STYLECHECKER_DIR, stylecheck
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
