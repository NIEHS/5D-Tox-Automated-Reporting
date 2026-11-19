"""ui_api.review and its route: the review page's read (the demo path, spec
§4 S5) — the book's address, the sections by owner with the read model's
state, and where each section starts in the Bookshelf page.

Small fake sessions in a scratch SESSIONS_DIR: a report over two studies and
a study on its own, both rendering from the default report definition. No
model, no network, and no render: the anchors are derived from the tree.
"""

import json
import re

import pytest

REPORT = "DTXSID0000444"
RAT, MOUSE = f"{REPORT}_rat", f"{REPORT}_mouse"
ALONE = "DTXSID0000445"


def _write(folder, name, content="{}"):
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content))
    return path


def _study(folder, *, processed=True, interpretation=True):
    _write(folder, "identity.json", {"name": "Testane", "casrn": "50-00-0"})
    _write(folder, "files/data.txt", "doses")
    _write(folder, "_fingerprints.json")
    _write(folder, "validation_report.json")
    if processed:
        _write(folder, "integrated.json")
        _write(folder, "_cache_sections_h1.json")
    _write(folder, "bm2_body-weight.json", {
        "platform": "Body Weight", "title": "Body Weight", "narrative": ["Weights fell."],
        "approved": False, "source": "generated", "version": 1})
    # A results section the report prints no table for.
    _write(folder, "bm2_clinical-observations.json", {
        "platform": "Clinical Observations", "title": "Clinical Observations",
        "approved": False, "source": "generated", "version": 1})
    _write(folder, "summary.json", {"paragraphs": ["Facts by rule."], "source": "generated",
                                    "approved": False, "version": 1})
    if interpretation:
        _write(folder, "_cache_interpretation_liver_male_h1.json", {"gene_set_narrative": ["x"]})


@pytest.fixture
def store(sessions_dir):
    report = sessions_dir / REPORT
    _write(report, "studies.json", {"rat": RAT, "mouse": MOUSE})
    _write(report, "identity.json", {"name": "Testane", "casrn": "50-00-0"})
    _write(report, "background.json", {"paragraphs": ["Testane is a solvent."],
                                       "model_used": "model-x", "approved": False, "version": 1})
    _study(sessions_dir / RAT)
    _study(sessions_dir / MOUSE)
    _study(sessions_dir / ALONE)
    return sessions_dir


def _snapshot(root):
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*"))}


def _rows(answer, owner):
    [group] = [g for g in answer["groups"] if g["owner"] == owner]
    return {s["key"]: s for s in group["sections"]}


# ---------------------------------------------------------------------------
# The groups: who owns what
# ---------------------------------------------------------------------------

def test_a_report_owns_what_no_studys_data_changes_and_each_study_the_rest(store):
    from ui_api.review import review

    answer = review(REPORT)
    assert [(g["owner"], g["key"], g["title"]) for g in answer["groups"]] == [
        (REPORT, None, "The report"), (RAT, "rat", "Rat study"), (MOUSE, "mouse", "Mouse study")]
    report = _rows(answer, REPORT)
    assert list(report)[-1] == "background" and "foreword" in report and "abstract" in report
    assert not {"methods", "summary", "bm2_body-weight", "bmd_summary"} & set(report)
    for study in (RAT, MOUSE):
        rows = _rows(answer, study)
        assert {"methods", "bm2_body-weight", "bm2_clinical-observations", "bmd_summary",
                "genomics_liver_male", "summary"} <= set(rows)
        assert not {"background", "foreword", "abstract"} & set(rows)
        assert all(r["owner"] == study for r in rows.values())
    assert answer["asked"] is None and answer["report"] == {"id": REPORT, "kind": "report"}


