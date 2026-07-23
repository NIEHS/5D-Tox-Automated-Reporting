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


# ---------------------------------------------------------------------------
# Coverage diagnostic — a day-one read on how well a NEW template matches the
# style maps, turning the silent KeyError-skip into an explicit found/missing
# report.  Exercised against the NTP template the maps were built for (all
# present) so it also guards the maps against drift.
# ---------------------------------------------------------------------------

def test_extract_reads_all_caps_as_text_transform():
    """w:caps on a style → text_transform: uppercase.  The NTP template's built-in
    `Title` style is all-caps (per ADR-0009); prove the extractor recovers it.
    (In this reverse-engineered .dotx the caps sit on `Title`, not on
    `1-03_Report_Title` — a hand-edit drift the real template may differ on; the
    read itself is what this guards.)"""
    if not _NTP_DOTX.exists():
        pytest.skip(f"NTP template not present: {_NTP_DOTX}")
    doc = dse._open_word(str(_NTP_DOTX))
    props = dse._extract_style_props(doc.styles["Title"])
    assert props.get("text_transform") == "uppercase"


def test_extract_reads_rpr_letter_spacing_not_ppr_space():
    """rPr <w:spacing w:val> → letter_spacing, and it is NOT confused with pPr
    <w:spacing w:before/after> (space_before/after) — the ADR-0009 trap.  Build a
    Normal style carrying BOTH and confirm they extract to the right keys."""
    from docx import Document as _Doc
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn as _qn

    doc = _Doc()
    st = doc.styles["Normal"]
    # rPr character spacing = 30 twips (1.5pt).
    rpr = st.element.get_or_add_rPr()
    csp = OxmlElement("w:spacing"); csp.set(_qn("w:val"), "30"); rpr.append(csp)
    # pPr paragraph space_before = 120 twips (6pt), written on the pPr <w:spacing
    # w:before> — the SAME element name, different parent, carrying space_before.
    ppr = st.element.get_or_add_pPr()
    psp = OxmlElement("w:spacing"); psp.set(_qn("w:before"), "120"); ppr.append(psp)

    props = dse._extract_style_props(st)
    assert props.get("letter_spacing") == "1.5pt"   # from rPr w:val
    assert props.get("space_before") == "6pt"        # from pPr w:before
    # The two came from different elements — neither leaked into the other.


def test_letter_spacing_round_trips_through_generate_extract(tmp_path):
    """Design→extract→re-drive loop for letter_spacing (absolute twips)."""
    from docx import Document as _Doc
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn as _qn

    data = scaffold_report_data(chemical_name="T", casrn="1-1-1", dtxsid="X")
    doc = _Doc(io.BytesIO(generate_docx(data)))
    rpr = doc.styles["Normal"].element.get_or_add_rPr()
    el = OxmlElement("w:spacing"); el.set(_qn("w:val"), "20"); rpr.append(el)  # 1pt
    out = tmp_path / "ls.docx"
    doc.save(str(out))
    cfg = dse.extract_styles(str(out))
    assert cfg["defaults"].get("letter_spacing") == "1pt"


def test_text_transform_round_trips_through_generate_extract(tmp_path):
    """Generate a docx whose Normal style is all-caps, extract, and confirm the
    key comes back — the load-bearing design→extract→re-drive loop for the key."""
    from docx import Document as _Doc
    data = scaffold_report_data(chemical_name="T", casrn="1-1-1", dtxsid="X")
    raw = generate_docx(data)
    doc = _Doc(io.BytesIO(raw))
    doc.styles["Normal"].font.all_caps = True
    out = tmp_path / "caps.docx"
    doc.save(str(out))
    cfg = dse.extract_styles(str(out))
    assert cfg["defaults"].get("text_transform") == "uppercase"


def test_coverage_finds_all_expected_styles_in_ntp_template():
    if not _NTP_DOTX.exists():
        pytest.skip(f"NTP template not present: {_NTP_DOTX}")
    report = dse.coverage_report(str(_NTP_DOTX))
    # The template the maps were reverse-engineered from ⇒ every expected present.
    assert report["missing"] == 0
    assert report["found"] == report["total"]
    names = {r["style"] for r in report["expected"]}
    assert {"Normal", "Header", "Heading 1", "1-03_Report_Title"} <= names
    # It surfaces the rest of the NTP library as mapping candidates.
    assert len(report["unmapped_with_props"]) > 50


def test_coverage_reports_missing_expected_styles(generated_docx_path):
    """The generated scaffold docx has Normal/Heading but NOT the NTP 1-NN family,
    so those roles report missing — the exact signal a mismatched new template
    would give."""
    report = dse.coverage_report(generated_docx_path)
    by_name = {r["style"]: r for r in report["expected"]}
    assert by_name["Normal"]["present"] is True
    assert by_name["1-03_Report_Title"]["present"] is False
    assert report["missing"] > 0


def test_format_coverage_renders_marks(generated_docx_path):
    text = dse.format_coverage(dse.coverage_report(generated_docx_path))
    assert "expected styles present" in text
    assert "MISSING" in text  # the absent 1-NN roles show the missing mark


