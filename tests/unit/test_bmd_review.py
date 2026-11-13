"""UREP is a reviewer's decision; the screen only proposes it (pipeline.bmd_review)."""

from types import SimpleNamespace

from pipeline.bmd_review import (
    REVIEWS_FILE, apply_reviews, pending, record_reviews, reviews_hash, screen,
)


def _row(label, bmd, noel, loel, bmdl="1"):
    return SimpleNamespace(label=label, bmd_str=bmd, bmdl_str=bmdl, bmd_status="viable",
                           noel=noel, loel=loel)


def _tables():
    return {"Clinical Chemistry": {"Male": [
        _row("Cholesterol", "0.5", 37.0, 111.0),     # 74- to 222-fold: flagged
        _row("Albumin", "30", 37.0, 111.0),          # plausible
        _row("Globulin", "NVM", 4.0, 12.0, "NVM"),   # no number to screen
    ]}, "Hormones": {"Female": [
        _row("Thyroid Stimulating Hormone", "1.0", None, 37.0),  # no NOEL: LOEL, 37-fold
    ]}}


class _Store:
    def __init__(self):
        self.docs = {}

    def read_json(self, dtxsid, name):
        return self.docs.get(name)

    def write_json(self, dtxsid, name, data):
        self.docs[name] = data


def test_screen_flags_bmds_far_below_noel_else_loel():
    flags = screen(_tables())
    assert [(f["key"], f["fold"]) for f in flags] == [
        ("Male|Clinical Chemistry|Cholesterol", [74, 222]),
        ("Female|Hormones|Thyroid Stimulating Hormone", [None, 37]),
    ]


def test_a_flag_with_no_decision_is_pending_and_keeps_its_number():
    tables = _tables()
    flags = apply_reviews(tables, None)
    assert len(pending(flags)) == 2
    assert tables["Clinical Chemistry"]["Male"][0].bmd_str == "0.5"


def test_a_rejected_bmd_becomes_urep_on_its_row_and_an_accepted_one_stays():
    store, tables = _Store(), _tables()
    record_reviews(store, "D", {
        "Male|Clinical Chemistry|Cholesterol": {"decision": "unreliable", "reason": "fit artifact"},
        "Female|Hormones|Thyroid Stimulating Hormone": {"decision": "reliable", "reason": "plausible"},
    }, screen(tables))
    flags = apply_reviews(tables, store.docs[REVIEWS_FILE])
    chol = tables["Clinical Chemistry"]["Male"][0]
    assert (chol.bmd_str, chol.bmdl_str, chol.bmd_status) == ("UREP", "UREP", "UREP")
    assert chol._urep == {"bmd": "0.5", "bmdl": "1", "fold": [74, 222], "reason": "fit artifact"}
    assert tables["Hormones"]["Female"][0].bmd_str == "1.0"
    assert not pending(flags)


def test_a_decision_holds_only_for_the_bmd_it_was_made_on():
    store, tables = _Store(), _tables()
    record_reviews(store, "D", {"Male|Clinical Chemistry|Cholesterol":
                                {"decision": "unreliable", "reason": "fit artifact"}}, screen(tables))
    tables["Clinical Chemistry"]["Male"][0].bmd_str = "0.6"      # a reprocess moved it
    flags = apply_reviews(tables, store.docs[REVIEWS_FILE])
    assert [f["key"] for f in pending(flags)][0] == "Male|Clinical Chemistry|Cholesterol"
    assert tables["Clinical Chemistry"]["Male"][0].bmd_str == "0.6"


def test_a_replaced_decision_is_kept_in_the_history():
    store, tables = _Store(), _tables()
    key = "Male|Clinical Chemistry|Cholesterol"
    record_reviews(store, "D", {key: {"decision": "reliable", "reason": "first look"}}, screen(tables))
    before = reviews_hash(store.docs[REVIEWS_FILE])
    record_reviews(store, "D", {key: {"decision": "unreliable", "reason": "second look"}}, screen(tables))
    reviews = store.docs[REVIEWS_FILE]
    assert reviews["decisions"][key]["decision"] == "unreliable"
    assert [h["reason"] for h in reviews["history"]] == ["first look"]
    assert reviews_hash(reviews) != before


# --- the summary, the narrative and the table follow the decision -----------

def _cc_row(label, bmd, noel, loel, values):
    from bmdx_pipe import TableRow
    return TableRow(label=label, values_by_dose=values, n_by_dose={}, bmd_str=bmd, bmdl_str="0.2",
                    trend_marker="**", bmd_status="viable", loel=loel, noel=noel, direction="DOWN",
                    responsive=True, missing_animals_by_dose={})


def _cc_tables():
    vals = {0.0: "100 ± 2", 37.0: "98 ± 2", 111.0: "80 ± 2**", 333.0: "70 ± 2**"}
    return {"Clinical Chemistry": {"Male": [_cc_row("Cholesterol", "0.5", 37.0, 111.0, vals)]}}


