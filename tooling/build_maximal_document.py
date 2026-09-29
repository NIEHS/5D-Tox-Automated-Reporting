"""
build_maximal_document — author a per-session document.yaml that exercises EVERY
node type, so the dependency tracer covers every render path.

The global template already exercises 13 of the 18 catalog node types. This adds the
5 the tracer found unexercised — cover, page-break, freeform-page, figure,
incidence-table — at LEGAL parents (per render_capabilities containment grammar), on
top of the shipped document block, then validates the whole thing through
build_session_tree before writing sessions/<dtxsid>/document.yaml.

No scientific/domain values are invented: the additions are structural (a cover, a
page break, a boilerplate freeform page) or point at data this session already has
(a figure on genomics chart data; an incidence-table on the real Clinical Observations
platform, which is present in the sections cache).

Usage:  .venv/bin/python -m tooling.build_maximal_document DTXSID50469320 [--write]
Without --write it validates and prints a summary but does not touch disk.
"""

from __future__ import annotations

import copy
import sys

import yaml

from document_model.document_tree import ACTIVE_TEMPLATE
from document_model.document_template import load_template


def _find_region(doc: list, region: str) -> dict:
    for entry in doc:
        if isinstance(entry, dict) and entry.get("region") == region:
            return entry
    raise KeyError(region)


def build_maximal_document() -> list:
    """Return a document list (region containers) covering all 18 node types."""
    doc = copy.deepcopy(load_template(ACTIVE_TEMPLATE))
    # load_template returns the document list (region containers).

    front = _find_region(doc, "front")
    body = _find_region(doc, "body")

    # 1. cover — top-level in front, before the title page. subtype niehs-5d-tox.
    front["children"].insert(0, {
        "id": "max-cover",
        "type": "cover",
        "title": "Cover",
        "subtype": "niehs-5d-tox",
    })

    # 2. page-break — legal under heading-only. Add a heading-only host in body
    #    carrying a page-break plus a freeform-page (both otherwise unexercised).
    body["children"].append({
        "id": "max-extras",
        "type": "heading-only",
        "title": "Supplementary Structure",
        "children": [
            {
                "id": "max-page-break",
                "type": "page-break",
                "title": "",
            },
            # 3. freeform-page — inline dual-source content (no representation).
            {
                "id": "max-freeform-page",
                "type": "freeform-page",
                "title": "Data Availability",
                "content": {
                    "latex": r"\emph{Data available on request.}",
                    "html": "<em>Data available on request.</em>",
                },
            },
        ],
    })

    # 4. figure — top-level (no catalog parent accepts it). Points at genomics chart
    #    data this session has; subtype chart.
    body["children"].append({
        "id": "max-figure",
        "type": "figure",
        "title": "Representative UMAP",
        "subtype": "chart",
        "data_key": "genomics_charts",
        "caption": "Representative UMAP projection (coverage figure).",
        "orientation": "landscape",
    })

    # 5. incidence-table — legal ONLY under narrative+tables. The Results section's
    #    animal-condition node is a narrative+tables; add an incidence-table child on
    #    the real Clinical Observations platform (present in this session's data).
    results = None
    for c in body["children"]:
        if c.get("id") == "results":
            results = c
            break
    if results is not None:
        for sub in results.get("children", []):
            if sub.get("type") == "narrative+tables":
                sub.setdefault("children", []).append({
                    "id": "max-incidence-clin-obs",
                    "type": "incidence-table",
                    "title": "Clinical Observations Incidence",
                    "platform": "Clinical Observations",
                    "caption": "Incidence of clinical observations by dose.",
                })
                break

    return doc


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dtxsid = args[0] if args else "DTXSID50469320"
    write = "--write" in sys.argv

    doc = build_maximal_document()

    # Validate the whole thing exactly as build_session_tree would.
    from document_model.document_config import _tree_from_document_list
    from document_model.document_tree import walk_tree
    from document_model.render_capabilities import COMPONENT_CATALOG

    tree = _tree_from_document_list(doc)  # raises on any invalid entry / dup id
    present: set[str] = set()
    walk_tree(tree, lambda n: present.add(n.node_type))
    missing = set(COMPONENT_CATALOG) - present
    print(f"node types covered: {len(present)}/{len(COMPONENT_CATALOG)}")
    print(f"still missing     : {sorted(missing) or 'NONE — fully maximal'}")

    text = yaml.safe_dump({"document": doc}, sort_keys=False, allow_unicode=True)

    if write:
        from document_model.document_config import session_document_path
        path = session_document_path(dtxsid)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path}")
    else:
        print("(dry run — pass --write to persist)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
