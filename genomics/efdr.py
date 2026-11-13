"""
genomics/efdr.py — the empirical false discovery rate (eFDR) of the genomic
analysis, from its synthetic-null BMDExpress analysis.

The 2026 books (NIEHS-12, 13 Appendix D.2) generate synthetic null data from
each tissue's control animals (SaNDGen), distribute it into 20 experiments
that mirror the study's groups, run each through BMDExpress with the study's
parameters, and report the share of genes and of GO biological processes that
come out "active" — the eFDR, per species and tissue, its mean and range over
the experiments (Table D-1).  The analyses are deposited with the book, one
.bm2 per species and tissue ("Rat Heart DCB Synthetic Null Analysis.bm2" in
108020004_Rat_DCB_eFDR_Synthetic_Null_Analysis.zip).

What is counted, per null experiment:

  gene eFDR   the genes that pass all of the gene-level analysis' filters
              (its GENE category analysis: results with a passed gene), as a
              percentage of the genes analysed.  That universe is not exported
              as a number; it is exact from any one-gene category's Fisher
              right tail, K/U (K the passed genes, U the universe).
  GO eFDR     the GO biological processes active by the report's own gene set
              criteria (the method profile's genomics.go_display: at least
              ``min_bmd`` genes with a BMD, ``min_genes``–``max_genes`` genes in
              the set, ``pct`` % coverage), as a percentage of the possible
              processes.  That universe is not in the export at all, so an
              experiment with active processes has no percentage
              (``go_pct`` None, its count kept in ``go_active``).

record_efdr writes the per-tissue summaries as the session sidecar efdr.json;
the Results table and text are rendering.genomics_appendix's.  Reading a .bm2
is Java deserialization (bmdx_pipe.java_bridge), as for the study's own.
"""

from __future__ import annotations

import json
import re
import statistics
import subprocess
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

EFDR_FILE = "efdr.json"
# The deposited synthetic-null analyses: "<study>_<Species>_<abbr>_eFDR_Synthetic_Null_Analysis.zip".
ZIP_PATTERN = "*eFDR_Synthetic_Null_Analysis*.zip"
_NAME = re.compile(r"^(?P<species>Rat|Mouse|Mice|Rats)\s*(?P<tissue>[A-Z][a-z]+)")
_SPECIES = {"rat": "rat", "rats": "rat", "mouse": "mouse", "mice": "mouse"}


def _java(cls: str, *args: str) -> None:
    from bmdx_pipe.java_bridge import JAVA_HELPER_DIR, build_classpath
    subprocess.run(["java", "-cp", f"{build_classpath()}:{JAVA_HELPER_DIR}", cls, *args],
                   check=True, capture_output=True)


def _gene_universe(results: list[dict], passed: int) -> float | None:
    """The genes analysed, from a one-gene category's Fisher right tail (K/U)."""
    for r in results:
        p = r.get("fishers_right")
        if r.get("genes_total") == 1 and r.get("genes_passed") == 1 and p:
            return passed / p
    return None


def _go_active(r: dict, go: dict) -> bool:
    total, passed = r.get("genes_total") or 0, r.get("genes_passed") or 0
    return (passed >= go.get("min_bmd", 3) and go.get("min_genes", 0) <= total
            <= go.get("max_genes", 10 ** 9) and total and passed / total * 100 >= go.get("pct", 0))


