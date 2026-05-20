"""
test_html_generator.py — Smoke tests for the in-app HTML preview renderer.

Verifies that html_generator.generate_html produces structurally valid,
self-contained HTML5 from the same data dict that drives the LaTeX
output.  The two generators are intentionally parallel — both walk
DOCUMENT_TREE and dispatch on node_type — so a missing handler or
broken table shape would be visible in either output.

What this proves
----------------
  - Document skeleton: doctype, head, body, inline CSS block.
  - Section headings render at correct h2/h3/h4 levels.
  - Apical, BMD-summary, and genomics tables emit semantic <table>
    elements with <caption>, <thead>, <tbody>.
  - n-row and sex-separator rows carry the CSS classes the inline
    stylesheet hooks on.
  - section_filter restricts the output to the requested subtree.
  - Special characters in narrative text are HTML-escaped.

What this does NOT prove
------------------------
  - That the rendering matches what Overleaf will compile from the
    parallel .tex output pixel-for-pixel — that's not the contract.
    The contract is "same data, same structure, same node types".
"""

from pathlib import Path

import pytest

from html_generator import generate_html
from latex_export import load_session_data
from report_pdf import scaffold_report_data


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def scaffold() -> dict:
    """Pure scaffold data — same fixture latex tests use."""
    return scaffold_report_data(
        chemical_name="Perfluorohexanesulfonamide",
        casrn="41997-13-1",
        dtxsid="DTXSID50469320",
    )


@pytest.fixture(scope="module")
def session_data() -> dict:
    """Real DTXSID50469320 session data overlayed on the scaffold."""
    return load_session_data(
        dtxsid="DTXSID50469320",
        chemical_name="Perfluorohexanesulfonamide",
        casrn="41997-13-1",
    )


# ---------------------------------------------------------------------------
# Document skeleton
# ---------------------------------------------------------------------------

def test_full_document_has_doctype_and_skeleton(scaffold):
    """Output must be a complete HTML5 document an iframe srcdoc can render."""
    html = generate_html(scaffold)
    assert html.startswith("<!DOCTYPE html>")
    assert "<html" in html
    assert "<head>" in html
    assert "<body>" in html
    assert "</html>" in html


def test_inline_css_is_embedded(scaffold):
    """
    The iframe srcdoc is sandboxed from the parent page's style.css, so
    the renderer must ship its own CSS inline.
    """
    html = generate_html(scaffold)
    assert "<style>" in html
    assert "table.niehstable" in html
    assert ".pending" in html


def test_title_block_present(scaffold):
    """Title block at the top with chemical name in the metadata."""
    html = generate_html(scaffold)
    assert 'class="title-block"' in html
    assert "Perfluorohexanesulfonamide" in html


# ---------------------------------------------------------------------------
# Section headings
# ---------------------------------------------------------------------------

def test_level_1_nodes_emit_h2(scaffold):
    """DocNode.level == 1 → <h2> (h1 reserved for the title block)."""
    html = generate_html(scaffold)
    assert "<h2>Background</h2>" in html
    assert "<h2>Summary</h2>" in html
    assert "<h2>Materials and Methods</h2>" in html


def test_level_2_nodes_emit_h3(scaffold):
    """DocNode.level == 2 → <h3>."""
    html = generate_html(scaffold)
    assert "<h3>Study Design</h3>" in html
    assert "<h3>Animal Condition, Body Weights, and Organ Weights</h3>" in html


def test_level_3_nodes_emit_h4(scaffold):
    """DocNode.level == 3 → <h4>."""
    html = generate_html(scaffold)
    assert "<h4>Clinical Observations</h4>" in html
    assert "<h4>RNA Isolation, Library Creation, and Sequencing</h4>" in html


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

def test_bmd_summary_table_with_real_session(session_data):
    """
    DTXSID50469320 has 28 apical endpoints in its BMD summary.  The
    HTML output must carry that exact row count.
    """
    html = generate_html(session_data, section_filter="bmd-summary")
    assert "<table" in html
    assert "<caption>Table" in html
    # The endpoints all live in tbody as <tr> rows.  Count the rows.
    tbody_start = html.find("<tbody>")
    tbody_end = html.find("</tbody>", tbody_start)
    assert tbody_start > 0 and tbody_end > tbody_start
    tbody = html[tbody_start:tbody_end]
    assert tbody.count("<tr>") == 28


def test_apical_table_uses_niehstable_class(session_data):
    """All Results-section tables get class=\"niehstable\" so the CSS hits."""
    html = generate_html(session_data, section_filter="animal-condition")
    assert 'class="niehstable"' in html


def test_apical_table_marks_sex_separator_and_n_rows(session_data):
    """
    Sex-separator rows and n-rows get specific CSS class hooks so
    the stylesheet can render them distinctly without inline styles.
    """
    html = generate_html(session_data, section_filter="animal-condition")
    assert 'class="sex-separator"' in html
    assert 'class="n-row"' in html


