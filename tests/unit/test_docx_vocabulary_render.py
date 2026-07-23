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

from docx_generator import generate_docx
from report_data import scaffold_report_data


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
    import docx_style_extract as dse
    doc = _open(generate_docx(_with_vocab(scaffold)))
    s = doc.styles["NTP Publisher Location"]
    assert s.base_style.name == "1-09_Publication_Department"
    props = dse._resolved_style_props(s)
    assert props.get("align") == "center"
    assert props.get("style") != "italic"


def test_built_report_title_resolves_through_chain(scaffold):
    import docx_style_extract as dse
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


# ---------------------------------------------------------------------------
# No vocabulary → legacy path, unchanged
# ---------------------------------------------------------------------------

def test_no_vocabulary_uses_legacy_styles(scaffold):
    doc = _open(generate_docx(scaffold))  # no "vocabulary" key
    title = _para(doc, "NIEHS Report on the")
    bg = _para(doc, "Background")
    assert title.style.name == "Normal"      # legacy hardcoded-default path
    assert bg.style.name == "Heading 1"
    # And the NTP role styles are NOT built into a no-vocab document.
    assert "1-03_Report_Title" not in {s.name for s in doc.styles}


def test_unknown_vocabulary_falls_back_to_legacy(scaffold):
    # A bad vocabulary name is swallowed to the legacy path, not a hard error.
    doc = _open(generate_docx({**scaffold, "vocabulary": "does-not-exist"}))
    assert _para(doc, "Background").style.name == "Heading 1"
