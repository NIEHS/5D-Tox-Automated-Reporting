"""
Tests for Appendix B (Animal Identifiers): the roster as a `data-table` node.

Since ADR-0025 the reference's Table B-1 "Animal Numbers and FASTQ Data File
Names" is an ordinary programmatic matrix table under the appendix — a
`data-table` node bound to data["appendix_animals_matrix"] — not a special case
inside the appendix emitters.  Its "Table B-1" label is assigned by the
appendix-scoped numbering pass (document_tree._number_scoped), never written as
a literal.  The row JOIN (bare animal number + Plate1-/Plate5- FASTQ ids →
tissue rows) still lives in latex_export._load_animal_identifiers; the matrix
builder (render_common.build_animal_roster_matrix) projects those rows to the
shared {caption, headers, rows, footnotes, breakable} shape every surface
renders.
"""

from document_model.document_node import DocNode
from document_model.document_tree import compute_table_numbers
from rendering.render_common import build_animal_roster_matrix, ANIMAL_ROSTER_HEADERS
from rendering.latex_generator import (
    _render_appendix as latex_appendix,
    _render_sample_counts_table as latex_matrix,
)
from rendering.html_generator import (
    _render_appendix as html_appendix,
    _render_sample_counts_table as html_matrix,
)

# Post-join rows (the shape build_animal_roster_matrix consumes): one row per
# (animal, tissue).
_ROWS = [
    {"animal_number": "101", "sex": "Male", "dose": 0.0,
     "tissue": "Kidney", "fastq_file_id": "Plate5-101"},
    {"animal_number": "101", "sex": "Male", "dose": 0.0,
     "tissue": "Liver", "fastq_file_id": "Plate1-101"},
    {"animal_number": "102", "sex": "Female", "dose": 1000.0,
     "tissue": "Kidney", "fastq_file_id": "Plate5-102"},
]


def _appendix_b() -> tuple[DocNode, DocNode]:
    """A numbered Appendix B holding the roster data-table (as the template does)."""
    table = DocNode(id="table-b-1", title="Animal Numbers and FASTQ Data File Names",
                    level=0, node_type="data-table", data_key="appendix_animals_matrix")
    app = DocNode(id="appendix-b", title="Animal Identifiers", level=1,
                  node_type="appendix", children=[table])
    # Letters are positional: an Appendix A must precede it for B to be "B".
    first = DocNode(id="appendix-a", title="Internal Dose Assessment", level=1,
                    node_type="appendix")
    compute_table_numbers([first, app])
    return app, table


def _data():
    return {"appendix_animals_matrix": build_animal_roster_matrix(_ROWS)}


def test_matrix_builder_projects_rows_in_header_order():
    built = build_animal_roster_matrix(_ROWS)
    assert built["headers"] == list(ANIMAL_ROSTER_HEADERS)
    assert built["rows"][0] == ["101", "Male", "0", "Kidney", "Plate5-101"]
    # Integer doses drop the trailing .0; fractional doses are kept verbatim.
    assert built["rows"][2][2] == "1000"
    assert built["breakable"] is True and built["footnotes"] == []


def test_roster_is_labelled_b_1_by_the_scoped_numbering_pass():
    app, table = _appendix_b()
    assert app.appendix_letter == "B"
    assert (table.table_number, table.table_label, table.appendix_scope) == (1, "B-1", "B")


def test_appendix_b_renders_longtable_roster_latex():
    app, table = _appendix_b()
    out = latex_matrix(table, _data())
    assert "\\begin{longtable}" in out and "\\endhead" in out
    assert "Animal Number" in out and "FASTQ File ID" in out
    assert "Plate5-101" in out and "Kidney" in out
    assert "1000" in out and "1000.0" not in out
    # 5-column colspec (number | sex | dose | tissue | fastq id).
    assert "\\begin{longtable}{l l l l l}" in out


def test_appendix_b_longtable_carries_scoped_caption_and_label_latex():
    app, table = _appendix_b()
    out = latex_matrix(table, _data())
    # Numbered caption (steps LaTeX's counter) with the EMPTY short form — an
    # appendix table belongs to the appendix's own Tables list, not the front
    # \listoftables — plus a \label so \ref{tab:table-b-1} resolves.
    assert "\\caption[]{Table B-1. Animal Numbers and FASTQ Data File Names}" in out
    assert "\\label{tab:table-b-1}" in out
    assert "\\endfirsthead" in out


def test_appendix_opens_its_numbering_scope_latex():
    app, _ = _appendix_b()
    out = latex_appendix(app, _data())
    assert "\\section{Appendix B. Animal Identifiers}" in out
    assert "\\renewcommand{\\thetable}{B-\\arabic{table}}" in out
    assert "\\setcounter{figure}{0}" in out
    # Children carry the body: no pending stub, no roster inline.
    assert "Appendix body pending" not in out and "longtable" not in out


def test_appendix_b_without_data_is_pending():
    app, table = _appendix_b()
    assert "Table data pending" in latex_matrix(table, {})
    assert "Table data pending" in html_matrix(table, {})
    # A childless appendix still stubs.
    lone = DocNode(id="appendix-c", title="QC", level=1, node_type="appendix")
    assert "Appendix body pending" in latex_appendix(lone, {})
    assert "Appendix body pending" in html_appendix(lone, {})


def test_appendix_b_renders_table_html():
    app, table = _appendix_b()
    out = html_matrix(table, _data())
    assert "<table" in out and "Animal Number" in out
    assert "FASTQ File ID" in out and "Plate5-101" in out
    assert "<caption>Table B-1. Animal Numbers and FASTQ Data File Names</caption>" in out


def test_roster_cell_escaping_is_single_latex():
    """A LaTeX special in a FASTQ id is escaped exactly once (the old inline
    roster double-escaped)."""
    _, table = _appendix_b()
    data = {"appendix_animals_matrix": build_animal_roster_matrix([{
        "animal_number": "1", "sex": "Male", "dose": 0, "tissue": "Liver",
        "fastq_file_id": "A_1"}])}
    tex = latex_matrix(table, data)
    assert r"A\_1" in tex and r"\textbackslash" not in tex


def test_appendix_with_freeform_child_emits_heading_only_no_stub():
    node = DocNode(id="appendix-e", title="Organ Weight Descriptions",
                   level=1, node_type="appendix")
    node.children = [DocNode(id="appendix-e-body", title="", level=2,
                             node_type="freeform-block")]
    assert "Appendix body pending" not in latex_appendix(node, {})
    assert "Appendix body pending" not in html_appendix(node, {})
