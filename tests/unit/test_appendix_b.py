"""
Tests for Appendix B (Animal Identifiers) rendering (ADR-0003 Phase 5).

Appendix B turns the animal_report.json roster into a real table; the other
appendices stay pending.  The LaTeX path uses a page-breaking longtable (the
roster is ~300 rows); the HTML path a plain table.
"""

from document_node import DocNode
from latex_generator import _render_appendix as latex_appendix
from html_generator import _render_appendix as html_appendix

_ROWS = [
    {"animal_id": "Plate1-1", "sex": "Female", "dose": 0.0},
    {"animal_id": "Plate1-2", "sex": "Male", "dose": 1000.0},
    {"animal_id": "Plate1-3", "sex": "Male", "dose": 0.15},
]


def _node(node_id, title):
    return DocNode(id=node_id, title=title, level=1, node_type="appendix")


def test_appendix_b_renders_longtable_roster_latex():
    out = latex_appendix(_node("appendix-b", "Appendix B. Animal Identifiers"),
                         {"appendix_animals": _ROWS})
    assert "\\begin{longtable}" in out and "\\endhead" in out
    assert "Animal ID" in out and "Plate1-1" in out
    # Integer doses drop the trailing .0; fractional doses are kept verbatim.
    assert "1000" in out and "1000.0" not in out
    assert "0.15" in out


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
    assert "<table" in out and "Animal ID" in out and "Plate1-1" in out