def test_every_row_is_the_read_models_row_with_an_owner_a_title_and_a_writer(store):
    from ui_api.read_model import study_state
    from ui_api.review import review

    answer = review(REPORT)
    for owner in (REPORT, RAT):
        served = {s["key"]: s for s in study_state(owner)["sections"]}
        for key, row in _rows(answer, owner).items():
            for field in ("kind", "approvable", "approved", "has_file", "enabled", "stale",
                          "regenerated", "review", "maturity", "version", "machine_may_write",
                          "region", "instance_of", "blocked_by", "accept"):
                assert row[field] == served[key][field], (owner, key, field)
            assert row["title"] and row["writer_say"]
    rat = _rows(answer, RAT)
    assert rat["bm2_body-weight"]["accept"] == {"allowed": True, "code": None, "say": None}
    assert rat["methods"]["accept"]["allowed"] is False and rat["methods"]["accept"]["say"]
    # A section printed without a heading of its own is named by the heading
    # it is printed under; an interpretation by its tissue and sex.
    assert rat["animal_condition"]["title"] == "Animal Condition, Body Weights, and Organ Weights"
    assert rat["genomics_liver_male"]["title"] == "Gene-level interpretation: liver, male"
    assert "language model" in rat["genomics_liver_male"]["writer_say"]
    assert "data" in rat["bm2_body-weight"]["writer_say"]


def test_the_publish_readiness_is_served_for_the_report_and_for_each_study(store):
    from ui_api.read_model import study_state
    from ui_api.review import review

    answer = review(REPORT)
    for group in answer["groups"]:
        assert group["publish"] == study_state(group["owner"])["readiness"]["publish"]
        assert group["publish"]["complete"] is False      # never "ready to publish" (C6)


# ---------------------------------------------------------------------------
# The anchors
# ---------------------------------------------------------------------------

def test_a_section_is_anchored_where_it_starts_in_the_book(store):
    from ui_api.review import review

    answer = review(REPORT)
    report, rat, mouse = (_rows(answer, o) for o in (REPORT, RAT, MOUSE))
    assert report["foreword"]["anchor"] == "fm-foreword"
    assert report["peer_review"]["anchor"] == "fm-peer-review"
    assert report["background"]["anchor"] == "bp-background"
    # A section repeated per study: the copy of that study.
    assert rat["animal_condition"]["anchor"] == "sec-animal-condition-study--rat"
    assert mouse["animal_condition"]["anchor"] == "sec-animal-condition-study--mouse"
    assert rat["methods"]["anchor"] == "sec-mm-study-design--rat"
    # A table the studies share stands once, under the first study.
    assert rat["bm2_body-weight"]["anchor"] == mouse["bm2_body-weight"]["anchor"] == "T-table-body-weight"
    # An interpretation: its tissue, in its study.
    assert rat["genomics_liver_male"]["anchor"] == "sec-gene-set-tissue-study--rat--liver"
    assert mouse["genomics_liver_male"]["anchor"] == "sec-gene-set-tissue-study--mouse--liver"
    # What the studies share and no copy is made of.
    assert rat["summary"]["anchor"] == mouse["summary"]["anchor"] == "bp-summary"
    assert rat["bmd_summary"]["anchor"] == "sec-bmd-summary"


def test_a_section_with_no_place_of_its_own_has_no_anchor(store):
    from ui_api.review import review

    answer = review(REPORT)
    # The Abstract is held in the book's metadata; no table is printed for
    # the clinical observations; a domain no study collected is left out.
    assert _rows(answer, REPORT)["abstract"]["anchor"] is None
    assert _rows(answer, RAT)["bm2_clinical-observations"]["anchor"] is None
    assert _rows(answer, RAT)["clinical_pathology"]["anchor"] is None


def test_the_sections_of_a_group_are_in_the_books_order(store):
    from ui_api.review import _Book, review
    from ui_api.read_model import _rendering_catalog

    answer = review(REPORT)
    _, tree, _ = _rendering_catalog(REPORT)
    book = _Book(tree, ["rat", "mouse"], ["liver"], {"Body Weight", "Clinical Observations"})
    place = {}
    for i, node in enumerate(book.order):
        anchor = book.anchor(node)
        if anchor:
            place.setdefault(anchor, i)
    for group in answer["groups"]:
        anchored = [place[s["anchor"]] for s in group["sections"] if s["anchor"]]
        assert anchored == sorted(anchored), group["owner"]
        assert all(s["anchor"] in place for s in group["sections"] if s["anchor"])


