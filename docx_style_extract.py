r"""
docx_style_extract.py — bootstrap the styling vocabulary FROM a Word template.

The inverse of docx_generator's style application: open a `.docx` authored in
Word/LibreOffice and read its base styles + page geometry into the `styles`
mapping the rest of the pipeline already consumes (the {defaults, types,
instances, document} shape `document_config._parse_styles_yaml` validates and
`report_data._resolve_layout_config` feeds to all three renderers).

This is how a customer designs the report's look in Word — WYSIWYG — and has it
drive the LaTeX and HTML surfaces too, at the shared-vocabulary fidelity
(layout_style.LAYOUT_KEY_SCHEMA + DOCUMENT_KEY_SCHEMA — the ~20 typographic +
document-geometry keys).

SCOPE — buckets 1 + 2 only (see the design discussion):
  1. per-block typography — the Word STYLES Normal / Heading 1-3 / Header →
     the `defaults` + `types` layers.
  2. document geometry — the first section's page size, margins, header
     distance, and the base body/header fonts → the `document` layer.
Bucket 3 (table column widths, ToC dot-leaders, list numbering — Word's
COMPONENT geometry) is deliberately NOT extracted; it isn't part of the shared
vocabulary and stays per-surface. `extract_styles` logs what it skipped so the
omission is visible, never silent.

Font names are LITERAL on every surface (the decision for this feature): a
"Times New Roman" read here is written verbatim as the `font` key and used as-is
by docx, LaTeX (fontspec), and HTML — not mapped back to serif/sans/mono.

Read-only w.r.t. fonts: this reads a template's style *names* (family strings),
never glyph data, so it carries no font-licensing burden.

CLI:
    python -m docx_style_extract template.docx            # YAML to stdout
    python -m docx_style_extract template.docx -o out.yaml
"""

from __future__ import annotations

import io
import sys
import zipfile

from docx import Document
from docx.enum.text import WD_LINE_SPACING
from docx.shared import Emu

# python-docx opens .docx (document.main) but rejects .dotx (template.main).
# A template is the same OPC package with one content-type string changed, so we
# normalize it in memory to read a Word template the customer authored as .dotx.
_TEMPLATE_CT = b"wordprocessingml.template.main+xml"
_DOCUMENT_CT = b"wordprocessingml.document.main+xml"


def _open_word(path: str):
    """Open a .docx OR .dotx into a python-docx Document (template CT normalized)."""
    with zipfile.ZipFile(path) as zin:
        if _TEMPLATE_CT not in zin.read("[Content_Types].xml"):
            return Document(path)  # plain .docx — open directly
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "[Content_Types].xml":
                    data = data.replace(_TEMPLATE_CT, _DOCUMENT_CT)
                zout.writestr(item, data)
    buf.seek(0)
    return Document(buf)

# The Word STYLE name → the styles-config `types` node_type it maps to.  Normal
# is the document default (→ `defaults`), Header feeds the `document` layer's
# header font; the three Heading styles map to the heading-bearing catalog types
# that share a level.  We key on the built-in style names docx_generator emits.
_HEADING_STYLE_TO_TYPES: dict[str, list[str]] = {
    # Heading 1 → the level-1 body sections; Heading 2/3 → the nested groups.
    # These node_type names must exist in the component catalog (validated
    # downstream); we map to the ones docx_generator styles via _HEADING_STYLE_BY_LEVEL.
    "Heading 1": ["front-matter", "narrative", "heading-only", "appendix",
                  "bmd-summary", "genomics-section"],
    "Heading 2": ["narrative+tables"],
    "Heading 3": [],  # level-3 nodes inherit Heading 3 in Word; no distinct type today
}

# The NTP template's title-page style family → the title_page ROLE each maps to
# (layout_style.TITLE_PAGE_ROLES).  The style NAMES are the ICF/NTP `1-NN`
# convention (Word displays them with a space + underscores).  Only the roles
# that correspond to content OUR title-page node emits are mapped; the rest of
# the `1-NN` family (foreword/abstract/authors/peer-review) belongs to separate
# front-matter nodes and is intentionally not read here.
_TITLE_PAGE_STYLE_TO_ROLE: dict[str, str] = {
    "1-03_Report_Title": "report_title",
    "1-02_Report_Type": "report_type",
    "1-04_Report_Subtitle": "report_subtitle",
    "1-05_Publication_Date": "publication_date",
    "1-05a_Report-Number": "report_number",
    "1-05b_DOI": "doi",
    "1-05c_ISSN": "issn",
    "1-05d_NIH-Number": "nih_number",
    "1-01_Publisher_Name": "publisher_name",
    "1-06_Publication_Office": "publication_office",
    "1-07_Publication_Division": "publication_division",
    "1-08_Publication_Institute": "publication_institute",
    "1-09_Publication_Department": "publication_department",
    "1-26_Logo_Graphic": "logo_graphic",
}


