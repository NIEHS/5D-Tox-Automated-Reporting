"""The Summary section is built from the session's results (NIEHS-10 shape):
study purpose, unreliable apical BMDs, the most sensitive apical endpoints,
per-organ gene set and gene, and the point of departure per sex."""

from narrative.report_summary import build_report_summary

_APICAL = [
    {"sex": "Male", "endpoint": "Relative Liver Weight", "platform": "Organ Weight",
     "bmd": "36.7", "bmdl": "14.2", "loel": 125.0, "noel": 62.5, "direction": "UP",
     "bmd_status": "viable"},
    {"sex": "Male", "endpoint": "Absolute Liver Weight", "platform": "Organ Weight",
     "bmd": "63", "bmdl": "16", "loel": 250.0, "noel": 125.0, "direction": "UP",
     "bmd_status": "viable"},
]
_GENOMICS = {"liver_male": {
    "gene_sets_by_stat": {"fifth_pct": [
        {"go_id": "GO:0009062", "go_term": "fatty acid catabolic process",
         "bmd": 4.232, "bmdl": 2.172}]},
    "top_genes": [{"gene_symbol": "Eci1", "bmd": 3.341, "bmdl": 0.349}],
}}
_DOSES = [0.0, 7.8, 15.6, 31.25, 62.5, 125.0, 250.0, 500.0, 1000.0]


def _build(**kw):
    args = dict(chemical_name="Triclosan", dose_groups=_DOSES, dose_unit="mg/kg",
                bmd_stat="fifth_pct", sexes=["Male"])
    args.update(kw)
    return build_report_summary(kw.pop("apical", _APICAL), kw.pop("genomics", _GENOMICS),
                                **{k: v for k, v in args.items() if k not in ("apical", "genomics")})


def test_full_shape():
    paras = _build()
    assert paras[0] == ("This study used a transcriptomic approach and standard toxicological "
                        "endpoints to estimate the in vivo biological potency of Triclosan.")
    assert "most sensitive apical endpoint in male rats was increased relative liver weight" in paras[1]
    assert "36.7 (14.2) mg/kg" in paras[1] and "Increased absolute liver weight was the next" in paras[1]
    assert "fatty acid catabolic process (GO:0009062)" in paras[2] and "Eci1" in paras[2]
    assert "point of departure with a reliable estimate was a transcriptional change in the gene Eci1" in paras[3]
    assert "Gene set changes provided potency estimates in the same range as that value." in paras[3]
    assert "Apical endpoints provided potency estimates higher than that value." in paras[3]


def test_background_sentence_leads():
    paras = _build(abstract_background="Triclosan is an antimicrobial agent.")
    assert paras[0].startswith("Triclosan is an antimicrobial agent. This study used")


def test_apical_measured_but_none_with_a_bmd():
    paras = _build(apical=[], apical_evaluated=True)
    assert "standard toxicological endpoints" in paras[0]
    assert "In male rats, there were no apical endpoints for which a BMD value could be reliably estimated." in paras


def test_anomalous_bmds_are_named_and_excluded():
    flagged = [{**_APICAL[0], "bmd": "UREP", "bmdl": "UREP", "anomalous": True}, _APICAL[1]]
    paras = _build(apical=flagged)
    assert "relative liver weight in male rats" in paras[1] and "unreliable" in paras[1]
    assert paras[2].startswith("Taking this into account, the most sensitive apical endpoint "
                               "in male rats was increased absolute liver weight")


def test_nothing_to_summarize():
    assert build_report_summary([], {}, chemical_name="X") == []