def test_a_study_on_its_own_is_one_group_and_its_sections_are_not_scoped(store):
    from ui_api.review import review

    answer = review(ALONE)
    assert [(g["owner"], g["key"], g["title"]) for g in answer["groups"]] == [(ALONE, None, "The report")]
    rows = _rows(answer, ALONE)
    assert {"foreword", "background", "methods", "bm2_body-weight", "summary"} <= set(rows)
    assert rows["bm2_body-weight"]["anchor"] == "T-table-body-weight"
    assert rows["methods"]["anchor"] == "bp-methods"
    # The heading that takes in a single study's untitled section names it.
    assert rows["animal_condition"]["anchor"] == "sec-animal-condition"
    assert rows["animal_condition"]["title"] == "Animal Condition, Body Weights, and Organ Weights"
    assert not any("--rat" in (r["anchor"] or "") for r in rows.values())
    assert answer["kind"] == "study" and answer["asked"] is None


def test_the_element_ids_are_the_ones_the_emitter_writes():
    """The derivation against a real render: every anchor derived for the
    default tree is an id of the BITS book made from it."""
    from document_model.document_tree import DOCUMENT_TREE
    from rendering.jats_generator import generate_bits
    from rendering.report_data import scaffold_report_data
    from ui_api.review import _Book
    from workflow.section_catalog import catalog_for_tree

    data = scaffold_report_data(chemical_name="Perfluorohexanesulfonamide",
                                casrn="41997-13-1", dtxsid="DTXSID50469320")
    ids = set(re.findall(r'\bid="([^"]+)"', generate_bits(data)))
    book = _Book(DOCUMENT_TREE, [], [], set())
    anchors = {}
    for spec in catalog_for_tree(DOCUMENT_TREE):
        if spec.instance_of is None:
            node = book.singleton(spec.key, None)
            anchors[spec.key] = book.anchor(node) if node is not None else None
    assert anchors["abstract"] is None
    derived = {k: a for k, a in anchors.items() if a is not None}
    assert {"foreword", "background", "methods", "bmd_summary", "summary"} <= set(derived)
    assert not {k: a for k, a in derived.items() if a not in ids}


# ---------------------------------------------------------------------------
# Asked of a study of a report; the book; the finished side
# ---------------------------------------------------------------------------

def test_asked_of_a_study_it_answers_for_the_report_and_says_which_study(store):
    from ui_api.review import review

    of_report, of_study = review(REPORT), review(MOUSE)
    assert of_study["id"] == MOUSE and of_study["kind"] == "member"
    assert of_study["report"] == {"id": REPORT, "kind": "report"}
    assert of_study["asked"]["id"] == MOUSE and of_study["asked"]["key"] == "mouse"
    assert REPORT in of_study["asked"]["say"]
    assert of_study["groups"] == of_report["groups"]
    assert of_study["book"] == of_report["book"]            # the book is the report's
    assert of_study["downloads"] == of_report["downloads"]


def test_the_book_and_its_downloads_are_addressed_when_it_can_be_shown(store):
    from ui_api.review import review

    answer = review(REPORT)
    assert answer["book"] == {"shown": True, "url": f"/Bookshelf/{REPORT}",
                              "say": "On the Bookshelf (draft)"}
    assert [(d["format"], d["url"], d["filename"]) for d in answer["downloads"]] == [
        ("docx", f"/Bookshelf/{REPORT}/report.docx", f"{REPORT}-report.docx"),
        ("pdf", f"/Bookshelf/{REPORT}/report.pdf", f"{REPORT}-report.pdf")]


def test_a_report_whose_studies_are_not_all_processed_has_no_book_and_says_why(store):
    from ui_api.review import review

    (store / MOUSE / "integrated.json").unlink()
    answer = review(RAT)
    assert answer["book"]["shown"] is False and answer["book"]["url"] is None
    assert "not all been processed" in answer["book"]["say"]
    assert answer["downloads"] == []
    assert len(answer["groups"]) == 3                      # the sections still list


