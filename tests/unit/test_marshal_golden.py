"""
Golden-snapshot regression oracle for marshal_export_data.

marshal_export_data overlays request-body content onto the report scaffold.
It is the report-data layer's large "god function" (decomposition in progress),
and the rest of the suite only smoke-tests it structurally.  This pins its
EXACT marshaled output for two fixed request bodies, so the decomposition —
and any future edit — is provably output-preserving: a single byte change in
the produced dict fails here.

Why this is reproducible: report_data.py has no nondeterminism (no dates,
random, uuid, or set-ordering), and the fixtures use a dtxsid with no session
directory, so the genomics-cache disk reads are no-ops.

Regenerate the fixtures after an INTENTIONAL output change:
    UPDATE_GOLDEN=1 uv run python -m pytest tests/unit/test_marshal_golden.py
"""

import copy
import json
import os
import pathlib

import pytest

from rendering.report_data import marshal_export_data

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

# --- Fixed input bodies --------------------------------------------------
# BODY_MINIMAL: just identity — exercises the scaffold + the empty-overlay
# structure (most of the document shape, every section present as a stub).
BODY_MINIMAL = {
    "chemical_name": "Test Article",
    "casrn": "1-1-1",
    "dtxsid": "DTXSID_TEST_NO_SESSION",
}

# BODY_RICH: content for every overlay phase — orientations, report metadata,
# front matter, background/refs/methods, abstract assembly (Methods/Background/
# Results/Summary), an apical section (empty table to dodge the table_data
# schema while still exercising the entry build + tree table-number lookup +
# sort + normalize), unified narratives, BMD summary + the LLE paragraph,
# genomics + gene-set narrative, and the summary.  dtxsid has no session dir,
# so the disk-backed genomics-cache branches are deterministic no-ops.
BODY_RICH = {
    "chemical_name": "Test Article",
    "abbreviation": "TA",
    "casrn": "1-1-1",
    "dtxsid": "DTXSID_TEST_NO_SESSION",
    "pubchem_cid": "999",
    "ec_number": "200-000-0",
    "orientations": {"table-body-weight": "landscape"},
    "report_number": "DR99",
    "report_date": "Month 2026",
    "strain": "Wistar",
    "foreword": "Foreword text.",
    "acknowledgments": ["Ack one.", "Ack two."],
    "paragraphs": ["Background para 1.", "Background para 2."],
    "references": [{"id": 1, "text": "Ref 1"}],
    "methods_paragraphs": ["Methods flat para."],
    "methods_data": {
        "context": {
            "chemical_name": "Test Article",
            "dose_groups": [0, 3, 10, 30],
            "dose_unit": "mg/kg",
            "has_gene_expression": True,
        }
    },
    "abstract_background": "Abstract background sentence.",
    "apical_sections": [
        {
            "section_title": "Body Weight",
            "platform": "Body Weight",
            "dose_unit": "mg/kg",
            "caption": "Body weights.",
            "narrative_paragraphs": ["BW narrative."],
            "table_data": {},
            "footnotes": [],
        }
    ],
    "unified_narratives": {"apical": {"paragraphs": ["Unified animal-condition prose."]}},
    "bmd_summary_endpoints": [{"endpoint": "ALT", "bmd": 12.3}],
    "genomics_sections": [{"type": "gene_set", "organ": "Liver", "sex": "Male"}],
    "gene_set_narrative": ["Gene set prose."],
    "summary_paragraphs": ["Summary para."],
}

BODIES = {"minimal": BODY_MINIMAL, "rich": BODY_RICH}


def _canonical(body: dict) -> str:
    """Marshal a (copied) body and serialize stably for byte comparison."""
    out = marshal_export_data(copy.deepcopy(body))
    return json.dumps(out, sort_keys=True, indent=2, ensure_ascii=False)


@pytest.mark.parametrize("name", list(BODIES))
def test_marshal_output_matches_golden(name):
    produced = _canonical(BODIES[name])
    path = FIXTURES / f"marshal_{name}.json"

    if os.environ.get("UPDATE_GOLDEN"):
        FIXTURES.mkdir(exist_ok=True)
        path.write_text(produced, encoding="utf-8")
        pytest.skip(f"UPDATE_GOLDEN set — regenerated {path.name}")

    expected = path.read_text(encoding="utf-8")
    assert produced == expected, (
        f"marshal_export_data output changed for the '{name}' fixture.\n"
        f"If this change is INTENTIONAL, regenerate the golden file:\n"
        f"    UPDATE_GOLDEN=1 uv run python -m pytest "
        f"tests/unit/test_marshal_golden.py"
    )
