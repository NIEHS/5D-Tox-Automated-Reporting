"""
Cold-start table-numbering regression for marshal_export_data.

The apical overlay resolves each section's table number from the document
tree via _find_table_number(DOCUMENT_TREE, platform), which reads
node.table_number.  Those fields are None until compute_table_numbers() has
run.  marshal_export_data must therefore compute the numbers itself before the
overlays — otherwise a *fresh* process produces apical sections with no
table_number, and the document-order sort collapses every section to the
10_000 fallback (the bug this test guards).

The cold_tree fixture resets every node's table_number to None so the test
asserts the property on a genuinely fresh tree, independent of whether some
earlier test in the run already left numbers cached in the module-global
DOCUMENT_TREE.

The dtxsid has no session directory, so the disk-backed genomics-cache reads
are deterministic no-ops (same rationale as test_marshal_golden.py).
"""

import copy

import pytest

from report_data import marshal_export_data
from document_tree import DOCUMENT_TREE, walk_tree


# Positional numbers assigned by compute_table_numbers() on the canonical
# document tree.  Table 1 is the Methods sample-counts-table node (first
# numbered node in document order), so the Results apical tables start at 2.
# These are the ground truth the overlay must reproduce.  The apical platforms
# are contiguous (2..7) — the active template no longer instances a Clinical
# Observations incidence-table, so there is no gap.
EXPECTED_TABLE_NUMBERS = {
    "Body Weight": 2,
    "Organ Weight": 3,
    "Clinical Chemistry": 4,
    "Hematology": 5,
    "Hormones": 6,
    "Tissue Concentration": 7,
}


@pytest.fixture
def cold_tree():
    """Force the module-global document tree into the unnumbered state a
    fresh process starts in, so the test never passes only because an earlier
    marshal call leaked positional numbers across the run."""
    def _clear(node):
        node.table_number = None

    walk_tree(DOCUMENT_TREE, _clear)
    return DOCUMENT_TREE


def _apical_body(*platforms: str) -> dict:
    """A minimal export body carrying one empty apical section per platform.
    Empty table_data dodges the table-row schema while still exercising the
    footnote build, tree table-number lookup, and document-order sort."""
    return {
        "chemical_name": "Test Article",
        "casrn": "1-1-1",
        "dtxsid": "DTXSID_TEST_NO_SESSION",
        "apical_sections": [
            {
                "section_title": platform,
                "platform": platform,
                "dose_unit": "mg/kg",
                "caption": f"{platform} table.",
                "narrative_paragraphs": [f"{platform} narrative."],
                "table_data": {},
                "footnotes": [],
            }
            for platform in platforms
        ],
    }


def test_cold_marshal_assigns_positional_table_number(cold_tree):
    """A single apical section gets its correct positional number on the very
    first marshal call of a fresh process (table_number is not None)."""
    out = marshal_export_data(_apical_body("Body Weight"))

    section = out["apical_sections"][0]
    assert section["table_number"] == EXPECTED_TABLE_NUMBERS["Body Weight"], (
        "Cold-start marshal_export_data failed to assign the positional table "
        "number — compute_table_numbers() must run before the apical overlay."
    )


def test_cold_marshal_numbers_and_orders_multiple_sections(cold_tree):
    """Sections supplied out of document order are renumbered AND re-sorted
    into document-tree order on a cold tree (the sort key is the tree number,
    so this also guards the ordering benefit of computing numbers first)."""
    # Deliberately reversed input order.
    out = marshal_export_data(
        _apical_body("Hematology", "Organ Weight", "Body Weight")
    )

    produced = [(s["title"], s["table_number"]) for s in out["apical_sections"]]
    assert produced == [
        ("Body Weight", 2),
        ("Organ Weight", 3),
        ("Hematology", 5),
    ], "Apical sections must be numbered from the tree and sorted in document order."


def test_cold_marshal_matches_full_tree_numbering(cold_tree):
    """Every known apical platform resolves to its canonical positional number
    on a cold call — a full-coverage guard against the numbering drifting."""
    platforms = list(EXPECTED_TABLE_NUMBERS)
    out = marshal_export_data(_apical_body(*platforms))

    got = {s["title"]: s["table_number"] for s in out["apical_sections"]}
    assert got == EXPECTED_TABLE_NUMBERS


def test_cold_marshal_numbers_genomics_tables_after_apical(cold_tree):
    """Genomics tables (data-driven, not tree nodes) continue the positional
    sequence after the last apical/BMD table.  The last tree table is the BMD
    summary (Table 8), so genomics gene_set tables get 9.. and gene tables
    follow — assigned in RENDER order (all gene_set first, then all gene),
    NOT the interleaved list order."""
    body = _apical_body("Body Weight")
    # Interleaved delivery order, two organs, gene_set + gene each.
    body["genomics_sections"] = [
        {"type": "gene_set", "organ": "liver", "sex": "male", "gene_sets": [{"rank": 1}]},
        {"type": "gene", "organ": "liver", "sex": "male", "top_genes": [{"rank": 1}]},
        {"type": "gene_set", "organ": "kidney", "sex": "male", "gene_sets": [{"rank": 1}]},
        {"type": "gene", "organ": "kidney", "sex": "male", "top_genes": [{"rank": 1}]},
    ]
    out = marshal_export_data(body)
    numbered = {
        (s["type"], s["organ"]): s["table_number"]
        for s in out["genomics_sections"]
    }
    # gene_set tables numbered first (9, 10), then gene tables (11, 12),
    # each in list order within its role.
    assert numbered == {
        ("gene_set", "liver"): 9,
        ("gene_set", "kidney"): 10,
        ("gene", "liver"): 11,
        ("gene", "kidney"): 12,
    }
    # The front-matter Tables list continues the sequence too.
    table_nums = [e["table_number"] for e in out["table_entries"]]
    assert 9 in table_nums and 12 in table_nums
    assert table_nums == sorted(table_nums)
