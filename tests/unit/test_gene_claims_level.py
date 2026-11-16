"""A claim from a paper that mentions a gene is not evidence about the gene:
gene_claims says which claims name it (independent review, 2026-11-16)."""

import duckdb

from knowledge_base.toxkb import ToxKBQuerier


def test_claims_are_claim_level_only_when_they_name_the_gene(tmp_path):
    db = tmp_path / "kb.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE papers (paper_id VARCHAR, title VARCHAR, year INT, venue VARCHAR,"
                " doi VARCHAR, citation_count INT)")
    con.execute("CREATE TABLE paper_genes (paper_id VARCHAR, gene_symbol VARCHAR)")
    con.execute("CREATE TABLE paper_claims (paper_id VARCHAR, claim VARCHAR)")
    con.execute("INSERT INTO papers VALUES ('p1', 'Liver study', 2020, '', '', 1)")
    con.execute("INSERT INTO paper_genes VALUES ('p1', 'NFE2L2'), ('p1', 'CYP1A1')")
    con.execute("INSERT INTO paper_claims VALUES ('p1', 'Body weight fell at 1000 mg/kg.'),"
                " ('p1', 'Nfe2l2 activation induced Nqo1 in the liver.')")
    con.close()

    kb = ToxKBQuerier.__new__(ToxKBQuerier)
    kb.con = duckdb.connect(str(db), read_only=True)
    claims = kb.gene_claims("NFE2L2")
    assert [(c["association"], c["claim"][:9]) for c in claims] == [
        ("claim", "Nfe2l2 ac"), ("paper", "Body weig")]
    assert all(c["association"] == "paper" for c in kb.gene_claims("CYP1A1"))
    assert claims[0]["paper_id"] == "p1"
