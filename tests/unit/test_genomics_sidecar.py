"""
Unit tests for the genomics sidecar (ADR-0016 Phase D).

Integration persists the raw ExportGenomics JSON as `genomics.sidecar.json`, and
process-time extraction reads it INSTEAD of re-running Java on the raw .bm2
(fixing CLAUDE.md invariant #1). These pin:
  1. sidecar present → _load_genomics_export reads it, export_genomics NOT called;
  2. no sidecar, .bm2 present → falls back to export_genomics (Java path);
  3. neither → returns {} (no genomics);
  4. _extract_genomics produces the SAME Shape A whether the raw export came from
     the sidecar or the .bm2 (provenance change, not shape change);
  5. _hash_genomics folds in the sidecar signature so a re-extract invalidates.
"""

import asyncio
import json
from unittest.mock import patch

import pytest

from pipeline import processing_helpers as ph
from pipeline.processing_helpers import (
    _load_genomics_export,
    _extract_genomics,
    GENOMICS_SIDECAR_NAME,
)
from pipeline.cache_plumbing import _hash_genomics


DTXSID = "DTXSID_GENO"

# A minimal raw ExportGenomics result (what the sidecar / Java both return).
_RAW = {
    "experiments": [
        {
            "name": "liver_male", "organ": "Liver", "sex": "Male",
            "total_probes": 3,
            "genes": [
                {"probe_id": "p1", "gene_symbol": "EGR1", "bmd": 4.2, "bmdl": 2.1,
                 "bmdu": 6.0, "direction": "up", "r_squared": 0.9, "fold_change": 2.5},
            ],
            "go_bp": [
                {"go_id": "GO:1", "go_term": "cell division", "bmd_median": 5.0,
                 "bmdl_median": 3.0, "n_genes": 1, "n_passed": 1, "direction": "up",
                 "fishers_two_tail": 0.01, "gene_symbols": "EGR1"},
            ],
        }
    ]
}


def _write_sidecar(session_dir):
    d = session_dir / DTXSID
    d.mkdir(parents=True, exist_ok=True)
    (d / GENOMICS_SIDECAR_NAME).write_text(json.dumps(_RAW))
    return d


def _integrated_with_ge(filename="Gene Expression.bm2"):
    return {"_meta": {"source_files": {"gene_expression": {
        "filename": filename, "tier": "bm2"}}}}


@pytest.mark.integration
class TestLoadGenomicsExport:
    def test_sidecar_preferred_no_java(self, sessions_dir):
        _write_sidecar(sessions_dir)
        with patch("pipeline.processing_helpers.export_genomics") as mock_java:
            result = asyncio.run(_load_genomics_export(DTXSID, {}))
        assert result == _RAW
        mock_java.assert_not_called()  # sidecar read → Java never runs

    def test_falls_back_to_bm2_when_no_sidecar(self, sessions_dir):
        # session dir + the .bm2 present, but NO sidecar
        d = sessions_dir / DTXSID
        (d / "files").mkdir(parents=True, exist_ok=True)
        (d / "files" / "Gene Expression.bm2").write_bytes(b"fake bm2")
        with patch(
            "pipeline.processing_helpers.export_genomics", return_value=_RAW
        ) as mock_java:
            result = asyncio.run(
                _load_genomics_export(DTXSID, _integrated_with_ge())
            )
        assert result == _RAW
        mock_java.assert_called_once()  # legacy path used

    def test_no_sidecar_no_bm2_returns_empty(self, sessions_dir):
        (sessions_dir / DTXSID).mkdir(parents=True, exist_ok=True)
        with patch("pipeline.processing_helpers.export_genomics") as mock_java:
            result = asyncio.run(
                _load_genomics_export(DTXSID, _integrated_with_ge())
            )
        assert result == {}
        mock_java.assert_not_called()  # .bm2 missing → no Java, no crash

    def test_unreadable_sidecar_falls_back_to_bm2(self, sessions_dir):
        d = _write_sidecar(sessions_dir)
        (d / GENOMICS_SIDECAR_NAME).write_text("{ not json")
        (d / "files").mkdir(parents=True, exist_ok=True)
        (d / "files" / "Gene Expression.bm2").write_bytes(b"fake")
        with patch(
            "pipeline.processing_helpers.export_genomics", return_value=_RAW
        ) as mock_java:
            result = asyncio.run(
                _load_genomics_export(DTXSID, _integrated_with_ge())
            )
        assert result == _RAW
        mock_java.assert_called_once()


@pytest.mark.integration
class TestExtractGenomicsProvenanceEquivalence:
    """_extract_genomics must produce identical Shape A whether the raw export
    came from the sidecar or from the .bm2 — the whole point of the change."""

    def _run(self, dtxsid):
        return asyncio.run(_extract_genomics(
            dtxsid, {"_meta": {"source_files": {"gene_expression": {
                "filename": "Gene Expression.bm2", "tier": "bm2"}}},
                "_category_lookup": {}},
            bmd_stats=["median"], go_pct=0.0, go_min_genes=0,
            go_max_genes=10**9, go_min_bmd=0,
        ))

    def test_sidecar_and_bm2_yield_same_shape(self, sessions_dir):
        # (a) via sidecar
        _write_sidecar(sessions_dir)
        via_sidecar = self._run(DTXSID)
        assert "liver_male" in via_sidecar
        assert via_sidecar["liver_male"]["top_genes"][0]["gene_symbol"] == "EGR1"

        # (b) via .bm2 (remove sidecar, mock Java to return the SAME raw)
        (sessions_dir / DTXSID / GENOMICS_SIDECAR_NAME).unlink()
        (sessions_dir / DTXSID / "files").mkdir(parents=True, exist_ok=True)
        (sessions_dir / DTXSID / "files" / "Gene Expression.bm2").write_bytes(b"x")
        with patch("pipeline.processing_helpers.export_genomics", return_value=_RAW):
            via_bm2 = self._run(DTXSID)

        assert via_sidecar == via_bm2  # identical Shape A regardless of provenance


class TestHashGenomicsSidecarSig:
    def test_sidecar_sig_changes_key(self):
        base = _hash_genomics(["median"], "ge.bm2")           # no sidecar sig
        with_sig = _hash_genomics(["median"], "ge.bm2", "12345")
        assert with_sig != base                               # sig folded in
        # a different sidecar signature (re-extraction) invalidates
        assert _hash_genomics(["median"], "ge.bm2", "99999") != with_sig
        # same inputs → stable
        assert _hash_genomics(["median"], "ge.bm2", "12345") == with_sig
