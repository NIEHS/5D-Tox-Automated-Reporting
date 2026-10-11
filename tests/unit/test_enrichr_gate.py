"""Gene lists go to the public Enrichr service only when explicitly allowed.

The genomics cluster chart labelled clusters by sending each cluster's genes to
Enrichr (maayanlab.cloud) — outside the LLM egress guard — and did so for the
unpublished BPAF and Triclosan studies.  The client now fails closed unless
BMDX_ALLOW_ENRICHR=1; the chart labels clusters from our own GO terms.
"""

import urllib.request

import pytest

from genomics.genomics_viz import enrich_clusters
from knowledge_base import enrichr_client

GENE_SETS = [{"go_id": f"GO:{i}", "go_term": f"term {i}", "genes": "TP53;BRCA1;CDKN1A;MDM2", "bmd": 10.0 + i}
             for i in range(3)]
CLUSTERS = {"GO:0": 0, "GO:1": 0, "GO:2": 1}


@pytest.fixture
def no_network(monkeypatch):
    def fail(*a, **k):
        raise AssertionError("network call made")
    monkeypatch.setattr(urllib.request, "urlopen", fail)


def test_client_refuses_without_the_opt_in(monkeypatch, no_network):
    monkeypatch.delenv(enrichr_client.ALLOW_ENV, raising=False)
    with pytest.raises(enrichr_client.EnrichrDisabled):
        enrichr_client.enrichr_submit(["TP53"], "x")


def test_chart_labels_come_from_internal_terms_when_off(monkeypatch, no_network):
    monkeypatch.delenv(enrichr_client.ALLOW_ENV, raising=False)
    rows = enrich_clusters(GENE_SETS, CLUSTERS)
    assert rows and all(r["source"] == "internal" for r in rows)
    assert rows[0]["terms"][0] == "term 0"


def test_opt_in_turns_it_on(monkeypatch):
    monkeypatch.setenv(enrichr_client.ALLOW_ENV, "1")
    assert enrichr_client.enrichr_allowed()
