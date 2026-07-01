"""
Tests for Appendix B (Animal Identifiers) rendering + roster reconstruction.

Appendix B reconstructs the reference's Table B-1 "Animal Numbers and FASTQ Data
File Names": one row per (animal x sequenced tissue).  The LaTeX path uses a
page-breaking longtable (hundreds of rows); the HTML path a plain table.  The
row JOIN (bare animal number + Plate1-/Plate5- FASTQ ids → tissue rows) lives in
latex_export._load_animal_identifiers; the renderers consume the already-joined
rows via the shared appendix_roster_rows EXTRACT.
"""

import json

from document_node import DocNode
from latex_generator import _render_appendix as latex_appendix
from html_generator import _render_appendix as html_appendix

# Post-join rows (the shape appendix_roster_rows / the emitters consume): one
# row per (animal, tissue).
_ROWS = [
    {"animal_number": "101", "sex": "Male", "dose": 0.0,
     "tissue": "Kidney", "fastq_file_id": "Plate5-101"},
    {"animal_number": "101", "sex": "Male", "dose": 0.0,
     "tissue": "Liver", "fastq_file_id": "Plate1-101"},
    {"animal_number": "102", "sex": "Female", "dose": 1000.0,
     "tissue": "Kidney", "fastq_file_id": "Plate5-102"},
]


def _node(node_id, title):
    return DocNode(id=node_id, title=title, level=1, node_type="appendix")


def test_appendix_b_renders_longtable_roster_latex():
    out = latex_appendix(_node("appendix-b", "Appendix B. Animal Identifiers"),
                         {"appendix_animals": _ROWS})
    assert "\\begin{longtable}" in out and "\\endhead" in out
    # New FASTQ-mapping columns + a joined FASTQ file id.
    assert "Animal Number" in out and "FASTQ File ID" in out
    assert "Plate5-101" in out and "Kidney" in out
    # Integer doses drop the trailing .0; fractional doses are kept verbatim.
    assert "1000" in out and "1000.0" not in out


def test_appendix_b_longtable_has_five_columns_latex():
    out = latex_appendix(_node("appendix-b", "Appendix B. Animal Identifiers"),
                         {"appendix_animals": _ROWS})
    # 5-column colspec (number | sex | dose | tissue | fastq id).
    assert "\\begin{longtable}{l l r l l}" in out


def test_appendix_b_without_data_is_pending_latex():
    out = latex_appendix(_node("appendix-b", "Appendix B. Animal Identifiers"), {})
    assert "Appendix body pending" in out
    assert "longtable" not in out


def test_other_appendix_stays_pending_even_with_roster_data_latex():
    out = latex_appendix(_node("appendix-a", "Appendix A. Internal Dose Assessment"),
                         {"appendix_animals": _ROWS})
    assert "Appendix body pending" in out


def test_appendix_b_renders_table_html():
    out = html_appendix(_node("appendix-b", "Appendix B. Animal Identifiers"),
                        {"appendix_animals": _ROWS})
    assert "<table" in out and "Animal Number" in out
    assert "FASTQ File ID" in out and "Plate5-101" in out


def test_appendix_b_longtable_carries_fastq_caption_latex():
    out = latex_appendix(_node("appendix-b", "Appendix B. Animal Identifiers"),
                         {"appendix_animals": _ROWS})
    # The roster names itself Table B-1 with the reference's FASTQ title,
    # emitted once on the first page via \endfirsthead / \endhead.
    assert "Table B-1. Animal Numbers and FASTQ Data File Names" in out
    assert "\\endfirsthead" in out and "\\endhead" in out


def test_appendix_b_table_caption_html():
    out = html_appendix(_node("appendix-b", "Appendix B. Animal Identifiers"),
                        {"appendix_animals": _ROWS})
    assert "<caption>" in out
    assert "Table B-1. Animal Numbers and FASTQ Data File Names" in out


def test_appendix_with_freeform_child_emits_heading_only_no_stub():
    # An appendix carrying an authored freeform child renders heading only; the
    # walker renders the child body separately, so NO pending stub is emitted.
    node = DocNode(id="appendix-e", title="Appendix E. Organ Weight Descriptions",
                   level=1, node_type="appendix")
    node.children = [DocNode(id="appendix-e-body", title="", level=2,
                             node_type="freeform-block")]
    latex_out = latex_appendix(node, {})
    html_out = html_appendix(node, {})
    assert "pending" not in latex_out.lower()
    assert "pending" not in html_out.lower()


# ---------------------------------------------------------------------------
# The roster JOIN — bare animal number + Plate1-/Plate5- FASTQ ids → tissue rows
# ---------------------------------------------------------------------------

def _write_report(tmp_path, animals: dict) -> object:
    (tmp_path / "animal_report.json").write_text(
        json.dumps({"animals": animals}), encoding="utf-8"
    )
    return tmp_path


def test_load_identifiers_joins_id_forms_into_tissue_rows(tmp_path):
    from latex_export import _load_animal_identifiers
    # One physical animal (111) under all three id-forms.
    animals = {
        "111": {"animal_id": "111", "sex": "Female", "dose": 0.0},
        "Plate1-111": {"animal_id": "Plate1-111", "sex": "Female", "dose": 0.0},
        "Plate5-111": {"animal_id": "Plate5-111", "sex": "Female", "dose": 0.0},
    }
    rows = _load_animal_identifiers(_write_report(tmp_path, animals))
    # Exactly two rows (one per tissue), Kidney before Liver, bare id carries no row.
    assert [r["tissue"] for r in rows] == ["Kidney", "Liver"]
    assert rows[0]["fastq_file_id"] == "Plate5-111"   # Kidney
    assert rows[1]["fastq_file_id"] == "Plate1-111"   # Liver
    assert all(r["animal_number"] == "111" for r in rows)
    assert all(r["sex"] == "Female" and r["dose"] == 0.0 for r in rows)


def test_load_identifiers_sorts_by_number_then_kidney_before_liver(tmp_path):
    from latex_export import _load_animal_identifiers
    animals = {
        "Plate1-2": {"animal_id": "Plate1-2", "sex": "Male", "dose": 1.0},
        "Plate5-2": {"animal_id": "Plate5-2", "sex": "Male", "dose": 1.0},
        "Plate1-1": {"animal_id": "Plate1-1", "sex": "Male", "dose": 0.0},
        "Plate5-1": {"animal_id": "Plate5-1", "sex": "Male", "dose": 0.0},
    }
    rows = _load_animal_identifiers(_write_report(tmp_path, animals))
    got = [(r["animal_number"], r["tissue"]) for r in rows]
    assert got == [("1", "Kidney"), ("1", "Liver"), ("2", "Kidney"), ("2", "Liver")]


def test_load_identifiers_missing_file_returns_empty(tmp_path):
    from latex_export import _load_animal_identifiers
    assert _load_animal_identifiers(tmp_path) == []