def null_analysis(bm2: Path, go_display: dict, workdir: Path) -> dict:
    """One species-tissue's synthetic-null analysis (module docstring)."""
    m = _NAME.match(bm2.stem)
    if not m:
        raise ValueError(f"{bm2.name}: not a '<Species> <Tissue> … Synthetic Null Analysis' file")
    cats, project = workdir / "categories.json", workdir / "project.json"
    _java("ExportCategories", str(bm2), str(cats))
    _java("ExportBm2", str(bm2), str(project), "NONE")
    analyses = json.loads(cats.read_text(encoding="utf-8"))["analyses"]
    experiments = json.loads(project.read_text(encoding="utf-8")).get("doseResponseExperiments") or []
    groups = Counter(t.get("dose") for t in (experiments[0].get("treatments") or [])) \
        if experiments else Counter()

    def experiment(a):
        return a["name"].split("_curvefitprefilter")[0].split("_BMD")[0]

    genes, go_active = {}, {}
    for a in analyses:
        results = a.get("results") or []
        if a.get("category_type") == "gene":
            passed = sum(1 for r in results if (r.get("genes_passed") or 0) > 0)
            universe = _gene_universe(results, passed) if passed else None
            genes[experiment(a)] = passed / universe * 100 if universe else 0.0
        elif a.get("category_type") == "go_bp":
            go_active[experiment(a)] = sum(1 for r in results if _go_active(r, go_display))
    names = sorted(set(genes) | set(go_active), key=lambda n: [int(x) if x.isdigit() else x
                                                              for x in re.split(r"(\d+)", n)])
    return {
        "species": _SPECIES[m["species"].lower()], "tissue": m["tissue"],
        "source": bm2.name, "experiments": len(names),
        "groups": {f"{d:g}": n for d, n in sorted(groups.items())},
        "gene_pct": [genes.get(n, 0.0) for n in names],
        "go_active": [go_active.get(n, 0) for n in names],
        "go_pct": [0.0 if not go_active.get(n) else None for n in names],
    }


def summarize(values: list) -> dict | None:
    """{mean, min, max} of the percentages; None when any is unknown."""
    if not values or any(v is None for v in values):
        return None
    return {"mean": statistics.fmean(values), "min": min(values), "max": max(values)}


def efdr_from_zips(zips: list[Path], go_display: dict) -> dict:
    """{"tissues": [one per species-tissue, species then tissue order]}."""
    tissues = []
    for z in zips:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            with zipfile.ZipFile(z) as zf:
                members = [n for n in zf.namelist() if n.lower().endswith(".bm2")
                           and "/" not in n.strip("/") and ".." not in n]
                for name in members:
                    zf.extract(name, tmp / "in")
            for name in members:
                work = tmp / "work"
                work.mkdir(exist_ok=True)
                found = null_analysis(tmp / "in" / name, go_display, work)
                found["archive"] = Path(z).name
                tissues.append(found)
    tissues.sort(key=lambda t: (t["species"], t["tissue"]))
    return {"tissues": tissues, "go_display": go_display}


def record_efdr(dtxsid: str, zips: list[Path], go_display: dict | None = None) -> dict:
    """Compute the study's eFDR from its synthetic-null analyses and save it as
    the session's efdr.json.  ``go_display`` defaults to the session's method
    profile's."""
    from pipeline.session_store import session_path
    if go_display is None:
        from pipeline.method_profile import session_method
        go_display = session_method(dtxsid).get("genomics.go_display")
    out = efdr_from_zips([Path(z) for z in zips], dict(go_display))
    (session_path(dtxsid) / EFDR_FILE).write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def load_efdr(dtxsid: str | None) -> dict | None:
    if not dtxsid:
        return None
    from pipeline.session_store import session_path
    try:
        path = session_path(dtxsid) / EFDR_FILE
    except ValueError:
        return None
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Record a study's eFDR from its synthetic-null "
                                             "analyses (efdr.json).")
    ap.add_argument("dtxsid")
    ap.add_argument("zips", nargs="+", type=Path,
                    help="the deposited *_eFDR_Synthetic_Null_Analysis.zip files")
    a = ap.parse_args(argv)
    out = record_efdr(a.dtxsid, a.zips)
    for t in out["tissues"]:
        g = summarize(t["gene_pct"])
        print(f"{t['species']:6s} {t['tissue']:8s} n={t['experiments']} gene mean "
              f"{g['mean']:.3f} range {g['min']:.3f}-{g['max']:.3f}  GO active {sum(t['go_active'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