# ---------------------------------------------------------------------------
# Length / color helpers — python-docx returns EMU Length objects and RGBColor
# ---------------------------------------------------------------------------

_EMU_PER_PT = 12700  # 1pt = 12700 EMU


def _emu_to_pt_str(length) -> "str | None":
    """A python-docx Length (EMU) → a 'Npt' string the vocabulary accepts, or None."""
    if length is None:
        return None
    pt = int(length) / _EMU_PER_PT
    # Trim trailing-zero noise: 12.0 → "12pt", 13.8 → "13.8pt".
    s = f"{pt:.2f}".rstrip("0").rstrip(".")
    return f"{s}pt"


def _emu_to_in_str(length) -> "str | None":
    """A python-docx Length (EMU) → an 'Nin' string (used for page/margin sizes)."""
    if length is None:
        return None
    inches = int(length) / 914400
    s = f"{inches:.3f}".rstrip("0").rstrip(".")
    return f"{s}in"


def _color_to_hex(font) -> "str | None":
    """A style font's color → '#rrggbb', or None when unset/auto/theme."""
    color = font.color
    if color is None or color.type is None:
        return None
    rgb = color.rgb
    if rgb is None:
        return None
    return f"#{str(rgb).lower()}"


# ---------------------------------------------------------------------------
# Per-style extraction → one resolved-style dict (the vocabulary's flat keys)
# ---------------------------------------------------------------------------

def _extract_style_props(style) -> dict:
    """Read one Word paragraph style into a vocabulary style dict (only the keys
    the style actually sets — absent props stay absent so layers stay sparse)."""
    out: dict = {}
    font = style.font
    if font.name:
        out["font"] = font.name           # literal family name (font wins)
    size = _emu_to_pt_str(font.size)
    if size:
        out["font_size"] = size
    if font.bold is True:
        out["weight"] = "bold"
    elif font.bold is False:
        out["weight"] = "normal"
    if font.italic is True:
        out["style"] = "italic"
    elif font.italic is False:
        out["style"] = "normal"
    color = _color_to_hex(font)
    if color:
        out["color"] = color

    pf = style.paragraph_format
    if pf.alignment is not None:
        out["align"] = {0: "left", 1: "center", 2: "right", 3: "justify"}.get(
            int(pf.alignment)
        )
        if out["align"] is None:
            del out["align"]
    # line_spacing is a float multiple only when the RULE is MULTIPLE/SINGLE/etc.;
    # an EMU value (exact spacing) can't be a unitless multiplier, so skip it.
    if isinstance(pf.line_spacing, float):
        out["line_height"] = pf.line_spacing
    sb = _emu_to_pt_str(pf.space_before)
    if sb:
        out["space_before"] = sb
    sa = _emu_to_pt_str(pf.space_after)
    if sa:
        out["space_after"] = sa
    indent = _emu_to_pt_str(pf.first_line_indent)
    if indent:
        out["first_line_indent"] = indent
    if pf.page_break_before is True:
        out["break_before"] = "page"
    if pf.keep_together is True:
        out["keep_together"] = True
    return out


def _resolved_style_props(style) -> dict:
    """Style props with the ``basedOn`` (parent) chain resolved.

    python-docx does NOT resolve inheritance: `style.font.name` on a style that
    inherits its font from a parent (via ``w:basedOn``) returns None.  The NTP
    title-page styles rely on this — e.g. `1-03_Report_Title` gets its Arial from
    the parent `Base_Heading` — so reading a child style alone loses the font.
    We walk `style.base_style` to the root, then merge base→child so the child's
    own props win.  Cycles are guarded by an id-visited set (defensive; Word
    doesn't emit cyclic basedOn)."""
    chain = []
    seen = set()
    s = style
    while s is not None and id(s) not in seen:
        seen.add(id(s))
        chain.append(s)
        s = s.base_style
    merged: dict = {}
    for anc in reversed(chain):          # root first, child overrides
        merged.update(_extract_style_props(anc))
    return merged


_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _docdefaults(styles) -> dict:
    """Read the document-wide default font/size from `w:docDefaults/rPrDefault`.

    Word stores the body baseline here (not on the Normal style) — the NIEHS
    templates leave Normal font-less and set Times New Roman 12pt in docDefaults.
    Returns {'font': ..., 'font_size': ...} with only the keys actually present.
    """
    out: dict = {}
    el = styles.element  # the <w:styles> lxml element python-docx already parsed
    rpr = el.find(f"{{{_W_NS}}}docDefaults/{{{_W_NS}}}rPrDefault/{{{_W_NS}}}rPr")
    if rpr is None:
        return out
    rfonts = rpr.find(f"{{{_W_NS}}}rFonts")
    if rfonts is not None:
        name = rfonts.get(f"{{{_W_NS}}}ascii")
        if name:
            out["font"] = name
    sz = rpr.find(f"{{{_W_NS}}}sz")
    if sz is not None and sz.get(f"{{{_W_NS}}}val"):
        # w:sz is in half-points.
        out["font_size"] = _emu_to_pt_str(int(sz.get(f"{{{_W_NS}}}val")) / 2 * _EMU_PER_PT)
    return out