def test_no_bmd_becomes_urep_without_a_reviewer():
    from pipeline.processing_helpers import _build_apical_bmd_summary
    tables = _cc_tables()
    apply_reviews(tables, None)
    [entry] = _build_apical_bmd_summary(tables)
    assert entry["bmd"] == "0.5" and entry["review"] == "pending"
    assert not entry.get("anomalous")


def test_a_rejected_bmd_is_urep_in_the_summary_and_the_narrative():
    from narrative.unified_narrative import _build_sub_platform_paragraphs
    from pipeline.processing_helpers import _build_apical_bmd_summary

    store, tables = _Store(), _cc_tables()
    record_reviews(store, "D", {"Male|Clinical Chemistry|Cholesterol":
                                {"decision": "unreliable", "reason": "fit artifact"}}, screen(tables))
    apply_reviews(tables, store.docs[REVIEWS_FILE])
    [entry] = _build_apical_bmd_summary(tables)
    assert (entry["bmd"], entry["bmdl"], entry["direction"], entry["anomalous"]) == \
        ("UREP", "UREP", "–", True)
    assert (entry["bmd_original"], entry["fold"]) == ("0.5", [74, 222])

    [para] = _build_sub_platform_paragraphs("Clinical Chemistry", tables["Clinical Chemistry"],
                                            "X", "mg/kg")
    assert "The BMD and BMDL were" not in para
    assert ("with a negative trend. Although a BMD was estimated, its value was much lower "
            "(approximately 74- to 222-fold) than would be expected given the endpoint-specific "
            "NOEL and LOEL values") in para


def test_the_summary_table_explains_urep():
    from rendering.render_common import UREP_NOTE, bmd_summary_plan
    from document_model.document_node import DocNode

    node = DocNode(id="bmd-summary", title="Apical Endpoint BMD Summary")
    data = {"bmd_summary": {"endpoints": [
        {"sex": "Male", "endpoint": "Cholesterol", "bmd": "UREP", "bmdl": "UREP",
         "loel": 111.0, "noel": 37.0, "direction": "–", "anomalous": True}]}}
    assert UREP_NOTE in [f["text"] for f in bmd_summary_plan(node, data).footnotes]


# --- the safeguards ----------------------------------------------------------

def test_a_review_names_flagged_endpoints_a_known_decision_and_a_reason():
    from safeguards.inputs import bmd_review_errors

    flags = screen(_tables())
    assert bmd_review_errors({}, flags) == ["no decisions were given"]
    errors = bmd_review_errors({
        "Male|Clinical Chemistry|Albumin": {"decision": "unreliable", "reason": "x"},
        "Male|Clinical Chemistry|Cholesterol": {"decision": "maybe", "reason": " "},
    }, flags)
    assert errors == [
        "Male|Clinical Chemistry|Albumin is not a BMD the last Process flagged",
        "Male|Clinical Chemistry|Cholesterol: the decision must be “unreliable” or “reliable”",
        "Male|Clinical Chemistry|Cholesterol: the reviewer's reason is missing",
    ]


def test_a_data_table_prints_the_reviewed_bmd_with_the_books_note():
    """NIEHS-07 … 10 print a rejected BMD in the data tables as its value with
    a lettered note ("0.811^h"); only the BMD summary prints UREP."""
    from tables.table_builder_common import (
        REVIEWED_BMD_NOTE, finalize_footnotes, lettered_footnote, mark_reviewed_bmd,
        reviewed_bmd_footnotes,
    )

    store, tables = _Store(), _cc_tables()
    record_reviews(store, "D", {"Male|Clinical Chemistry|Cholesterol":
                                {"decision": "unreliable", "reason": "fit artifact"}}, screen(tables))
    apply_reviews(tables, store.docs[REVIEWS_FILE])
    serialized = {"Male": []}
    for row in tables["Clinical Chemistry"]["Male"]:
        entry = {"label": row.label, "bmd": row.bmd_str or "—", "bmdl": row.bmdl_str or "—"}
        mark_reviewed_bmd(entry, row)
        serialized["Male"].append(entry)
    chol = serialized["Male"][0]
    assert (chol["bmd"], chol["bmdl"]) == ("0.5", "0.2")

    footnotes = [lettered_footnote("data format", "data_format")]
    footnotes += reviewed_bmd_footnotes(serialized)
    finalize_footnotes(footnotes, serialized)
    assert footnotes[-1]["text"] == REVIEWED_BMD_NOTE
    assert chol["markers"] == {"bmd": "b", "bmdl": "b"}
    assert all("markers" not in e for e in serialized["Male"][1:])


def test_a_table_with_no_rejected_bmd_has_no_note_and_nd_stays_nd():
    from tables.table_builder_common import mark_reviewed_bmd, reviewed_bmd_footnotes

    row = SimpleNamespace(_urep={"bmd": "0.5", "bmdl": "1"})
    entry = {"bmd": "ND", "bmdl": "ND"}          # the statistical gate left it ND
    mark_reviewed_bmd(entry, row)
    assert entry == {"bmd": "ND", "bmdl": "ND"}
    assert reviewed_bmd_footnotes({"Male": [entry]}) == []
