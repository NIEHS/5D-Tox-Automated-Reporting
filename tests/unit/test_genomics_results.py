"""
The gene set and gene results as the books write them (rendering.
genomics_results): each sentence built from the tables, matched here against
NIEHS-13's published sentences (assets/cebs/_bookshelf/NIEHS-13, Results).
"""

import pytest

from rendering.genomics_results import GENE_NAME_PENDING, attach_genomics_results
from rendering.render_common import inline_plain_text, node_data

DISPLAY = {"stat": "fifth_pct", "unit": "ppm", "decimals": 1}
DOSES = [0, 1, 10, 50, 150, 400, 800]


def _design(species):
    return {"species": species, "route": "inhaled", "sexes": ["female"], "duration_days": 5}


def _study(key, title, species):
    rows = [{"doses": DOSES}]
    return {"key": key, "title": title, "dtxsid": f"X_{key}",
            "data": {"study_design": _design(species),
                     "apical_sections": [{"table_data": {"Female": rows}}]}}


def _gs(go_id, term, bmd, bmdl):
    return {"go_id": go_id, "go_term": term, "bmd": bmd, "bmdl": bmdl}


def _gene(sym, gid, bmd, bmdl, direction):
    return {"gene": sym, "entrez_id": gid, "bmd": bmd, "bmdl": bmdl, "direction": direction}


@pytest.fixture
def report(monkeypatch):
    import genomics.gene_names as gn
    monkeypatch.setattr(gn, "_read_cache", lambda: {
        "25353": "secreted phosphoprotein 1", "24309": "D-box binding PAR bZIP transcription factor",
        "313050": "LCK proto-oncogene, Src family tyrosine kinase", "12623": "carboxylesterase 1G",
        "52670": "cleavage and polyadenylation specific factor 4-like"})
    monkeypatch.delenv(gn.ALLOW_ENV, raising=False)
    heart_sets = {"type": "gene_set", "organ": "heart", "display": DISPLAY, "table_number": 7,
                  "sexes": [
                      {"sex": "Rats", "study": "rat", "gene_sets": [
                          _gs("GO:0044770", "cell cycle phase transition", 141.36, 55.85),
                          _gs("GO:0044772", "mitotic cell cycle phase transition", 141.36, 55.85)]},
                      {"sex": "Mice", "study": "mouse", "gene_sets": [
                          _gs("GO:1901617", "organic hydroxy compound biosynthetic process", 91.0, 25.1),
                          _gs("GO:0007623", "circadian rhythm", 139.5, 37.4)]}]}
    ovary_sets = {"type": "gene_set", "organ": "ovary", "display": DISPLAY, "table_number": 11,
                  "sexes": [{"sex": "Rats", "study": "rat", "gene_sets": [
                      _gs("GO:0001667", "ameboidal-type cell migration", 223.1, 90.9),
                      _gs("GO:2001235", "positive regulation of apoptotic signaling pathway",
                          282.7, 140.2)]},
                      {"sex": "Mice", "study": "mouse", "gene_sets": []}]}
    heart_genes = {"type": "gene", "organ": "heart", "display": DISPLAY, "table_number": 13,
                   "sexes": [{"sex": "Rats", "study": "rat", "top_genes": [
                       _gene("Lck", "313050", 31.7, 6.0, "down"),
                       _gene("Spp1", "25353", 108.2, 30.6, "up"),
                       _gene("Dbp", "24309", 189.0, 183.6, "up")]},
                       {"sex": "Mice", "study": "mouse", "top_genes": [
                           _gene("Ces1g", "12623", 0.22, 0.05, "up"),
                           _gene("Cpsf4l", "52670", 8.9, 1.9, "down"),
                           _gene("Xyz1", "999", 9.0, 2.0, "up")]}]}
    data = {"studies": [_study("rat", "Rats", "rat"), _study("mouse", "Mice", "mouse")],
            "study_design": {"route": "inhaled", "studies": [_design("rat"), _design("mouse")]},
            "abbreviation": "1,4-DCB", "dose_unit": "ppm",
            "genomics_sections": [heart_sets, ovary_sets, heart_genes]}
    attach_genomics_results(data, None)
    return data


def _text(paragraphs):
    return [inline_plain_text(p) for p in paragraphs]


