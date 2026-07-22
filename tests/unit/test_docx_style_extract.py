r"""
Tests for docx_style_extract — the bootstrap extractor that reads a Word
template's styles + page geometry back into the pipeline's `styles` mapping.

The load-bearing property is the ROUND TRIP: styling applied by docx_generator
must be readable back by the extractor into a config that (a) validates as a
drop-in styles.yaml and (b) re-drives generation to the same fonts/sizes. That
closes the loop "design in Word → extract → drive all three surfaces."
"""

import io
import os
import tempfile
import zipfile
from pathlib import Path

import pytest
from docx import Document

import docx_style_extract as dse
from docx_generator import generate_docx
from document_config import _parse_styles_yaml
from report_data import scaffold_report_data


@pytest.fixture(scope="module")
def generated_docx_path() -> str:
    """A docx generated with the default reference styling, written to disk."""
    data = scaffold_report_data(chemical_name="T", casrn="1-1-1", dtxsid="X")
    raw = generate_docx(data)
    fd, path = tempfile.mkstemp(suffix=".docx")
    os.write(fd, raw)
    os.close(fd)
    yield path
    os.unlink(path)


def test_extract_returns_the_three_layers(generated_docx_path):
    cfg = dse.extract_styles(generated_docx_path)
    assert set(cfg) <= {"defaults", "types", "document"}
    assert "defaults" in cfg and "document" in cfg


def test_defaults_capture_the_body_font(generated_docx_path):
    cfg = dse.extract_styles(generated_docx_path)
    # The literal `font` key (not font_family) — names are literal on every surface.
    assert cfg["defaults"]["font"] == "Times New Roman"
    assert cfg["defaults"]["font_size"] == "12pt"


def test_types_capture_heading_font_and_size(generated_docx_path):
    cfg = dse.extract_styles(generated_docx_path)
    # Heading 1 → the level-1 body types at Arial Bold 17pt.
    narrative = cfg["types"]["narrative"]
    assert narrative["font"] == "Arial"
    assert narrative["font_size"] == "17pt"
    assert narrative["weight"] == "bold"


def test_document_layer_captures_page_and_margins(generated_docx_path):
    cfg = dse.extract_styles(generated_docx_path)
    doc = cfg["document"]
    assert doc["page_width"] == "8.5in"
    assert doc["page_height"] == "11in"
    assert doc["margin_left"] == "1in"
    assert doc["default_font"] == "Times New Roman"


def test_extracted_config_validates_as_styles_yaml(generated_docx_path):
    """The extractor output must be a drop-in styles.yaml (validates loudly)."""
    cfg = dse.extract_styles(generated_docx_path)
    yaml_text = dse.to_yaml(cfg)
    validated = _parse_styles_yaml(yaml_text)   # raises on any bad value/shape
    assert "defaults" in validated
    assert "document" in validated


def test_round_trip_redrives_generation(generated_docx_path):
    """
    Feed the extracted config back as data['layout_style'] → regenerate → the
    base fonts/sizes must match the source template. Closes the design loop.
    """
    cfg = dse.extract_styles(generated_docx_path)
    data = scaffold_report_data(chemical_name="T", casrn="1-1-1", dtxsid="X")
    data["layout_style"] = cfg
    doc = Document(io.BytesIO(generate_docx(data)))
    from docx.shared import Pt
    assert doc.styles["Normal"].font.name == "Times New Roman"
    assert doc.styles["Normal"].font.size == Pt(12)
    # Page geometry survived the round trip through the `document` layer.
    assert round(doc.sections[0].page_width.inches, 2) == 8.5


def test_to_yaml_wraps_under_styles_key(generated_docx_path):
    cfg = dse.extract_styles(generated_docx_path)
    yaml_text = dse.to_yaml(cfg)
    assert yaml_text.startswith("styles:")