def test_a_study_of_the_report_that_does_not_exist_is_said(store):
    import shutil
    from ui_api.review import review

    shutil.rmtree(store / MOUSE)
    answer = review(REPORT)
    [missing] = [g for g in answer["groups"] if g["owner"] == MOUSE]
    assert missing["exists"] is False and missing["sections"] == [] and MOUSE in missing["say"]
    assert answer["book"]["shown"] is False


def test_no_act_is_offered_on_the_finished_side_of_a_pair(store):
    from tooling import demo_copy
    from ui_api.review import review

    assert review(REPORT)["acts"] == {"allowed": True, "say": None, "counterpart": None}
    demo_copy.make(REPORT)
    finished = review(RAT)["acts"]
    assert finished["allowed"] is False and finished["counterpart"] == f"{REPORT}_live_rat"
    assert f"{REPORT}_live_rat" in finished["say"]
    assert review(REPORT)["acts"]["counterpart"] == f"{REPORT}_live"
    assert review(f"{REPORT}_live")["acts"]["allowed"] is True


def test_reading_leaves_no_trace(store):
    from ui_api.review import review

    before = _snapshot(store)
    for sid in (REPORT, RAT, ALONE):
        review(sid)
    assert _snapshot(store) == before


def test_nobody_is_addressed_and_the_page_is_named_on_the_api_page(store):
    from ui_api.review import _WRITER_SAY, review

    answer = review(MOUSE)
    texts = [answer["asked"]["say"], answer["book"]["say"], *_WRITER_SAY.values(),
             *(g["title"] for g in answer["groups"]),
             *(s["writer_say"] for g in answer["groups"] for s in g["sections"])]
    assert not [t for t in texts if re.search(r"\b(you|your|yours)\b", t, re.I)]
    assert [(link["group"], link["title"]) for link in answer["api_page"]] == [
        ("review", "Review and approval"), ("report", "The report: Bookshelf, Word and PDF")]
    assert all(link["href"].startswith("/docs#/") for link in answer["api_page"])


# ---------------------------------------------------------------------------
# The route
# ---------------------------------------------------------------------------

def test_the_route_answers_the_read_and_explains_its_refusals(store, client):
    from ui_api.review import review

    ok = client.get(f"/api/v2/studies/{REPORT}/review")
    assert ok.status_code == 200 and ok.json() == json.loads(json.dumps(review(REPORT)))

    gone = client.get("/api/v2/studies/DTXSID0000999/review")
    assert gone.status_code == 404
    assert gone.json()["error"]["code"] == "study_not_found" and gone.json()["error"]["say"]
    assert not (store / "DTXSID0000999").exists()

    bad = client.get("/api/v2/studies/not%20an%20id/review")
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_study_id"


def test_an_approval_and_a_reopening_show_in_the_next_read(store, client):
    """The page's acts are the section routes; the review reads what they left."""
    key = "bm2_body-weight"
    done = client.post(f"/api/v2/studies/{RAT}/sections/{key}/accept")
    assert done.status_code == 200, done.text
    row = _rows(client.get(f"/api/v2/studies/{REPORT}/review").json(), RAT)[key]
    assert row["approved"] is True and row["accept"]["code"] == "already_accepted"
    # The other study's section of the same key is its own.
    assert _rows(client.get(f"/api/v2/studies/{REPORT}/review").json(), MOUSE)[key]["approved"] is False

    refused = client.post(f"/api/v2/studies/{RAT}/sections/{key}/release", json={"reason": " "})
    assert refused.status_code >= 400 and refused.json()["error"]["say"]
    reopened = client.post(f"/api/v2/studies/{RAT}/sections/{key}/release",
                           json={"reason": "A footnote is wrong."})
    assert reopened.status_code == 200, reopened.text
    row = _rows(client.get(f"/api/v2/studies/{REPORT}/review").json(), RAT)[key]
    assert row["approved"] is False and row["accept"]["allowed"] is True
    history = client.get(f"/api/v2/studies/{RAT}/sections/{key}/history").json()
    assert any(e.get("reason") == "A footnote is wrong." for e in history["events"])
