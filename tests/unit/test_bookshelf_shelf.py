"""The Bookshelf shelf lists generated reports only.

Every directory in sessions/ used to be shelved — empty sessions, a session
whose data was cleared, and directories tests leaked into the real sessions/
(DTXSID_VC, DTXSID_TEST_NO_SESSION) all showed as books.  A report is a
session that was integrated and processed.
"""

import json

from fastapi.testclient import TestClient


def _session(root, dtxsid, *, integrated=False, processed=False, name=None):
    d = root / dtxsid
    d.mkdir(parents=True)
    if name:
        (d / "identity.json").write_text(json.dumps({"dtxsid": dtxsid, "name": name}))
    if integrated:
        (d / "integrated.json").write_text("{}")
    if processed:
        (d / "_cache_sections_0123456789abcdef.json").write_text("{}")
    return d


def test_only_generated_reports_are_shelved(sessions_dir):
    from web_routes.bookshelf_routes import generated_reports, has_generated_report

    _session(sessions_dir, "DTXSID7037717", integrated=True, processed=True, name="Bisphenol AF")
    _session(sessions_dir, "DTXSID50469320", name="PFHxSAm")                 # data cleared
    _session(sessions_dir, "DTXSID1020431", integrated=True, name="1,4-DCB")  # never processed
    _session(sessions_dir, "DTXSID_VC")                                       # a leaked test dir

    assert generated_reports() == ["DTXSID7037717"]
    assert not has_generated_report("DTXSID50469320")


def test_shelf_page_and_routes_serve_only_reports(sessions_dir):
    from web_routes.background_server import app

    _session(sessions_dir, "DTXSID7037717", integrated=True, processed=True, name="Bisphenol AF")
    _session(sessions_dir, "DTXSID_VC")
    client = TestClient(app)

    shelf = client.get("/Bookshelf").text
    assert "Bisphenol AF" in shelf and "DTXSID_VC" not in shelf
    assert client.get("/Bookshelf/DTXSID_VC").status_code == 404
    assert client.get("/Bookshelf/DTXSID_VC/report.docx").status_code == 404
    assert client.get("/Bookshelf/DTXSID_VC/report.pdf").status_code == 404


def test_rendering_a_body_creates_no_session_dir(sessions_dir):
    # marshal_export_data reads a session's files by id; it must not create
    # the directory for an id that has none.
    from rendering.report_data import marshal_export_data

    marshal_export_data({"dtxsid": "DTXSID_TEST_NO_SESSION", "chemical_name": "X"})
    assert not (sessions_dir / "DTXSID_TEST_NO_SESSION").exists()


def test_the_shelf_orders_published_reports_by_date_and_puts_unpublished_below(
        sessions_dir, monkeypatch):
    """Published books in the order they came out (left to right, top to
    bottom; one date's reports by number), each labelled with its date; a
    report over several studies is one book; unpublished studies follow in a
    grid of their own."""
    import narrative.prompt_workshop as pw
    import web_routes.compare_routes as cr
    from web_routes import bookshelf_routes as br

    reports = {"DTXSID1": "NIEHS-10", "DTXSID2": "NIEHS-02", "DTXSID3": "RR-8",
               "DTXSID4": "NIEHS-13"}
    dates = {"NIEHS-10": "2023-03", "NIEHS-02": "2022-10", "RR-8": "2018-12",
             "NIEHS-13": "2026-04"}
    monkeypatch.setattr(cr, "published_report", reports.get)
    monkeypatch.setattr(pw, "published_date", dates.get)
    for d, name in (("DTXSID1", "PFHxSAm"), ("DTXSID2", "EHDPP"), ("DTXSID3", "TPHP"),
                    ("DTXSID9", "Triclosan"), ("DTXSID8", "Bisphenol AF"),
                    ("DTXSID4_rat", "1,4-DCB"), ("DTXSID4_mouse", "1,4-DCB")):
        _session(sessions_dir, d, integrated=True, processed=True, name=name)
    report = _session(sessions_dir, "DTXSID4", name="1,4-Dichlorobenzene")
    (report / "studies.json").write_text(json.dumps({"rat": "DTXSID4_rat",
                                                     "mouse": "DTXSID4_mouse"}))

    published, unpublished = br.shelf_books()
    assert [b["dtxsid"] for b in published] == ["DTXSID3", "DTXSID2", "DTXSID1", "DTXSID4"]
    assert published[-1]["studies"] == ["Rats", "Mice"]
    assert [b["dtxsid"] for b in unpublished] == ["DTXSID8", "DTXSID9"]   # by title
    assert br.has_generated_report("DTXSID4")

    page = br._shelf_page(published, unpublished)
    assert page.index("2018 Dec · RR-8") < page.index("2022 Oct · NIEHS-02") \
        < page.index("2023 Mar · NIEHS-10") < page.index("2026 Apr · NIEHS-13") \
        < page.index("Unpublished") < page.index("Bisphenol AF")
    assert "DTXSID4_rat" not in page
