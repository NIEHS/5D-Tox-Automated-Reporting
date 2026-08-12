"""
Unit tests for genomics_charts.attach_genomics_charts — specifically the
`enabled_types` allowlist (the `charts:` config limiting factor).

The attach step hangs per-(organ, sex) chart images onto the matching gene_set
genomics entry.  `enabled_types` restricts WHICH chart types attach:

  - None  → no filtering (every produced type attaches — the default);
  - list  → only those types attach; the empty list attaches NONE.

Both render paths (session-export + web/preview) pass the active template's
`charts:` allowlist here, so the two surfaces always agree on which figures
appear.  A tiny synthetic cache (no real PNGs needed — a 1x1 PNG is enough to
pass the decode-validation) exercises the branch directly.
"""

import base64

from genomics.genomics_charts import attach_genomics_charts

# Smallest decodable PNG (1x1 transparent) — attach validates the base64
# decodes, so any real PNG bytes suffice.
_PNG_1x1 = base64.b64encode(
    base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
).decode()


def _sections():
    return [{"type": "gene_set", "organ": "Liver", "sex": "Male"}]


def _cache():
    return [{
        "organ": "liver", "sex": "male",
        "types": ["umap", "cluster"],
        "umap_png": _PNG_1x1, "umap_caption": "UMAP",
        "cluster_png": _PNG_1x1, "cluster_caption": "Cluster",
    }]


def _keys(sections):
    return [c["key"] for c in (sections[0].get("charts") or [])]


def test_none_attaches_every_produced_type():
    sections = _sections()
    attach_genomics_charts(sections, _cache(), enabled_types=None)
    assert _keys(sections) == ["umap", "cluster"]


def test_empty_list_attaches_nothing():
    sections = _sections()
    attach_genomics_charts(sections, _cache(), enabled_types=[])
    assert sections[0].get("charts") in (None, [])


def test_allowlist_keeps_only_listed_types():
    sections = _sections()
    attach_genomics_charts(sections, _cache(), enabled_types=["cluster"])
    assert _keys(sections) == ["cluster"]


def test_allowlist_is_case_insensitive():
    sections = _sections()
    attach_genomics_charts(sections, _cache(), enabled_types=["UMAP"])
    assert _keys(sections) == ["umap"]


def test_default_arg_matches_none_behavior():
    sections = _sections()
    attach_genomics_charts(sections, _cache())  # enabled_types omitted
    assert _keys(sections) == ["umap", "cluster"]
