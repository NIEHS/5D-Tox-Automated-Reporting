"""
The study's data deposit (pipeline.deposit, ADR-0029): which kind each deposited
file is, which species its study used, and how the document lists them — a
derived supplementary-material per kind, a `repeat: deposit_species` section per
species.
"""

import json
from pathlib import Path

import pytest

from pipeline import deposit as dep
from pipeline.deposit import build_manifest, classify, default_caption

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "reference"
BOOKSHELF = Path(__file__).resolve().parents[2] / "assets" / "cebs" / "_bookshelf"


@pytest.mark.parametrize("name, kind", [
    ("C20022-01_Individual_Animal_Hormone_Data.xlsx", "animal-data"),
    ("C10866B_Individual_Animal_Body_Weight_Data.xlsx", "animal-data"),
    ("C20022-01_PA41_-_Clinical_Chemistry_Summary.pdf", "study-tables"),
    ("108020004_I04G_Mean_Body_Weight_Gain.pdf", "study-tables"),
    ("108020004_Blood_and_Tissue_Concentration.pdf", "study-tables"),
    ("C20022-01_Organ_Weights_Summary.docx", "apical"),
    ("C20022-01_Appendix_Male_07282021.docx", "apical"),
    ("C20022-01_bmds.zip", "apical"),
    ("108020004_4D_Rat_NonGenomic.bm2", "apical"),
    ("Read_Me.docx", "apical"),
    ("108020004_4D_Rat_Genomic.bm2", "genomic"),
    ("C20022-01_Liver_PCA.zip", "genomic"),
    ("BMDExpress_Software.zip", "genomic"),
    ("Materials_and_Methods.pdf", "methods"),
    ("Theoretical_Inhaled_Dose.pdf", "inhaled-dose"),
    ("DTT_tBMD_Pipelinebm2.zip", "software"),
])
def test_a_file_is_classified_by_its_name(name, kind):
    assert classify(name) == kind


def test_the_caption_is_the_name_without_study_number_and_extension():
    assert default_caption("C20022-01_Organ_Weights_Summary.docx") == "Organ Weights Summary"
    assert default_caption("Theoretical_Inhaled_Dose.pdf") == "Theoretical Inhaled Dose"


def test_each_study_number_has_its_species():
    m = build_manifest([("108020004_4D_Rat_Genomic.bm2", 1), ("108020004_I02_Animal_Removals.pdf", 1),
                        ("108020005_4D_Mouse_Genomic.bm2", 1), ("108020005_Curve_Fit_Mouse_Liver.txt", 1),
                        ("Materials_and_Methods.pdf", 1)])
    by = {f["file"]: f["species"] for f in m["files"]}
    assert by["108020004_I02_Animal_Removals.pdf"] == "rat"
    assert by["108020005_Curve_Fit_Mouse_Liver.txt"] == "mouse"
    assert by["Materials_and_Methods.pdf"] is None
    assert m["species"] == [{"key": "rat", "title": "Rats"}, {"key": "mouse", "title": "Mice"}]


def _published_groups(report: str) -> dict[str, tuple[str, str | None]]:
    """file → (kind, species) as the published book lists it."""
    from rendering.bits_bundle import read_bundle
    kinds = {"Apical Benchmark Dose Analysis": "apical",
             "Genomic Benchmark Dose Analysis": "genomic", "Study Tables": "study-tables",
             "Individual Animal Data": "animal-data", "Materials and Methods": "methods",
             "Theoretical Inhaled Dose": "inhaled-dose",
             "Analysis Pipeline Evaluation": "software"}
    species = {"Rats": "rat", "Mice": "mouse"}
    out = {}
    for m in read_bundle(BOOKSHELF / report).iter("media"):
        titles = [a.findtext("title") for a in m.iterancestors("sec")]   # innermost first
        sp = next((species[t] for t in titles if t in species), None)
        out[m.get("{http://www.w3.org/1999/xlink}href")] = (kinds[titles[0]], sp)
    return out


@pytest.mark.parametrize("report", ["NIEHS-02", "NIEHS-03", "NIEHS-04", "NIEHS-05", "NIEHS-06",
                                    "NIEHS-07", "NIEHS-08", "NIEHS-09", "NIEHS-10",
                                    "NIEHS-12", "NIEHS-13"])
