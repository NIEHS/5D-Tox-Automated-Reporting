"""A gene-expression .bm2 is recognised by its transcriptomics chip, not its name.

The 2025 DTT projects ("108020004_4D_Genomic_Rats.bm2", experiments
"rat_4D_HE_No0") match no filename or experiment-name pattern; their chip is a
BioSpyder S1500 panel.  Apical ("non-genomic") projects carry BMDExpress's
placeholder "generic" chip and must stay unclassified by this rule.
"""

import pytest

from bmdx_pipe.file_integrator import _is_transcriptomic_chip, fingerprint_bm2


def _project(exp_name: str, chip) -> dict:
    return {"doseResponseExperiments": [{
        "name": exp_name,
        "chip": chip,
        "treatments": [{"name": "4DR1F1HE_S1_R1_001", "dose": 0.0},
                       {"name": "4DR1F2HE_S2_R1_001", "dose": 10.0}],
        "probeResponses": [{"probe": {"id": "A2M_7932"}, "responses": [1.0, 2.0]}],
        "experimentDescription": None,
    }]}


BIOSPYDER = {"provider": "BioSpyder", "species": "Rattus norvegicus",
             "name": "S1500_Plus_Rat", "geoName": "BioSpyder S1500_Rat"}
GENERIC = {"chipId": "generic", "provider": "generic", "species": "generic", "name": "Generic"}


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)


def test_dtt_genomic_project_classifies_as_gene_expression(tmp_path):
    fp = fingerprint_bm2("id", "108020004_4D_Genomic_Rats.bm2", str(tmp_path / "x.bm2"),
                         "2026-10-02", _project("rat_4D_HE_No0", BIOSPYDER))
    assert fp.data_type == "gene_expression"
    assert fp.platform is None


def test_generic_chip_project_is_not_gene_expression(tmp_path):
    fp = fingerprint_bm2("id", "108020004_4D_NonGenomic_Rats.bm2", str(tmp_path / "x.bm2"),
                         "2026-10-02", _project("108020004_4D_Rat_BMDExpress_Input_Fnl", GENERIC))
    assert fp.data_type != "gene_expression"


@pytest.mark.parametrize("chip,expected", [
    (BIOSPYDER, True),
    ({"provider": "Affymetrix", "name": "Rat230_2"}, True),
    (GENERIC, False),
    ({"provider": "generic", "name": "Generic"}, False),
    (None, False),
    ({}, False),
])
def test_is_transcriptomic_chip(chip, expected):
    assert _is_transcriptomic_chip(chip) is expected


def test_uncached_unnamed_bm2_is_exported_once_for_content(tmp_path, monkeypatch):
    """A .bm2 whose filename says nothing (e.g. "BPAF_0826.bm2") and that is not
    in the cache is deserialized on demand, not rejected as unassigned."""
    import bmdx_pipe.file_integrator as fi
    calls = []
    monkeypatch.setattr(fi, "_export_and_cache_bm2_json",
                        lambda path: calls.append(path) or _project("BPAF_S1_AA_liver_No0", BIOSPYDER))
    monkeypatch.setattr("bmdx_pipe.bm2_cache.get_json", lambda path: None)
    fp = fingerprint_bm2("id", "BPAF_0826.bm2", str(tmp_path / "BPAF_0826.bm2"), "2026-10-02")
    assert calls == [str(tmp_path / "BPAF_0826.bm2")]
    assert fp.data_type == "gene_expression"


def test_named_bm2_is_not_exported(tmp_path, monkeypatch):
    """When the filename already classifies the file, no Java export runs."""
    import bmdx_pipe.file_integrator as fi
    monkeypatch.setattr(fi, "_export_and_cache_bm2_json",
                        lambda path: pytest.fail("exported a filename-classified .bm2"))
    monkeypatch.setattr("bmdx_pipe.bm2_cache.get_json", lambda path: None)
    fp = fingerprint_bm2("id", "BPAF_gene_expression_0826.bm2", str(tmp_path / "x.bm2"), "2026-10-02")
    assert fp.data_type == "gene_expression"