def test_coverage_cli_flag(generated_docx_path, capsys):
    rc = dse._main([generated_docx_path, "--coverage"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "style coverage" in out


# ---------------------------------------------------------------------------
# Vocabulary generation — a Word template's named-style graph → a vocabulary
# (the descriptive-markup design system).  Exercised against a REAL example doc
# (the reverse-engineered .dotx lacks the used-body paragraphs the used_only
# scope walks), and falls back to the .dotx skeleton when examples are absent.
# ---------------------------------------------------------------------------

_NTP_EXAMPLE = next(
    iter(sorted((Path(__file__).resolve().parents[2] / "examples").glob("*.docx"))),
    None,
)


def _vocab_source() -> str:
    if _NTP_EXAMPLE is not None and _NTP_EXAMPLE.exists():
        return str(_NTP_EXAMPLE)
    if _NTP_DOTX.exists():
        return str(_NTP_DOTX)
    pytest.skip("no NTP example or template present")


def test_generate_vocabulary_shape():
    vocab = dse.generate_vocabulary(_vocab_source())
    assert vocab["vocabulary"] == "ntp-report"
    assert vocab["extends"] == "base"
    assert isinstance(vocab["types"], dict) and vocab["types"]


def test_generated_report_title_is_a_delta_specializing_a_root():
    """report_title emits ONLY its delta (no inherited Arial) and specializes the
    base_heading root — the specialization GRAPH is preserved, not flattened."""
    types = dse.generate_vocabulary(_vocab_source())["types"]
    rt = types.get("report_title")
    if rt is None:
        pytest.skip("report_title style not in this source")
    assert rt["specializes"] == "base_heading"
    # 20pt is the delta; Arial is inherited (NOT restated on the child).
    assert rt["style"]["font_size"] == "20pt"
    assert "font" not in rt["style"]
    assert rt["bind"]["docx"] == "1-03_Report_Title"


def test_generated_roots_link_into_base_vocabulary():
    """The NTP roots (Base_Text/Base_Heading/Normal) specialize the neutral base
    types so the whole graph resolves through vocab/base.yaml."""
    types = dse.generate_vocabulary(_vocab_source())["types"]
    # At least one root must bridge to base; which depends on what the source uses.
    bridges = {t.get("specializes") for t in types.values()}
    assert {"heading", "block", "text"} & bridges, "no NTP root bridged to base"


def test_used_only_scope_is_smaller_than_full():
    src = _vocab_source()
    used = dse.generate_vocabulary(src, used_only=True)["types"]
    full = dse.generate_vocabulary(src, used_only=False)["types"]
    assert len(used) <= len(full)


def test_generated_vocabulary_resolves_through_vocabulary_module(tmp_path):
    """End to end: generate → write → load_vocabulary (with the shipped base) →
    resolve report_title to the reference look with NO line spacing."""
    import vocabulary as V

    vocab_dict = dse.generate_vocabulary(_vocab_source())
    if "report_title" not in vocab_dict["types"]:
        pytest.skip("report_title not in this source")
    # Load via the module's injectable loader: base from disk, ntp from memory.
    def loader(name):
        if name == "base":
            return V._read_vocab_file("base")
        return vocab_dict
    vocab = V.load_vocabulary("ntp-report", _loader=loader)
    style = V.resolve_type_style(vocab, "report_title")
    assert style["font"] == "Arial"        # inherited through the chain
    assert style["font_size"] == "20pt"
    assert "line_height" not in style


def test_emit_vocabulary_cli(tmp_path):
    out = tmp_path / "vocab.yaml"
    rc = dse._main([_vocab_source(), "--emit-vocabulary", "-o", str(out)])
    assert rc == 0
    text = out.read_text()
    assert "vocabulary: ntp-report" in text
    assert "specializes:" in text


# ---------------------------------------------------------------------------
# PDF / converter contamination detection in the coverage diagnostic.
# ---------------------------------------------------------------------------

def test_classify_contamination_catches_converter_names():
    classes = dse._classify_contamination({"CM14", "Pa2", "0-03_Paragraph", "Normal"})
    assert classes["converter"] == ["CM14", "Pa2"]
    assert "0-03_Paragraph" not in classes["converter"]


def test_classify_contamination_catches_paste_collision_twins():
    # 'Title1' is a twin of 'Title'; 'Heading 1' is NOT (no base 'Heading').
    names = {"Title", "Title1", "Title2", "Heading 1", "No List", "No List11"}
    dup = dse._classify_contamination(names)["numbered_dup"]
    assert "Title1" in dup and "Title2" in dup
    assert "Heading 1" not in dup  # 'Heading ' base absent → a real numbered style


_EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"
_CONTAMINATED = _EXAMPLES_DIR / "NIEHS-12 1,2-DCB Publication Version Draft 03.20.2026.docx"
_CLEAN_FINAL = _EXAMPLES_DIR / "NIEHS-09 2,3-Benzofluorene_Final.docx"


def test_coverage_flags_contaminated_draft():
    if not _CONTAMINATED.exists():
        pytest.skip("contaminated draft example not present")
    report = dse.coverage_report(str(_CONTAMINATED))
    contam = report["contamination"]
    # The Acrobat CM##/Pa# fingerprint must be caught.
    assert contam["total"] >= 5
    assert any(c.startswith(("CM", "Pa")) for c in contam["converter"])
    # And the human-readable render must warn.
    text = dse.format_coverage(report)
    assert "PDF/paste-import" in text
    assert "converter" in text.lower()


def test_coverage_clean_final_has_no_contamination_warning():
    if not _CLEAN_FINAL.exists():
        pytest.skip("clean final example not present")
    report = dse.coverage_report(str(_CLEAN_FINAL))
    assert report["contamination"]["total"] == 0
    assert "PDF/paste-import" not in dse.format_coverage(report)


def test_contaminated_cruft_is_not_used_in_body():
    """The contamination is dead library cruft — no body paragraph applies it, so
    used_only extraction excludes it.  This is what makes it harmless."""
    if not _CONTAMINATED.exists():
        pytest.skip("contaminated draft example not present")
    contam = dse.coverage_report(str(_CONTAMINATED))["contamination"]
    assert contam["used_in_body"] == []
