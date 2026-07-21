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


def test_cli_writes_yaml(generated_docx_path, tmp_path):
    out = tmp_path / "styles.yaml"
    rc = dse._main([generated_docx_path, "-o", str(out)])
    assert rc == 0
    text = out.read_text()
    assert "styles:" in text and "Times New Roman" in text
