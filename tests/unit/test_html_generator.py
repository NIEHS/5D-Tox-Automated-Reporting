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
from report_data import scaffold_report_data


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
    """
    The inner title page reproduces the NIEHS Report 10 (p2) layout:
    series prefix, structured study title (chemical + CASRN, strain,
    Gavage Studies), institutional block, and ISSN — centered, no rule.
    """
    html = generate_html(scaffold)
    assert 'class="title-block"' in html
    # Series prefix + study-type line.
    assert "NIEHS Report on the" in html
    assert "In Vivo Repeat Dose Biological Potency Study of" in html
    # Chemical with CASRN (the formal title-name), then strain + study type.
    assert "Perfluorohexanesulfonamide (CASRN 41997-13-1)" in html
    assert "in Sprague Dawley (Hsd:Sprague Dawley® SD®) Rats" in html
    assert "(Gavage Studies)" in html
    # Publisher block + ISSN + location.
    assert "National Institute of Environmental Health Sciences" in html
    assert "ISSN: 2768-5632" in html
    assert "Research Triangle Park, North Carolina, USA" in html
    # The old left-aligned rule under the title is gone.
    assert "border-bottom: 2px solid #d6d3cd" not in html


# ---------------------------------------------------------------------------
# Printed-page pagination (Paged.js)
# ---------------------------------------------------------------------------
# The preview paginates the continuous body into printed-page sheets via the
# Paged.js polyfill loaded inside the srcdoc.  These tests pin that the
# polyfill + @page geometry + page chrome are emitted; they can't exercise
# the actual on-screen layout (that needs a browser) — see the in-app
# verification step for that.

def test_full_document_loads_pagedjs_polyfill(scaffold):
    """The polyfill <script> must be present so the iframe paginates."""
    html = generate_html(scaffold)
    assert "paged.polyfill.js" in html
    # Emitted after the body content so the DOM is parsed before it runs.
    assert html.index("paged.polyfill.js") > html.index("<body>")


def test_full_document_sets_letter_page_geometry(scaffold):
    """@page rule must request US Letter at 1in margins (matches niehs.cls)."""
    html = generate_html(scaffold)
    assert "@page" in html
    assert "size: letter" in html
    assert "margin: 1in" in html


def test_full_document_has_page_number_and_running_header(scaffold):
    """Page chrome: a bottom page-number box and a top running-header box."""
    html = generate_html(scaffold)
    # Page number in the bottom margin box.
    assert "@bottom-center" in html
    assert "counter(page)" in html
    # Running header in the top margin box, carrying the full report title
    # (the dedicated "running_header" metadata field).
    assert "@top-center" in html
    header = scaffold.get("running_header") or scaffold.get("title", "5dToxReport")
    assert f'content: "{header}"' in html


def test_title_block_is_own_headerless_cover_page(scaffold):
    """
    The running header must begin at Foreword, not page 1 — matching the
    reference (NIEHS Report 10), whose cover + title pages carry no header.
    The title block is therefore put on its own named "cover" page that
    suppresses both header and page number, and forces a break after it.
    """
    html = generate_html(scaffold)
    # A dedicated cover @page that blanks both margin boxes.
    assert "@page cover" in html
    # The title block is assigned to it and breaks the page after itself.
    assert "page: cover" in html
    assert "break-after: page" in html
    # The old page-1-only suppression must be gone (it stranded Foreword's
    # first page without a header).
    assert "@page:first" not in html


def test_landscape_orientation_wraps_node(scaffold):
    """
    A node flagged landscape in data["orientations"] is wrapped in a
    .landscape-block, which the CSS assigns to the @page report-landscape
    (size: letter landscape) so Paged.js rotates that page.
    """
    data = {**scaffold, "orientations": {"bmd-summary": "landscape"}}
    html = generate_html(data)
    # The landscape page + its size are always defined in the CSS...
    assert "@page report-landscape" in html
    assert "size: letter landscape" in html
    # ...but the wrapper only appears for the flipped node.
    assert 'class="landscape-block"' in html


def test_portrait_default_has_no_landscape_block(scaffold):
    """With no orientations set, nothing is wrapped landscape."""
    html = generate_html(scaffold)
    assert 'class="landscape-block"' not in html


def test_landscape_flag_on_non_orientable_node_ignored(scaffold):
    """
    A landscape flag on a non-orientable node (prose) is ignored — the
    capability dictionary gates the wrap, so stale/invalid flags do nothing.
    """
    data = {**scaffold, "orientations": {"background": "landscape"}}
    html = generate_html(data)
    assert 'class="landscape-block"' not in html


def test_sections_have_scroll_anchors(scaffold):
    """
    Each walked node is preceded by a zero-height sec-<id> anchor so the
    TOC can scroll the full preview to a section (scrollPreviewToNode).
    """
    html = generate_html(scaffold)
    assert 'class="sec-anchor"' in html
    assert 'id="sec-background"' in html
    assert 'id="sec-foreword"' in html
    assert 'id="sec-bmd-summary"' in html


def test_fragment_preview_also_paginates(session_data):
    """Per the chosen scope, section-card fragments paginate too."""
    html = generate_html(session_data, section_filter="bmd-summary")
    assert "paged.polyfill.js" in html
    assert "@page" in html
    assert "size: letter" in html


def test_running_header_escaped_against_style_breakout():
    """
    The running header is injected into a <style> raw-text element.  A
    title containing "</style>" must NOT close the style element early —
    the "<" is rewritten to its CSS unicode escape.
    """
    data = {"title": 'Bad</style><script>alert(1)</script>'}
    html = generate_html(data)
    # The raw breakout sequence must not survive into the document.
    assert "</style><script>" not in html
    # The "<" of the title is CSS-escaped inside the @page content string.
    assert "\\00003c" in html


def test_roman_front_matter_arabic_body(scaffold):
    """
    Full document: front-matter pages are lower-roman; the body (Background
    onward) switches to arabic restarted at 1.  The body is wrapped in
    .report-mainmatter, which the CSS assigns to @page mainmatter.
    """
    html = generate_html(scaffold)
    # Default @page (front matter) numbers in roman.
    assert "counter(page, lower-roman)" in html
    # Body named page (arabic) + the wrapper that resets the counter.
    assert "@page mainmatter" in html
    assert 'class="report-mainmatter"' in html
    assert "counter-reset: page" in html
    # The body wrapper sits after the front matter and contains Background.
    assert html.index('class="report-mainmatter"') < html.index("<h2>Background</h2>")
    assert html.index("<h2>Foreword</h2>") < html.index('class="report-mainmatter"')


def test_fragment_page_numbers_are_arabic(scaffold):
    """
    A single-section fragment has no front-matter/body split, so it forces
    the page number back to arabic (overriding the roman default) and does
    not wrap a body.
    """
    html = generate_html(scaffold, section_filter="bmd-summary")
    assert "@page { @bottom-center { content: counter(page); } }" in html
    assert 'class="report-mainmatter"' not in html


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
        "background": {"paragraphs": ["A & B & C", "Foo <script>alert(1)</script>"]},
    }
    html = generate_html(data)
    # Original unescaped form must not appear
    assert "<script>" not in html
    # Escaped form must appear
    assert "A &amp; B &amp; C" in html
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
    from report_data import marshal_export_data
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
    from report_data import normalize_apical_section_for_render
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