def test_a_tissue_s_gene_set_results_per_study(report):
    heart = report["genomics_sections"][0]["results"]
    assert _text(heart["rat"]) == [
        "The most sensitive GO biological processes for which a BMD value could be reliably "
        "calculated were cell cycle phase transition (GO:0044770) and mitotic cell cycle phase "
        "transition (GO:0044772), both with a 5th percentile BMD (BMDL) of 141.4 (55.9) ppm "
        "(Table 7)."]
    assert _text(heart["mouse"]) == [
        "The most sensitive GO biological processes for which a BMD value could be reliably "
        "calculated were organic hydroxy compound biosynthetic process (GO:1901617) and "
        "circadian rhythm (GO:0007623) with 5th percentile BMDs (BMDLs) of 91.0 (25.1) and "
        "139.5 (37.4) ppm, respectively (Table 7)."]
    ovary = report["genomics_sections"][1]["results"]
    assert _text(ovary["mouse"]) == [
        "In mice exposed to 1,4-DCB, there were no active GO terms (i.e., no gene expression "
        "response at the gene set level)."]


def test_the_bmd_l_is_a_subscript_and_a_symbol_italic(report):
    (para,) = report["genomics_sections"][0]["results"]["rat"]
    assert {"type": "sub", "text": "L"} in para
    (genes,) = report["genomics_sections"][2]["results"]["rat"]
    assert {"type": "italic", "text": "Spp1"} in genes


def test_a_tissue_s_gene_results(report):
    genes = report["genomics_sections"][2]["results"]
    assert _text(genes["rat"]) == [
        "Only three genes met the criteria. Of these three genes, the most sensitive "
        "upregulated genes with a calculated BMD were Spp1 (secreted "
        "phosphoprotein 1) and Dbp (D-box binding PAR bZIP transcription factor) with BMDs "
        "(BMDLs) of 108.2 (30.6) and 189.0 (183.6) ppm, respectively. One gene, Lck (LCK "
        "proto-oncogene, Src family tyrosine kinase), was downregulated with a BMD (BMDL) of "
        "31.7 (6.0) ppm."]
    assert _text(genes["mouse"]) == [
        "The most sensitive heart gene in mice, exhibiting an increase in expression, was "
        "Ces1g (carboxylesterase 1G) with an estimated median BMD <0.333 ppm. Only three genes "
        "met the criteria. Of these three genes, one gene, Xyz1 (" + GENE_NAME_PENDING + "), was "
        "upregulated with a BMD (BMDL) of 9.0 (2.0) ppm. One gene, Cpsf4l (cleavage and "
        "polyadenylation specific factor 4-like), was downregulated with a BMD (BMDL) of "
        "8.9 (1.9) ppm."]


def test_the_sections_open_and_the_gene_set_summary(report):
    (intro,) = _text(report["gene_intro"]["paragraphs"])
    assert intro.startswith("The top 10 genes ranked by BMD potency are shown in the heart "
                            "(Table 13). No genes had estimated median BMD values <0.333 ppm "
                            "with the exception of one heart gene in mice.")
    first, second = _text(report["gene_set_intro"]["paragraphs"])
    assert "most sensitive to 1,4-DCB exposure" in first
    assert "shown in the heart (Table 7) and ovary (Table 11). No gene sets" in second
    (summary,) = _text(report["gene_set_summary"]["paragraphs"])
    # The same tissue in both studies: one sentence (NIEHS-12's form).
    assert summary == (
        "In both rats and mice exposed to 1,4-DCB, the heart had the gene set with the lowest "
        "BMD 5th percentile value, corresponding to cell cycle phase transition (GO:0044770) "
        "and organic hydroxy compound biosynthetic process (GO:1901617), respectively. The "
        "BMDs (BMDLs) were 141.4 (55.9) and 91.0 (25.1) ppm, respectively.")


def test_a_tissue_section_renders_its_study_s_results(report):
    from document_model.document_node import DocNode
    node = DocNode(id="gs-heart-mouse", title="Mice", node_type="narrative",
                   data_key="gene_set_results", scope_species="mouse", scope_organ="heart")
    scoped = node_data(node, report)
    assert _text(scoped["gene_set_results"]["paragraphs"])[0].startswith(
        "The most sensitive GO biological processes")


def test_gene_names_are_not_looked_up_unless_allowed(monkeypatch, tmp_path):
    import genomics.gene_names as gn
    monkeypatch.setattr(gn, "CACHE_FILE", tmp_path / "names.json")
    monkeypatch.delenv(gn.ALLOW_ENV, raising=False)
    monkeypatch.setattr(gn, "_fetch", lambda ids: pytest.fail("looked up without consent"))
    assert gn.gene_names(["313050"]) == {}
