#!/usr/bin/env python3
"""tooling/slim_genomics_extract.py — the part of a published BMDExpress genomic
project the GO and gene tables read, small enough to commit as a test fixture.

A 2025-method genomic project (NIEHS-12/13) is ~10 MB as .bm2 and ~55 MB as
JSON, and reading the .bm2 needs Java.  The report's genomics tables
(pipeline.processing_helpers._extract_genomics) read only:

  * the ExportGenomics result (bmdx_pipe.export_genomics — Java; the session's
    genomics.sidecar.json): per experiment the GO BP categories (gene counts,
    BMD/BMDL/BMDU statistics, member genes) and the per-probe gene fits;
  * from the project itself (genomics.bmdexpress_categories): the experiments'
    names and chips, BMDExpress's own GO_BP and GENE category analyses (the
    adverse-direction counts and the gene-level Top-10), and each BMD
    analysis's recorded notes (the BMR label).

This keeps those, trimmed to the fields that code reads and to the BMD
statistics the tables rank by, and applies the integration step the pipeline
applies: organ and sex per experiment from the study's own files
(tooling.cebs_to_pool.genomic_metadata — sample IDs matched to the per-tissue
expression files; sex from the workbook's Key title).  Every value is copied,
none recomputed, and the inputs' checksums are recorded.

Usage (the two exports need Java once; see assets/cebs/bm2json.sh):
    python -m tooling.slim_genomics_extract \\
        --package assets/cebs/NIEHS-13 --prefix 108020004 \\
        --project assets/cebs/NIEHS-13/_bm2json/108020004_4D_Genomic_Rats.json \\
        --export /tmp/n13_genomics_export.json \\
        --out tests/fixtures/reference/NIEHS-13/108020004_4D_Genomic_Rats.slim.json
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os

import openpyxl

from genomics.bmdexpress_categories import _owning_experiment
from tooling.cebs_to_pool import genomic_metadata, key_sheet_sex

# The BMD statistics the GO tables rank by (published: 5th percentile; median).
STATS = ("fifth_pct", "median")
_GO_FIELDS = ("go_id", "go_term", "go_level", "n_genes", "n_passed", "gene_symbols",
              "direction", "fishers_two_tail")
_GENE_ITEM_FIELDS = ("genesThatPassedAllFilters", "bmdMedian", "bmdlMedian", "bmduMedian",
                     "genesAdverseUpCount", "genesAdverseDownCount", "probeIds",
                     "geneSymbolsPrivate", "genesIds")
_GO_ITEM_FIELDS = ("genesAdverseUpCount", "genesAdverseDownCount")


def _sha256(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _ident(item: dict) -> dict | None:
    ident = item.get("categoryIdentifier")
    return {"id": ident.get("id"), "title": ident.get("title")} if isinstance(ident, dict) else None


def slim(project: dict, export: dict, metadata: dict) -> dict:
    exp_names = [e.get("name", "") for e in project.get("doseResponseExperiments", [])]

    experiments = []
    for e in project.get("doseResponseExperiments", []):
        meta = metadata.get(e.get("name"), {})
        chip = e.get("chip")
        experiments.append({
            "name": e.get("name"),
            # Kept as serialized: an inline object the first time, a bare @ref id after.
            "chip": ({k: chip.get(k) for k in ("@ref", "name", "species", "provider")}
                     if isinstance(chip, dict) else chip),
            "experimentDescription": {k: meta.get(k) for k in
                                      ("dataType", "organ", "sex", "species", "platform", "provider")},
        })

    analyses = []
    for ca in project.get("categoryAnalysisResults", []):
        name = ca.get("name", "") if isinstance(ca, dict) else ""
        kind = "GENE" if "_GENE_" in name else "GO_BP" if "_GO_BP_" in name else None
        if not kind or _owning_experiment(name, exp_names) is None:
            continue
        fields = _GENE_ITEM_FIELDS if kind == "GENE" else _GO_ITEM_FIELDS
        analyses.append({"name": name, "categoryAnalsyisResults": [
            {"categoryIdentifier": _ident(r), **{k: r.get(k) for k in fields}}
            for r in ca.get("categoryAnalsyisResults") or [] if isinstance(r, dict)
        ]})

    bmd_results = [{"name": b.get("name"), "analysisInfo": {"notes": (b.get("analysisInfo") or {}).get("notes")}}
                   for b in project.get("bMDResult", []) if isinstance(b, dict)]

    sidecar = []
    for e in export.get("experiments", []):
        meta = metadata.get(e.get("name"), {})
        sidecar.append({
            "name": e.get("name"),
            # integration's reconciliation (bmdx_pipe.genomics_metadata) — the study's own organ/sex
            "organ": (meta.get("organ") or e.get("organ") or "").title(),
            "sex": (meta.get("sex") or e.get("sex") or "").title(),
            "total_probes": e.get("total_probes"),
            "genes": e.get("genes", []),
            "go_bp": [{**{k: g.get(k) for k in _GO_FIELDS},
                       **{f"{m}_stats": {s: (g.get(f"{m}_stats") or {}).get(s) for s in STATS}
                          for m in ("bmd", "bmdl", "bmdu")}}
                      for g in e.get("go_bp", [])],
        })

    return {
        "integrated": {"doseResponseExperiments": experiments,
                       "categoryAnalysisResults": analyses,
                       "bMDResult": bmd_results},
        "genomics_sidecar": {"experiments": sidecar},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--package", required=True, help="CEBS package dir (expression files, workbooks)")
    ap.add_argument("--prefix", default="", help="study-number prefix selecting one study")
    ap.add_argument("--project", required=True, help="the genomic .bm2 as JSON (ExportBm2)")
    ap.add_argument("--export", required=True, help="bmdx_pipe.export_genomics output for the same .bm2")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    workbook = sorted(glob.glob(os.path.join(a.package, f"{a.prefix}*Individual_Animal_*.xlsx")))[0]
    sex = key_sheet_sex(openpyxl.load_workbook(workbook))
    metadata = genomic_metadata(a.project, a.package, sex)
    with open(a.project) as f:
        project = json.load(f)
    with open(a.export) as f:
        export = json.load(f)

    out = slim(project, export, metadata)
    out = {"_provenance": {
        "tool": "tooling/slim_genomics_extract.py",
        "project_json": {"file": os.path.basename(a.project), "sha256": _sha256(a.project)},
        "export_genomics": {"file": os.path.basename(a.export), "sha256": _sha256(a.export)},
        "statistics_kept": list(STATS),
        "organ_sex_from": "tooling.cebs_to_pool.genomic_metadata (sample IDs ↔ expression files; "
                          f"sex '{sex}' from {os.path.basename(workbook)} Key title)",
    }, **out}
    with open(a.out, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(json.dumps({"out": a.out, "bytes": os.path.getsize(a.out),
                      "experiments": {e["name"]: e["organ"] for e in out["genomics_sidecar"]["experiments"]}}))


if __name__ == "__main__":
    main()
