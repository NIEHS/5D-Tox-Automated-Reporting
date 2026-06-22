"""
ToxKBQuerier — read-only typed query helpers over bmdx.duckdb.

Wraps the toxicology knowledge base (genes, pathways, GO terms, papers, claims)
with a small set of typed query methods and a context-manager lifecycle so the
duckdb connection is always released.  Extracted from interpret.py so the DB
concern is isolated from the analysis and narrative layers (and so
enrichment_stats can type-reference it without importing interpret).
"""

import duckdb


class ToxKBQuerier:
    """Wraps bmdx.duckdb with typed query methods."""

    def __init__(self, db_path: str = "bmdx.duckdb"):
        self.con = duckdb.connect(db_path, read_only=True)

    def close(self):
        self.con.close()

    def __enter__(self) -> "ToxKBQuerier":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        # Always release the duckdb connection, even when the with-body raises;
        # don't suppress the exception (return falsy).
        self.close()
        return False

    def gene_pathways(self, gene: str) -> list[dict]:
        rows = self.con.execute(
            "SELECT pathway_db, pathway_id, pathway_name, species "
            "FROM pathways WHERE gene_symbol = ?",
            [gene],
        ).fetchall()
        return [
            {"pathway_db": r[0], "pathway_id": r[1],
             "pathway_name": r[2], "species": r[3]}
            for r in rows
        ]

    def gene_go_terms(self, gene: str) -> list[dict]:
        rows = self.con.execute(
            "SELECT g.go_id, t.go_term, t.cluster_id "
            "FROM gene_go_terms g JOIN go_terms t ON g.go_id = t.go_id "
            "WHERE g.gene_symbol = ?",
            [gene],
        ).fetchall()
        return [
            {"go_id": r[0], "go_term": r[1], "cluster_id": r[2]}
            for r in rows
        ]

    def gene_organs(self, gene: str) -> list[str]:
        row = self.con.execute(
            "SELECT organs FROM genes WHERE gene_symbol = ?",
            [gene],
        ).fetchone()
        if row and row[0]:
            return list(row[0])
        return []

    def gene_papers(self, gene: str) -> list[dict]:
        rows = self.con.execute(
            "SELECT p.paper_id, p.title, p.year, p.citation_count "
            "FROM papers p JOIN paper_genes pg ON p.paper_id = pg.paper_id "
            "WHERE pg.gene_symbol = ?",
            [gene],
        ).fetchall()
        return [
            {"paper_id": r[0], "title": r[1], "year": r[2],
             "citation_count": r[3]}
            for r in rows
        ]

    def gene_claims(self, gene: str) -> list[dict]:
        rows = self.con.execute(
            "SELECT pc.claim, p.title, p.year "
            "FROM paper_claims pc "
            "JOIN paper_genes pg ON pc.paper_id = pg.paper_id "
            "JOIN papers p ON pc.paper_id = p.paper_id "
            "WHERE pg.gene_symbol = ?",
            [gene],
        ).fetchall()
        return [{"claim": r[0], "paper_title": r[1], "year": r[2]} for r in rows]

    def pathway_genes(self, pathway_name: str) -> list[str]:
        rows = self.con.execute(
            "SELECT DISTINCT gene_symbol FROM pathways WHERE pathway_name = ?",
            [pathway_name],
        ).fetchall()
        return [r[0] for r in rows]

    def all_pathway_gene_counts(self) -> dict[str, int]:
        rows = self.con.execute(
            "SELECT pathway_name, COUNT(DISTINCT gene_symbol) "
            "FROM pathways GROUP BY pathway_name",
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def all_go_term_gene_counts(self) -> dict[str, int]:
        rows = self.con.execute(
            "SELECT go_id, COUNT(DISTINCT gene_symbol) "
            "FROM gene_go_terms GROUP BY go_id",
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def total_gene_count(self) -> int:
        row = self.con.execute(
            "SELECT COUNT(DISTINCT gene_symbol) FROM genes",
        ).fetchone()
        return row[0] if row else 0

    def background_genes(self) -> set[str]:
        """The enrichment background universe: every distinct gene_symbol in
        the genes table.  Fisher's exact test is only valid when the responsive
        set is a subset of this universe, so callers must intersect against it
        before building 2x2 tables (otherwise out-of-universe genes inflate the
        'not in pathway' margin and drive the d-cell negative)."""
        rows = self.con.execute(
            "SELECT DISTINCT gene_symbol FROM genes",
        ).fetchall()
        return {r[0] for r in rows}

    def total_pathway_gene_count(self) -> int:
        row = self.con.execute(
            "SELECT COUNT(DISTINCT gene_symbol) FROM pathways",
        ).fetchone()
        return row[0] if row else 0

    def total_go_gene_count(self) -> int:
        row = self.con.execute(
            "SELECT COUNT(DISTINCT gene_symbol) FROM gene_go_terms",
        ).fetchone()
        return row[0] if row else 0

    def gene_evidence(self, gene: str) -> dict:
        row = self.con.execute(
            "SELECT evidence, mention_count FROM genes WHERE gene_symbol = ?",
            [gene],
        ).fetchone()
        if row:
            return {"evidence": row[0], "mention_count": row[1]}
        return {"evidence": None, "mention_count": 0}

    def go_term_name(self, go_id: str) -> str:
        row = self.con.execute(
            "SELECT go_term FROM go_terms WHERE go_id = ?",
            [go_id],
        ).fetchone()
        return row[0] if row else go_id

    def all_organ_counts(self) -> dict[str, int]:
        """Count how many genes are annotated to each organ in the KB."""
        rows = self.con.execute(
            "SELECT organ, COUNT(*) FROM ("
            "  SELECT UNNEST(organs) AS organ FROM genes "
            "  WHERE organs IS NOT NULL"
            ") GROUP BY organ",
        ).fetchall()
        return {r[0]: r[1] for r in rows}
