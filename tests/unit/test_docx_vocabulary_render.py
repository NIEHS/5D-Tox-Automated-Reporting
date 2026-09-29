"""
test_docx_vocabulary_render.py — the docx role-driven rendering path (ADR-0010
Phase 2).

When the data dict names a vocabulary, the generator (a) builds the vocabulary's
type graph as NATIVE Word paragraph styles (styleId = docx binding, basedOn = the
specialization parent), and (b) tags each role-bearing paragraph with that style
via pStyle — so the document carries the real NTP palette and inherits its
typography, with NO hardcoded per-role defaults.  Absent a vocabulary, the output
is the legacy path (Normal / Heading 1-3), unchanged.
"""

from io import BytesIO

import pytest
from docx import Document

from rendering.docx_generator import generate_docx
from rendering.report_data import scaffold_report_data


@pytest.fixture(scope="module")
def scaffold() -> dict:
    return scaffold_report_data(chemical_name="T", casrn="1-1-1", dtxsid="X")


def _open(raw: bytes) -> Document:
    return Document(BytesIO(raw))


def _with_vocab(scaffold: dict) -> dict:
    return {**scaffold, "vocabulary": "ntp-report"}


def _para(doc: Document, text_startswith: str):
    for p in doc.paragraphs:
        if p.text.strip().startswith(text_startswith):
            return p
    return None


# ---------------------------------------------------------------------------
# The vocabulary is built into styles.xml as native basedOn styles
# ---------------------------------------------------------------------------

def test_vocabulary_styles_are_built_with_basedon(scaffold):
    doc = _open(generate_docx(_with_vocab(scaffold)))
    names = {s.name for s in doc.styles}
    assert "1-03_Report_Title" in names
    assert "3-02a_Head1_NoNumber" in names
    assert "0-03_Paragraph" in names
    # basedOn mirrors the NTP graph (report_title → Base_Heading).
    assert doc.styles["1-03_Report_Title"].base_style.name == "Base_Heading"


def test_no_built_style_is_based_on_itself(scaffold):
    """A curated alias may reuse its parent's Word style name (both vocab types →
    one physical <w:style>).  The builder must NOT then set basedOn to itself — a
    self-reference Word can't resolve, which breaks the chain and drops the style
    to left/default rendering (the publisher-location bug)."""
    doc = _open(generate_docx(_with_vocab(scaffold)))
    for s in doc.styles:
        base = getattr(s, "base_style", None)  # numbering styles have none
        if base is not None:
            assert base.name != s.name, f"{s.name!r} is basedOn itself"


def test_publisher_location_resolves_centered(scaffold):
    """NTP Publisher Location inherits center alignment from 1-09_Publication_
    Department (not a broken self-basedOn) — the reported left/italic bug is gone."""
    import styling_export.docx_style_extract as dse
    doc = _open(generate_docx(_with_vocab(scaffold)))
    s = doc.styles["NTP Publisher Location"]
    assert s.base_style.name == "1-09_Publication_Department"
    props = dse._resolved_style_props(s)
    assert props.get("align") == "center"
    assert props.get("style") != "italic"


def test_built_report_title_resolves_through_chain(scaffold):
    import styling_export.docx_style_extract as dse
    doc = _open(generate_docx(_with_vocab(scaffold)))
    props = dse._resolved_style_props(doc.styles["1-03_Report_Title"])
    assert props["font"] == "Arial"        # inherited from Base_Heading
    assert props["font_size"] == "20pt"    # own delta
    assert props["align"] == "center"
    assert "line_height" not in props      # no line spacing → single (the title fix)


# ---------------------------------------------------------------------------
# Role-driven pStyle application
# ---------------------------------------------------------------------------

def test_title_paragraph_uses_native_role_style_with_vocab(scaffold):
    doc = _open(generate_docx(_with_vocab(scaffold)))
    title = _para(doc, "NIEHS Report on the")
    assert title is not None
    assert title.style.name == "1-03_Report_Title"


def test_section_heading_uses_native_role_style_with_vocab(scaffold):
    doc = _open(generate_docx(_with_vocab(scaffold)))
    bg = _para(doc, "Background")
    assert bg is not None
    assert bg.style.name == "3-02a_Head1_NoNumber"


def test_ntp_heading_styles_carry_outline_levels(scaffold):
    """The NTP heading styles come from the template base VERBATIM, carrying the
    reference's own outline levels: 3-03a_Head2 → 1 and 3-04a_Head3 → 2.  (The
    level-1 head 3-02a carries no explicit outlineLvl in the reference — it
    defaults via its basedOn chain — so we don't assert one for it.)  This
    replaces the earlier build-time stamping; the base is now the source."""
    from docx.oxml.ns import qn
    doc = _open(generate_docx(_with_vocab(scaffold)))
    expected = {
        "3-03a_Head2_NoNumber": "1",
        "3-04a_Head3_NoNumber": "2",
    }
    for name, want in expected.items():
        st = doc.styles[name]
        pPr = st.element.find(qn("w:pPr"))
        ol = pPr.find(qn("w:outlineLvl")) if pPr is not None else None
        assert ol is not None, f"{name} has no outlineLvl"
        assert ol.get(qn("w:val")) == want, f"{name} outlineLvl={ol.get(qn('w:val'))} != {want}"


def test_toc_field_collects_on_vocabulary_path(scaffold):
    """The TOC field is emitted regardless of styling path; with a vocabulary
    active, the collectable headings are the NTP role styles (now outline-marked),
    so the field will populate the same as the built-in Heading path."""
    from docx.oxml.ns import qn
    doc = _open(generate_docx(_with_vocab(scaffold)))
    instrs = [e.text for e in doc.element.body.findall(".//" + qn("w:instrText"))]
    assert any(i and i.strip().startswith("TOC") for i in instrs)


# ---------------------------------------------------------------------------
# No vocabulary → legacy path, unchanged
# ---------------------------------------------------------------------------

def test_no_vocabulary_key_uses_base_ntp_styles(scaffold):
    """With the template base present, a data dict with NO explicit `vocabulary`
    key now DEFAULTS to the NTP vocab (the base supplies the NTP style palette),
    so content resolves to the native NTP styles — not the built-in Normal/
    Heading fallback.  (The old no-key → legacy behavior only applies when the
    base asset is absent.)"""
    doc = _open(generate_docx(scaffold))  # no "vocabulary" key
    assert _para(doc, "NIEHS Report on the").style.name == "1-03_Report_Title"
    assert _para(doc, "Background").style.name == "3-02a_Head1_NoNumber"
    # The NTP role styles ARE present (they come from the template base).
    assert "1-03_Report_Title" in {s.name for s in doc.styles}


def test_unknown_vocabulary_falls_back_to_builtin_heading(scaffold):
    """A bad vocabulary name is swallowed (no role resolution), so handlers use
    the built-in Heading/Normal fallback — but the template base still supplies
    the full NTP style LIBRARY (the styles exist even though they're not applied
    by role)."""
    doc = _open(generate_docx({**scaffold, "vocabulary": "does-not-exist"}))
    assert _para(doc, "Background").style.name == "Heading 1"
    # The base's NTP styles are still present in the document.
    assert "1-03_Report_Title" in {s.name for s in doc.styles}
