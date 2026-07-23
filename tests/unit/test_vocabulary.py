"""
test_vocabulary.py — the semantic-type vocabulary (design) system.

Covers the pure data model in isolation (in-memory loaders, no disk) AND the
real shipped vocab/base.yaml + vocab/ntp-report.yaml resolving end-to-end.

The load-bearing properties:
  - specialization: a type's resolved style is the deep-merge of its OWN delta
    over its parents' (root→leaf, child wins) — Word's basedOn as a walk.
  - the reference title fix: report_title resolves through the chain to
    Arial/20pt/center with NO line_height (single spacing by construction).
  - bindings: auto-derived per surface, explicit `bind` overrides win.
"""

import pytest

import vocabulary as V


# ---------------------------------------------------------------------------
# In-memory fixtures — a tiny two-vocabulary chain (base + domain)
# ---------------------------------------------------------------------------

BASE = {
    "vocabulary": "base",
    "types": {
        "document": {},
        "text": {"specializes": "document",
                 "style": {"font": "Times New Roman", "font_size": "12pt"}},
        "block": {"specializes": "text"},
        "heading": {"specializes": "text", "style": {"font": "Arial", "weight": "bold"}},
        "title": {"specializes": "heading"},
    },
}

NTP = {
    "vocabulary": "ntp",
    "extends": "base",
    "types": {
        "report_title": {"specializes": "title",
                         "style": {"font_size": "20pt", "align": "center", "space_after": "6pt"},
                         "bind": {"docx": "1-03_Report_Title"}},
        "body_para": {"specializes": "block", "style": {"space_after": "9pt"}},
    },
}

_FILES = {"base": BASE, "ntp": NTP}


def _load(name="ntp"):
    return V.load_vocabulary(name, _loader=lambda n: _FILES[n])


# ---------------------------------------------------------------------------
# Loading + extends flattening
# ---------------------------------------------------------------------------

def test_extends_flattens_parent_types():
    vocab = _load()
    # base's types + ntp's types are all present after resolution.
    assert {"document", "text", "block", "heading", "title",
            "report_title", "body_para"} <= set(vocab.types)


def test_child_type_overrides_parent_vocabulary_of_same_name():
    files = {
        "base": {"vocabulary": "base", "types": {"text": {"style": {"font_size": "12pt"}}}},
        "child": {"vocabulary": "child", "extends": "base",
                  "types": {"text": {"style": {"font_size": "10pt"}}}},
    }
    vocab = V.load_vocabulary("child", _loader=lambda n: files[n])
    # The child's `text` wins wholesale (redefined, not field-merged).
    assert V.resolve_type_style(vocab, "text") == {"font_size": "10pt"}


# ---------------------------------------------------------------------------
# Specialization resolution
# ---------------------------------------------------------------------------

def test_resolve_walks_specialization_root_to_leaf():
    vocab = _load()
    style = V.resolve_type_style(vocab, "report_title")
    # font Arial inherited from base.heading; 20pt/center/after from own delta;
    # weight bold from heading.
    assert style["font"] == "Arial"
    assert style["font_size"] == "20pt"
    assert style["weight"] == "bold"
    assert style["align"] == "center"
    assert style["space_after"] == "6pt"


def test_report_title_has_no_line_height():
    """The reference title fix: NOTHING in the chain injects a line-spacing key,
    so the rendered pitch is font-size-driven single spacing."""
    vocab = _load()
    assert "line_height" not in V.resolve_type_style(vocab, "report_title")
    assert "line_spacing_exact" not in V.resolve_type_style(vocab, "report_title")


def test_child_delta_wins_over_parent():
    files = {
        "base": {"vocabulary": "base",
                 "types": {"text": {"style": {"font_size": "12pt", "align": "left"}}}},
        "d": {"vocabulary": "d", "extends": "base",
              "types": {"lead": {"specializes": "text", "style": {"align": "center"}}}},
    }
    vocab = V.load_vocabulary("d", _loader=lambda n: files[n])
    style = V.resolve_type_style(vocab, "lead")
    assert style["font_size"] == "12pt"   # inherited
    assert style["align"] == "center"      # overridden