def _extract_document(section, styles) -> dict:
    """Read page geometry + base fonts from the first section → the `document` layer."""
    doc_layer: dict = {}
    pw = _emu_to_in_str(section.page_width)
    ph = _emu_to_in_str(section.page_height)
    if pw:
        doc_layer["page_width"] = pw
    if ph:
        doc_layer["page_height"] = ph
    for key, val in (
        ("margin_top", section.top_margin),
        ("margin_bottom", section.bottom_margin),
        ("margin_left", section.left_margin),
        ("margin_right", section.right_margin),
        ("header_distance", section.header_distance),
    ):
        s = _emu_to_in_str(val)
        if s:
            doc_layer[key] = s
    # Base body font: prefer the Normal style, fall back to docDefaults (where
    # Word actually stores the body baseline when Normal is left font-less).
    normal_font = styles["Normal"].font
    dd = _docdefaults(styles)
    default_font = normal_font.name or dd.get("font")
    if default_font:
        doc_layer["default_font"] = default_font
    size = _emu_to_pt_str(normal_font.size) or dd.get("font_size")
    if size:
        doc_layer["default_font_size"] = size
    try:
        header_font = styles["Header"].font
        if header_font.name:
            doc_layer["header_font"] = header_font.name
        hsize = _emu_to_pt_str(header_font.size)
        if hsize:
            doc_layer["header_font_size"] = hsize
    except KeyError:
        pass
    return doc_layer


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_styles(docx_path: str) -> dict:
    """
    Read a Word template into a `styles` mapping (the {defaults, types, document}
    shape the pipeline validates + consumes).

    - `defaults` ← the Normal style (the document-wide baseline).
    - `types`    ← Heading 1/2/3 → the heading-bearing catalog node_types.
    - `document` ← first-section geometry + base body/header fonts.

    Only buckets 1+2 (typography + document geometry).  Bucket-3 component
    geometry (table/ToC/list) is NOT read; a note is logged to stderr so the
    omission is explicit.
    """
    doc = _open_word(docx_path)
    styles = doc.styles

    cfg: dict = {}

    # defaults ← Normal, merged over docDefaults (Word's body baseline lives in
    # docDefaults when Normal is font-less, as in the NIEHS templates).
    normal_props = _extract_style_props(styles["Normal"])
    defaults = {**_docdefaults(styles), **normal_props}
    if defaults:
        cfg["defaults"] = defaults

    # types ← each Heading style, fanned out to the node_types that use it.
    types: dict = {}
    for style_name, node_types in _HEADING_STYLE_TO_TYPES.items():
        try:
            props = _extract_style_props(styles[style_name])
        except KeyError:
            continue
        if not props:
            continue
        for nt in node_types:
            types[nt] = dict(props)
    if types:
        cfg["types"] = types

    # title_page ← the NTP `1-NN` title-page style family, keyed by role.  These
    # styles inherit from Base_Heading/Base_Text, so we resolve the basedOn chain
    # (python-docx does not) via _resolved_style_props.
    title_page: dict = {}
    for style_name, role in _TITLE_PAGE_STYLE_TO_ROLE.items():
        try:
            style = styles[style_name]
        except KeyError:
            continue
        props = _resolved_style_props(style)
        if props:
            title_page[role] = props
    if title_page:
        cfg["title_page"] = title_page

    # document ← first section geometry + base fonts.
    if doc.sections:
        doc_layer = _extract_document(doc.sections[0], styles)
        if doc_layer:
            cfg["document"] = doc_layer

    _log_skipped(doc)
    return cfg


def _log_skipped(doc) -> None:
    """Emit a stderr note naming the bucket-3 component geometry we did NOT read,
    so 'not extracted' is visible rather than a silent gap."""
    notes = []
    if doc.tables:
        notes.append(f"{len(doc.tables)} table(s): column widths / cell margins / borders")
    # ToC dot-leaders + list numbering live in styles we don't map.
    notes.append("ToC tab-stops (dot leaders), list indent/numbering")
    print(
        "docx_style_extract: extracted typography + document geometry only. "
        "NOT extracted (per-surface component geometry): " + "; ".join(notes),
        file=sys.stderr,
    )


def to_yaml(cfg: dict) -> str:
    """Serialize an extracted config as a `styles:`-wrapped YAML document."""
    import yaml
    return yaml.safe_dump({"styles": cfg}, sort_keys=False, default_flow_style=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main(argv: list[str]) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        prog="docx_style_extract",
        description="Extract a styles.yaml (typography + document geometry) from a Word template.",
    )
    parser.add_argument("docx", help="path to the .docx template")
    parser.add_argument("-o", "--out", help="write YAML here (default: stdout)")
    args = parser.parse_args(argv)

    cfg = extract_styles(args.docx)
    yaml_text = to_yaml(cfg)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(yaml_text)
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(yaml_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
