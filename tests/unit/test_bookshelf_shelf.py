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
