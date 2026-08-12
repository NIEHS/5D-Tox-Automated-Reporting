"""
cover_layouts.py — the cover / title-page layout catalog (the "building blocks"
that make a branded report cover).

Mirrors the design of ``chart_registry.ChartType`` / ``render_capabilities.
COMPONENT_CATALOG``: an unordered, frozen-dataclass registry keyed by
subtype-name, the SINGLE place that says "this is what a NIEHS 5D-Tox cover *is*".
It imports NOTHING from the renderers, so the dependency points one way
(renderer → here); LaTeX escaping and tikz stay in latex_generator, HTML escaping
in html_generator.  A ``cover`` / ``title-page`` node carries ``subtype``
(document_node.DocNode.subtype); the renderers look the layout up here and consume
its assets + palette + text builders + geometry instead of hardcoding them.

Everything reference-specific lives in ONE ``CoverLayout`` entry:
  - **assets**       — image files shipped into the bundle root (background, logo).
  - **palette**      — the brand colors (hex, no ``#``) the LaTeX cover emits as
                       ``\\definecolor``; the HTML cover reads the same values.
  - **institution_lines** — the header-band institution name (one line per entry).
  - **title_builder / publisher_builder** — data → the UNESCAPED text lines; each
                       renderer escapes for its own surface.  The single source of
                       truth for the title / publisher text on BOTH surfaces.
  - **metrics**      — surface-agnostic geometry in points, origin = top-left:
                       band height, background top, the accent-bar parallelogram
                       vertices, logo + text positions, title size/width, meta
                       positions.  The LaTeX cover turns these into tikz coords;
                       a light read, not a general layout interpreter.

Adding a second report type's cover = a new ``CoverLayout`` entry + its assets.
No renderer change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

# Static cover assets live under assets/ (resolved relative to this module, the
# REPO_ROOT idiom used by document_template.TEMPLATES_DIR / latex_export.CLASS_FILE).
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"


# ---------------------------------------------------------------------------
# The cover-layout record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CoverLayout:
    """One entry in the cover-layout catalog (a report type's branded cover)."""
    name: str
    # Image basenames shipped at the bundle ROOT (the cover's \includegraphics
    # references them bare); resolved from ASSETS_DIR when the bundle is built.
    assets: tuple[str, ...] = ()
    # Brand colors as 6-digit hex WITHOUT '#'.  Keys are referenced by the cover
    # emitter (both as \definecolor{cover<key>} names in LaTeX and CSS in HTML).
    palette: dict = field(default_factory=dict)
    # Header-band institution name, one physical line per tuple entry.
    institution_lines: tuple[str, ...] = ()
    # data -> UNESCAPED title lines (the formal report title block).
    title_builder: Callable[[dict], list] = None
    # data -> UNESCAPED publisher / ISSN lines (inner title page).
    publisher_builder: Callable[[dict], list] = None
    # data -> [(role, [line, ...]), ...] — role-tagged title-page blocks, the
    # single source of the SAME text as title_builder/publisher_builder but with
    # per-role semantic tags for role-addressable styling.  Optional: falls back
    # to title_builder + publisher_builder when a layout doesn't supply it.
    title_page_blocks: Callable[[dict], list] = None
    # Surface-agnostic geometry in points (origin = top-left of a Letter page).
    metrics: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Text builders — the SINGLE source of the title / publisher text for BOTH
# surfaces.  Return UNESCAPED strings; each renderer escapes for its surface.
# ---------------------------------------------------------------------------

# The default strain form (carries ® — the renderers map it: LaTeX
# \textregistered, HTML entity).  A report without an explicit strain uses this.
_DEFAULT_STRAIN = "(Hsd:Sprague Dawley® SD®)"


# Max characters per wrapped title line.  The title renders in ~20pt Arial bold
# in a ~6.5" text block; a fixed break scheme overflows for long chemical names
# (Word then re-wraps mid-line at an inconvenient point — the reported bug).  We
# instead greedy-pack the title to this width so every line fits and breaks land
# at word boundaries.  Tuned conservatively for the bold 20pt face; a single word
# longer than this (a long IUPAC name) still gets its own line and may itself wrap
# — nothing but a smaller font can fix a single over-wide word.
_TITLE_MAX_CHARS = 34

# The pinned header line — always standalone (the reference keeps "NIEHS Report on
# the" on its own line above the flowed body).
_TITLE_HEADER = "NIEHS Report on the"


def _wrap_words(text: str, max_chars: int) -> list:
    """Greedy word-wrap ``text`` into lines no longer than ``max_chars`` (a word
    longer than the limit takes its own line rather than being split)."""
    lines: list = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _niehs_title_lines(data: dict, max_chars: int = _TITLE_MAX_CHARS) -> list:
    """
    The NIEHS 5D-Tox report title, WIDTH-WRAPPED into lines (ADR-0010 title-page
    follow-up).  The pinned header line stands alone; the rest of the title —
    "In Vivo Repeat Dose Biological Potency Study of <chemical> (CASRN <casrn>) in
    Sprague Dawley <strain> Rats (Gavage Studies)" — is greedy-packed to
    ``max_chars`` so no line overflows the text block and Word never re-wraps a
    line mid-phrase.  The chemical line carries the CASRN in parentheses when
    present.  Emitted as ONE paragraph with soft breaks by the renderer (matching
    the reference), so the wrapped lines have zero inter-line gap.
    """
    chemical = data.get("chemical_name", "")
    casrn = data.get("casrn", "")
    strain = data.get("strain") or _DEFAULT_STRAIN
    title_name = chemical + (f" (CASRN {casrn})" if casrn else "")
    body = " ".join(seg for seg in (
        "In Vivo Repeat Dose Biological Potency Study of",
        title_name,
        "in Sprague Dawley",
        strain,
        "Rats (Gavage Studies)",
    ) if seg.strip())
    return [_TITLE_HEADER, *_wrap_words(body, max_chars)]


def _niehs_publisher_lines(data: dict) -> list:
    """
    The publisher block for the inner title page: the institution, its parent
    agencies, the ISSN (only when present), and the location.
    """
    lines = [
        "National Institute of Environmental Health Sciences",
        "Public Health Service",
        "U.S. Department of Health and Human Services",
    ]
    issn = data.get("issn")
    if issn:
        lines.append(f"ISSN: {issn}")
    lines.append("Research Triangle Park, North Carolina, USA")
    return lines


# ---------------------------------------------------------------------------
# Role-tagged title-page blocks — the SAME text as the flat builders above, but
# each line carries a semantic ROLE so a per-role styling layer (and the NTP
# `1-NN` template style family) can address it.  Reuses `_niehs_title_lines` /
# `_niehs_publisher_lines` so the WORDING is single-sourced and cannot drift.
#
# Roles are snake_case and map 1:1 onto the NTP title-page styles (see
# docx_style_extract._TITLE_PAGE_STYLE_TO_ROLE).  Each block is
# (role, lines) where `lines` is a list emitted as ONE paragraph with internal
# line breaks — matching the reference, where e.g. the whole title is a single
# `1-03_Report_Title` paragraph, not one paragraph per line.
# ---------------------------------------------------------------------------

def _niehs_title_page_blocks(data: dict) -> list:
    """data -> [(role, [line, ...]), ...] for the inner title page.

    The title lines collapse into ONE `report_title` block (multi-line); the
    report number and date, and each publisher line, get their own role so they
    can be styled independently.  Publisher lines beyond the institution name
    share the `publisher_affiliation` role (the parent agencies + location),
    with the ISSN split out to `issn`.
    """
    blocks: list = []

    title_lines = _niehs_title_lines(data)
    if title_lines:
        blocks.append(("report_title", title_lines))

    report_number = data.get("report_number", "")
    if report_number:
        blocks.append(("report_number", [report_number]))
    report_date = data.get("report_date", "")
    if report_date:
        blocks.append(("publication_date", [report_date]))

    # Publisher block: each line carries its SPECIFIC NTP role so it lands on the
    # right 1-NN style (tight single spacing), not the generic publisher_affiliation
    # (which maps to no style → Normal → a stray 6pt gap).  Order matches
    # _niehs_publisher_lines: name, parent-agency×2, ISSN (optional), location.
    #   1-01_Publisher_Name / 1-08_Publication_Institute /
    #   1-09_Publication_Department / 1-05c_ISSN / NTP Publisher Location
    _PUB_ROLE_BY_TEXT = {
        "National Institute of Environmental Health Sciences": "publisher_name",
        "Public Health Service": "publication_institute",
        "U.S. Department of Health and Human Services": "publication_department",
        "Research Triangle Park, North Carolina, USA": "publisher_location",
    }
    for ln in _niehs_publisher_lines(data):
        if ln.startswith("ISSN:"):
            role = "issn"
        else:
            role = _PUB_ROLE_BY_TEXT.get(ln, "publisher_affiliation")
        blocks.append((role, [ln]))

    return blocks


# ---------------------------------------------------------------------------
# The NIEHS 5D-Tox cover — every reference-derived building block in one place.
# Geometry from the reference PDF (NIEHS Report 10, page 1): colors extracted via
# PyMuPDF drawing analysis, accent-bar vertices from the page's vector paths, all
# in points with the origin at the top-left corner of a 612×792pt Letter page.
# ---------------------------------------------------------------------------

_NIEHS_5D_TOX = CoverLayout(
    name="niehs-5d-tox",
    assets=("cover-bg.jpg", "nih-logo.png"),
    palette={
        "darkgray": "525457",   # accent-bar dark block + (unused) neutrals
        "green": "78A12E",      # accent-bar green block
        "sage": "CEDBB5",       # full-bleed background field
        "title": "535557",      # title + institution text
        "meta": "231F20",       # report number + date
    },
    institution_lines=("National Institute of", "Environmental Health Sciences"),
    title_builder=_niehs_title_lines,
    publisher_builder=_niehs_publisher_lines,
    title_page_blocks=_niehs_title_page_blocks,
    metrics={
        "band_height": 102.0,       # white institution band, top of page
        "bg_top": 119.0,            # sage field + hexagon bg start (below the bar)
        # NIH badge, top-left of the band.
        "logo_x": 40.0, "logo_y": 33.0, "logo_height": 38.0,
        # Institution text, to the right of the badge.
        "institution_x": 112.0, "institution_y": 38.0, "institution_size": 12.7,
        # Bicolor accent bar as two PARALLELOGRAMS (slanted white gap between).
        # Each is a list of (x, y) vertices, y measured DOWN from the top.
        "bar_dark": [(0.0, 102.2), (0.0, 119.0), (62.8, 119.0), (71.8, 102.2)],
        # Green block: the last two vertices sit at the RIGHT page edge (x=paper
        # width); the emitter anchors those to the page's east side.
        "bar_green_left": [(74.2, 102.2), (65.2, 119.0)],
        "bar_top": 102.2, "bar_bottom": 119.0,
        # Title block.
        "title_x": 72.0, "title_y": 190.0, "title_size": 30.0, "title_leading": 34.0,
        "title_width_frac": 0.75,
        # Report number + date (left-aligned under the title).
        "meta_x": 72.0, "report_number_y": 530.0, "report_date_y": 660.0,
        "meta_size": 12.0,
    },
)

_COVER_LAYOUTS: dict = {
    _NIEHS_5D_TOX.name: _NIEHS_5D_TOX,
}

# Fallback when a cover / title-page node carries no explicit subtype — the one
# report type we ship today.
DEFAULT_COVER_SUBTYPE = "niehs-5d-tox"


# ---------------------------------------------------------------------------
# Validation + accessors
# ---------------------------------------------------------------------------

def validate_layout(layout: CoverLayout) -> None:
    """
    Sanity-check a layout at import (loud on a packaging bug, like chart_registry's
    validate_data_spec): non-empty assets, a palette, and both text builders.
    """
    if not layout.assets:
        raise ValueError(f"cover layout {layout.name!r} declares no assets")
    if not layout.palette:
        raise ValueError(f"cover layout {layout.name!r} has an empty palette")
    if layout.title_builder is None or layout.publisher_builder is None:
        raise ValueError(
            f"cover layout {layout.name!r} must supply title_builder + publisher_builder"
        )


for _layout in _COVER_LAYOUTS.values():
    validate_layout(_layout)


def get_cover_layout(subtype: str | None) -> CoverLayout:
    """
    Resolve a cover subtype to its layout, falling back to the default when the
    node carries no subtype.  Raises ValueError on an unknown subtype (a typo in
    the template should fail loudly, not silently render the wrong cover).
    """
    key = subtype or DEFAULT_COVER_SUBTYPE
    try:
        return _COVER_LAYOUTS[key]
    except KeyError:
        raise ValueError(
            f"unknown cover subtype {key!r}; known: {sorted(_COVER_LAYOUTS)}"
        )


def required_assets(subtypes: Iterable) -> list:
    """
    The de-duplicated asset basenames needed to ship the covers for a set of
    subtypes (what latex_export must copy into the bundle).  None entries resolve
    to the default subtype.  Order is stable (first-seen) for deterministic output.
    """
    seen: dict = {}  # basename -> None, used as an ordered set
    for st in subtypes:
        for name in get_cover_layout(st).assets:
            seen.setdefault(name, None)
    return list(seen)


def asset_path(name: str) -> Path:
    """Absolute path to a shipped cover asset under ASSETS_DIR."""
    return ASSETS_DIR / name