def test_the_rules_reproduce_every_published_grouping(report):
    if not (BOOKSHELF / report / "TOC.nxml").exists():
        pytest.skip(f"published {report} bundle not downloaded (assets/cebs/_bookshelf)")
    listing = json.loads((FIXTURES / report / "deposit-files.json").read_text(encoding="utf-8"))
    manifest = build_manifest([tuple(f) for f in listing])
    multi = len(manifest["species"]) > 1
    ours = {f["file"]: (f["kind"], f["species"] if multi else None) for f in manifest["files"]}
    assert ours == _published_groups(report)


@pytest.fixture()
def study(tmp_path, monkeypatch):
    """A session store and a templates root of our own."""
    import pipeline.session_store as store
    from document_model import document_template as dt
    import document_model.document_config  # noqa: F401 — builds the shared tree first
    monkeypatch.setattr(store, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(dt, "TEMPLATES_DIR", tmp_path / "templates")
    (tmp_path / "sessions" / "DTXSID0000001").mkdir(parents=True)
    (tmp_path / "templates" / "studies" / "DTXSID0000001").mkdir(parents=True)
    deposit_dir = tmp_path / "deposit"
    deposit_dir.mkdir()
    for name in ("C20022-01_Appendix_Male_1.docx", "C20022-01_PA41_Summary.pdf", "TOC.pdf"):
        (deposit_dir / name).write_bytes(b"x" * 10)
    return tmp_path


def test_a_recorded_deposit_takes_the_study_s_own_wording(study):
    (study / "templates/studies/DTXSID0000001/deposit.yaml").write_text(
        "captions:\n  C20022-01_Appendix_Male_1.docx: Male BMD Apical Endpoints Model Fits\n"
        "kinds:\n  C20022-01_PA41_Summary.pdf: apical\n")
    dep.record_deposit("DTXSID0000001", study / "deposit", ("TOC.pdf",))
    loaded = dep.load_deposit("DTXSID0000001")
    assert [(f["file"], f["kind"], f["caption"], f["size"]) for f in loaded["files"]] == [
        ("C20022-01_Appendix_Male_1.docx", "apical", "Male BMD Apical Endpoints Model Fits", 10),
        ("C20022-01_PA41_Summary.pdf", "apical", "PA41 Summary", 10)]
    assert dep.load_deposit("DTXSID0000002") is None


def test_a_stated_kind_must_be_known(study):
    (study / "templates/studies/DTXSID0000001/deposit.yaml").write_text(
        "kinds:\n  C20022-01_PA41_Summary.pdf: tables\n")
    with pytest.raises(ValueError, match="unknown kind"):
        dep.record_deposit("DTXSID0000001", study / "deposit")


def _sections(nodes, depth=0):
    out = []
    for n in nodes:
        out.append(("  " * depth) + f"{n.sec_label or ''} {n.title} [{n.scope_species}]".strip())
        out += _sections(n.children, depth + 1)
    return out


def test_a_repeated_section_is_one_per_deposited_species():
    from document_model.document_template import instantiate
    from document_model.document_tree import study_tree

    tree = instantiate([{"region": "back", "children": [{
        "id": "app", "type": "appendix", "title": "Supplemental Data", "children": [
            {"id": "sp", "type": "heading-only", "title": "Species", "repeat": "deposit_species",
             "children": [{"id": "ap", "type": "heading-only", "title": "Apical", "children": [
                 {"id": "ap-files", "type": "supplementary-material", "binding": "derived",
                  "title": "", "deposit_group": "apical"}]}]}]}]}])
    two = {"deposit": {"species": [{"key": "rat", "title": "Rats"},
                                   {"key": "mouse", "title": "Mice"}]}}
    nodes = study_tree(tree, None, None, two)
    assert [ln for ln in _sections(nodes) if "[None]" not in ln or "Supplemental" in ln] == [
        "Supplemental Data [None]",
        "  A.1 Rats [rat]", "    A.1.1 Apical [rat]", "      [rat]",
        "  A.2 Mice [mouse]", "    A.2.1 Apical [mouse]", "      [mouse]"]
    assert tree[0].children[0].title == "Species"                # the shared tree is untouched
    # No deposit species: the section's children stand in its place.
    flat = study_tree(tree, None, None, {})
    assert [n.title for n in flat[0].children] == ["Apical"]


def test_a_derived_list_shows_its_kind_of_the_deposit():
    from document_model.document_node import DocNode
    from rendering.render_common import supplied_files, supplied_files_pending

    deposit = build_manifest([("108020004_4D_Rat_NonGenomic.bm2", 5),
                              ("108020005_4D_NonGenomic_Mouse.bm2", 7),
                              ("108020005_I02_Animal_Removals_Mouse.pdf", 1)])
    node = DocNode(id="f", title="", node_type="supplementary-material", binding="derived",
                   deposit_group="apical", scope_species="mouse")
    assert [(f.file, f.size) for f in supplied_files(node, {"deposit": deposit})] == [
        ("108020005_4D_NonGenomic_Mouse.bm2", 7)]
    assert "no data deposit" in supplied_files_pending(node, {})
    node.deposit_group = "software"
    assert supplied_files_pending(node, {"deposit": deposit}).startswith("No files")


@pytest.mark.parametrize("entry, message", [
    ({"id": "f", "type": "supplementary-material", "binding": "derived", "title": "",
      "deposit_group": "tables"}, "deposit_group"),
    ({"id": "f", "type": "supplementary-material", "title": "x", "content_file": "a.pdf",
      "deposit_group": "apical"}, "only valid on a derived"),
    ({"id": "s", "type": "heading-only", "title": "S", "repeat": "organs"}, "repeat must be"),
])
def test_deposit_fields_are_checked(entry, message):
    from document_model.document_template import instantiate
    with pytest.raises(ValueError, match=message):
        instantiate([{"region": "back", "children": [
            {"id": "app", "type": "appendix", "title": "A", "children": [entry]}]}])


@pytest.mark.parametrize("report", ["NIEHS-02", "NIEHS-03", "NIEHS-04", "NIEHS-05", "NIEHS-06",
                                    "NIEHS-07", "NIEHS-08", "NIEHS-09", "NIEHS-10",
                                    "NIEHS-12", "NIEHS-13"])
def test_every_caption_is_the_published_wording(report):
    """The file-name default, else the study's own wording (deposit.yaml)."""
    if not (BOOKSHELF / report / "TOC.nxml").exists():
        pytest.skip(f"published {report} bundle not downloaded (assets/cebs/_bookshelf)")
    from tooling.bits_structure import PUBLISHED
    from tooling.deposit_captions import published_captions
    dtxsid = {r: d for d, r in PUBLISHED.items()}[report]
    listing = json.loads((FIXTURES / report / "deposit-files.json").read_text(encoding="utf-8"))
    captions = dep._study_statements(dtxsid).get("captions")
    manifest = build_manifest([tuple(f) for f in listing], captions=captions)
    assert {f["file"]: f["caption"] for f in manifest["files"]} == published_captions(report)


def test_supplemental_data_opens_with_the_deposit_doi():
    """Every NIEHS book opens Supplemental Data with "The following supplemental
    files are available at https://doi.org/<deposit DOI>.": a node's
    `deposit_text` gives it when the study's deposit has a DOI and files; the
    study's own authored text comes first, `missing_content_text` without one."""
    from document_model.document_node import DocNode
    from document_model.document_tree import study_tree

    def node():
        return DocNode(id="f-body", node_type="freeform-block", title="",
                       session_content="appendix-f",
                       deposit_text="The following supplemental files are available at {doi}.",
                       missing_content_text="Supplemental data files are not available.")

    deposit = {"doi": "10.22427/NIEHS-DATA-NIEHS-02", "files": [{"file": "a.pdf"}]}
    got = study_tree([node()], None, {}, {"deposit": deposit})[0].resolved_content
    assert got["html"] == ('<p>The following supplemental files are available at <a href='
                           '"https://doi.org/10.22427/NIEHS-DATA-NIEHS-02">https://doi.org/'
                           '10.22427/NIEHS-DATA-NIEHS-02</a>.</p>')
    assert got["latex"] == ("The following supplemental files are available at "
                            "\\url{https://doi.org/10.22427/NIEHS-DATA-NIEHS-02}.")
    authored = {"appendix-f": {"html": "<p>Own.</p>", "latex": "Own."}}
    assert study_tree([node()], None, authored, {"deposit": deposit})[0].resolved_content[
        "html"] == "<p>Own.</p>"
    for facts in ({"deposit": {**deposit, "files": []}}, {"deposit": None}, None):
        assert "not available" in study_tree([node()], None, {}, facts)[0].resolved_content["html"]