def test_genomics_section_emits_per_organ_sex_h4(session_data):
    """Gene-set + gene tables each get their own (organ, sex) h4 header."""
    html = generate_html(session_data, section_filter="gene-sets")
    assert "<h4>Liver, Male</h4>" in html or "<h4>Liver, Female</h4>" in html


# ---------------------------------------------------------------------------
# section_filter
# ---------------------------------------------------------------------------

def test_section_filter_strips_other_sections(scaffold):
    """A fragment-compile must omit everything outside the requested subtree."""
    html = generate_html(scaffold, section_filter="bmd-summary")
    # bmd-summary content present
    assert "Apical Endpoint Benchmark Dose Summary" in html
    # Other top-level sections absent
    assert "Materials and Methods" not in html
    assert "Foreword" not in html
    # Title block absent (no full-document skeleton)
    assert 'class="title-block"' not in html


def test_section_filter_unknown_id_returns_stub(scaffold):
    """An unknown id renders a polite stub fragment, not an exception."""
    html = generate_html(scaffold, section_filter="not-a-real-id")
    assert "<!DOCTYPE html>" in html
    assert "No section found" in html


# ---------------------------------------------------------------------------
# Special-character escaping
# ---------------------------------------------------------------------------

def test_special_characters_are_html_escaped():
    """
    Ampersands, angle brackets, and quotes in narrative content must
    be escaped so they don't corrupt the document structure.
    """
    data = {
        "title": "X & Y <example>",
        "background": {"paragraphs": ["A & B & C", "Foo <script>alert(1)</script>"]},
    }
    html = generate_html(data)
    # Original unescaped form must not appear
    assert "X & Y <example>" not in html
    assert "<script>" not in html
    # Escaped form must appear
    assert "X &amp; Y &lt;example&gt;" in html
    assert "&lt;script&gt;" in html


# ---------------------------------------------------------------------------
# Regression: dict-by-dose values must not leak into cell columns
# ---------------------------------------------------------------------------
# Bug observed 2026-05-19: when the web UI POSTed apical_sections with
# row.values shaped as {dose: cell}, the renderers iterated the dict and
# emitted its KEYS (the dose strings) in every endpoint's cell columns —
# identical for every row.  Fixed by normalize_apical_section_for_render
# in marshal_export_data; this test pins that fix so it doesn't regress.

def test_apical_row_values_render_real_measurements_not_dose_keys():
    """
    Feed the renderer a row in the web-UI shape (values as dict-by-dose,
    label key 'label') and verify the rendered HTML carries the actual
    measurement strings, not the dose-string keys.
    """
    from report_pdf import marshal_export_data
    body = {
        "chemical_name": "TestChem",
        "casrn": "00-00-0",
        "dtxsid": "DTXSID00000000",
        "apical_sections": [
            {
                "platform": "Body Weight",
                "table_data": {
                    "Male": [
                        {
                            "label": "n",
                            "doses": [0.0, 1.0, 10.0],
                            "values": {"0": "10", "1": "5", "10": "5"},
                            "bmd": "NA", "bmdl": "NA", "is_n_row": True,
                        },
                        {
                            "label": "Day 5",
                            "doses": [0.0, 1.0, 10.0],
                            "values": {"0": "245.3", "1": "244.8", "10": "240.1"},
                            "bmd": "8.5", "bmdl": "3.6",
                        },
                    ],
                },
            },
        ],
    }
    data = marshal_export_data(body)
    html = generate_html(data, section_filter="table-body-weight")
    # The actual measurement strings must appear in the rendered HTML.
    assert "245.3" in html
    assert "244.8" in html
    assert "240.1" in html
    # The dose-string keys ("0", "1", "10") must NOT appear as cell values
    # of the Day-5 row.  Specifically the run "<td>0</td><td>1</td><td>10</td>"
    # is what the bug would produce — assert against that sequence.
    assert "<td>0</td><td>1</td><td>10</td>" not in html.replace(" ", "").replace(
        '<td class="', '<td '  # tolerate any sex-separator td-class noise
    )


def test_normalize_apical_section_is_idempotent():
    """Re-normalizing an already-normalized section is a no-op."""
    from report_pdf import normalize_apical_section_for_render
    sec = {
        "platform": "Body Weight",
        "table_data": {
            "Male": [
                {
                    "endpoint": "Day 5",
                    "doses": [0.0, 1.0, 10.0],
                    "values": ["245.3", "244.8", "240.1"],
                    "bmd": "8.5", "bmdl": "3.6", "is_n_row": False,
                },
            ],
        },
    }
    once = normalize_apical_section_for_render(sec)
    twice = normalize_apical_section_for_render(once)
    assert once["table_data"] == twice["table_data"]
    assert once["table_data"]["Male"][0]["values"] == ["245.3", "244.8", "240.1"]