def test_unknown_type_resolves_empty():
    assert V.resolve_type_style(_load(), "nonexistent") == {}


# ---------------------------------------------------------------------------
# Bindings — auto-derive + override
# ---------------------------------------------------------------------------

def test_bindings_auto_derive_from_type_name():
    b = V.resolve_bindings(_load(), "body_para")
    assert b["html"] == "body-para"     # kebab
    assert b["latex"] == "bodypara"     # alnum
    assert b["docx"] == "body_para"     # name unchanged (no override)
    assert b["bits"] == "p"             # default element


def test_explicit_bind_overrides_derived():
    b = V.resolve_bindings(_load(), "report_title")
    assert b["docx"] == "1-03_Report_Title"   # explicit override wins
    assert b["html"] == "report-title"        # still auto-derived
    assert b["bits"] == "title"               # suffix-derived


def test_derive_binding_surfaces():
    assert V.derive_binding("section_heading_1", "html") == "section-heading-1"
    assert V.derive_binding("section_heading_1", "latex") == "sectionheading1"
    assert V.derive_binding("table_footnote", "bits") == "fn"
    assert V.derive_binding("body_para", "bits") == "p"
    with pytest.raises(ValueError):
        V.derive_binding("x", "pdf")


# ---------------------------------------------------------------------------
# Validation — loud failure on malformed vocabularies
# ---------------------------------------------------------------------------

def test_unknown_specializes_target_is_rejected():
    files = {"v": {"vocabulary": "v", "types": {"x": {"specializes": "ghost"}}}}
    with pytest.raises(ValueError, match="specializes unknown type"):
        V.load_vocabulary("v", _loader=lambda n: files[n])


def test_specialization_cycle_is_rejected():
    files = {"v": {"vocabulary": "v", "types": {
        "a": {"specializes": "b"}, "b": {"specializes": "a"}}}}
    with pytest.raises(ValueError, match="cycle"):
        V.load_vocabulary("v", _loader=lambda n: files[n])


def test_bad_style_value_is_rejected():
    files = {"v": {"vocabulary": "v", "types": {"x": {"style": {"align": "sideways"}}}}}
    with pytest.raises(ValueError, match="invalid style value"):
        V.load_vocabulary("v", _loader=lambda n: files[n])


def test_unknown_surface_in_bind_is_rejected():
    files = {"v": {"vocabulary": "v", "types": {"x": {"bind": {"pdf": "X"}}}}}
    with pytest.raises(ValueError, match="not a known surface"):
        V.load_vocabulary("v", _loader=lambda n: files[n])


def test_extends_cycle_is_rejected():
    files = {"a": {"vocabulary": "a", "extends": "b", "types": {}},
             "b": {"vocabulary": "b", "extends": "a", "types": {}}}
    with pytest.raises(ValueError, match="'extends' cycle"):
        V.load_vocabulary("a", _loader=lambda n: files[n])


# ---------------------------------------------------------------------------
# The REAL shipped vocabulary — vocab/base.yaml + vocab/ntp-report.yaml
# ---------------------------------------------------------------------------

def test_shipped_ntp_vocabulary_loads_and_resolves():
    vocab = V.load_vocabulary("ntp-report")
    # base roots + NTP roles all resolved into one graph.
    assert "text" in vocab.types            # from base.yaml
    assert "report_title" in vocab.types    # from ntp-report.yaml


def test_shipped_report_title_resolves_to_reference_look_without_line_spacing():
    vocab = V.load_vocabulary("ntp-report")
    style = V.resolve_type_style(vocab, "report_title")
    assert style["font"] == "Arial"          # inherited base_heading → heading
    assert style["font_size"] == "20pt"
    assert style["align"] == "center"
    assert "line_height" not in style        # the title fix, end to end
    # And it binds back to the real Word style for the docx round-trip.
    assert V.resolve_bindings(vocab, "report_title")["docx"] == "1-03_Report_Title"


def test_shipped_body_paragraph_is_times_12pt():
    vocab = V.load_vocabulary("ntp-report")
    style = V.resolve_type_style(vocab, "paragraph")   # 0-03_Paragraph
    assert style["font"] == "Times New Roman"
    assert style["font_size"] == "12pt"
    assert "line_height" not in style