def _repackage_as_dotx(docx_path: str, out_path: str) -> None:
    """Flip a .docx's main content-type to template.main so it reads as a .dotx.

    A .dotx is the same OPC package with one content-type string changed — this
    mirrors what Word writes on Save-As-Template, so the extractor must accept it.
    """
    with zipfile.ZipFile(docx_path) as zin, \
            zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "[Content_Types].xml":
                data = data.replace(
                    b"wordprocessingml.document.main+xml",
                    b"wordprocessingml.template.main+xml",
                )
            zout.writestr(item, data)


def test_extracts_from_a_dotx_template(generated_docx_path, tmp_path):
    """A .dotx (template content-type) extracts the same core facts as a .docx.

    python-docx rejects template.main directly; the extractor normalizes the
    content-type in memory so customers can author the look as a Word template.
    """
    dotx = tmp_path / "template.dotx"
    _repackage_as_dotx(generated_docx_path, str(dotx))
    cfg = dse.extract_styles(str(dotx))
    assert cfg["defaults"]["font"] == "Times New Roman"
    assert cfg["document"]["page_width"] == "8.5in"
    # And it still validates as a drop-in styles.yaml.
    _parse_styles_yaml(dse.to_yaml(cfg))


def test_cli_writes_yaml(generated_docx_path, tmp_path):
    out = tmp_path / "styles.yaml"
    rc = dse._main([generated_docx_path, "-o", str(out)])
    assert rc == 0
    text = out.read_text()
    assert "styles:" in text and "Times New Roman" in text


# ---------------------------------------------------------------------------
# Title-page style family — the NTP `1-NN` styles → the title_page role layer.
# Exercised against the reverse-engineered NTP template (which carries the real
# 1-NN family + Base_Heading/Base_Text parents); the generated scaffold docx
# does NOT have these styles.
# ---------------------------------------------------------------------------

_NTP_DOTX = (
    Path(__file__).resolve().parents[2]
    / "assets" / "templates" / "NIEHS-report-style-bordered.dotx"
)


@pytest.fixture(scope="module")
def ntp_template_cfg() -> dict:
    if not _NTP_DOTX.exists():
        pytest.skip(f"NTP template not present: {_NTP_DOTX}")
    return dse.extract_styles(str(_NTP_DOTX))


def test_title_page_family_extracted(ntp_template_cfg):
    """The extractor emits a title_page role layer from the NTP 1-NN family."""
    tp = ntp_template_cfg.get("title_page")
    assert tp, "no title_page layer extracted"
    # The roles our title-page node emits should all be present.
    for role in ("report_title", "publisher_name", "publication_date",
                 "report_number", "issn"):
        assert role in tp, f"missing role {role!r}"


def test_report_title_resolves_through_basedon(ntp_template_cfg):
    """
    `1-03_Report_Title` inherits its Arial font from the parent `Base_Heading`.
    python-docx does NOT resolve basedOn, so this proves the extractor's
    _resolved_style_props walk works: the title comes out Arial Bold 20pt center.
    """
    title = ntp_template_cfg["title_page"]["report_title"]
    assert title["font"] == "Arial"       # inherited from Base_Heading, not on the child
    assert title["font_size"] == "20pt"
    assert title["weight"] == "bold"
    assert title["align"] == "center"


def test_title_page_layer_validates_as_styles_yaml(ntp_template_cfg):
    """The extracted title_page layer is a drop-in styles.yaml (validates loudly)."""
    validated = _parse_styles_yaml(dse.to_yaml(ntp_template_cfg))
    assert "title_page" in validated
    # Every extracted role is a known TITLE_PAGE_ROLE (else validation would raise).
    import layout_style
    for role in validated["title_page"]:
        assert role in layout_style.TITLE_PAGE_ROLES


def test_resolved_style_props_walks_parent_chain(ntp_template_cfg):
    """Directly: a child style with no own font inherits the parent's."""
    doc = dse._open_word(str(_NTP_DOTX))
    child = doc.styles["1-03_Report_Title"]
    # python-docx alone returns None (the font lives on Base_Heading)...
    assert child.font.name is None
    # ...but the resolved walk recovers it.
    resolved = dse._resolved_style_props(child)
    assert resolved.get("font") == "Arial"
