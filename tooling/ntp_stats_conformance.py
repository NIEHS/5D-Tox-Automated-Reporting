#!/usr/bin/env python3
"""tooling/ntp_stats_conformance.py — check our NTP statistics against the
significance markers NIEHS published, cell by cell.

For each CEBS package, the NTP summary tables (PA06 organ weights, PA41
clinical chemistry, PA43 hematology) print, per endpoint and dose group,
"mean ± SEM (N)" followed by * / ** — the control column's marker is the trend
test, a dose column's marker its pairwise test.  The same package carries the
individual-animal data.  This tool:

  1. converts the Individual Animal workbooks to per-sex truth CSVs
     (tooling.cebs_to_pool), per study number;
  2. parses the published tables (pypdf layout text);
  3. matches each published row to a data endpoint by VALUE — every dose
     group's N equal and mean equal at the published precision — so a row the
     NTP staff edited (an excluded outlier) is reported as unmatched instead of
     silently compared on different data;
  4. runs bmdx_pipe.ntp_stats on the matched data (Williams/Dunnett for organ
     weights, Shirley/Dunn for clinical pathology) and compares markers;
  5. formats our mean ± SE at the precision the table builders print
     (tables.display_precision: the endpoint's convention, "<organ> Absolute"
     for organ weights, else the recorded precision) and compares it with the
     published cell ("published_cell" / "ours_cell").

Usage:
    python -m tooling.ntp_stats_conformance assets/cebs/NIEHS-13 assets/cebs/NIEHS-10 ...
        [--json out.json] [--show-diffs]
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import tempfile
from collections import defaultdict
from pathlib import Path

import pypdf

from bmdx_pipe import ntp_stats

from tables.display_precision import recorded_decimals, row_decimals
from tables.table_builder_common import format_mean_se, mean_se
from tooling.cebs_to_pool import convert_workbook

# Published table → (data truth-CSV stem, test family)
_TABLE_KIND = {
    "PA06": ("organ_weights", ntp_stats.PARAMETRIC),
    "PA41": ("clin_chem", ntp_stats.NONPARAMETRIC),
    "PA43": ("hematology", ntp_stats.NONPARAMETRIC),
}

# "mean ± SE (N) marker"; a group of one animal prints "mean (N)" with no SE.
_CELL = re.compile(
    r"(-?\d[\d,]*\.?\d*)\s*(?:±\s*(\d[\d,]*\.?\d*)\s*)?\(\s*(\d+)\s*\)\s*(\*{0,2})")
# "Males: Core Animals" (NIEHS-07 on), "Males: Original Animals" (NIEHS-02/03),
# or a bare "Males" (NIEHS-04 … 06: the whole study is one cohort).
_SEX = re.compile(r"^\s*(Males?|Females?)\s*(?::\s*(.+?))?\s*$")
# The cohort the summaries count, by the words NIEHS used for it.
_COUNTED_COHORT = ("core", "original")
_NUM = re.compile(r"-?\d+(?:\.\d+)?")


# ---------------------------------------------------------------------------
# Published tables
# ---------------------------------------------------------------------------

def parse_pa_table(pdf_path: str) -> dict:
    """{study, kind, rows: [{sex, selection, label, phase_day, cells: {dose: (mean, se, n, marker)}}]}"""
    text = "\n".join(p.extract_text(extraction_mode="layout")
                     for p in pypdf.PdfReader(pdf_path).pages)
    lines = text.splitlines()
    study = kind = None
    for ln in lines[:40]:
        m = re.search(r"Study Number:\s*(\S+)", ln)
        if m and not study:
            study = m.group(1)
        m = re.search(r"\b(PA0?6|PA41|PA43)\b", ln)
        if m and not kind:
            kind = m.group(1).replace("PA6", "PA06")
    rows: dict[tuple, dict] = {}
    sex = selection = None
    doses: list[float] = []
    group = None
    expect_doses = False
    for ln in lines:
        if not ln.strip():
            continue
        m = _SEX.match(ln)
        if m:
            sex = "Male" if m.group(1).lower().startswith("male") else "Female"
            selection = (m.group(2) or "").strip() or None
            group = None
            continue
        if "Treatment Groups" in ln:
            expect_doses = True
            continue
        if expect_doses:
            nums = [float(x) for x in _NUM.findall(ln)]
            if nums:
                doses = nums
                expect_doses = False
            continue
        cells = list(_CELL.finditer(ln))
        if not cells:
            stripped = ln.strip()
            # An organ group header ("Heart", "R. Kidney") — no digits, short.
            if sex and not re.search(r"\d", stripped) and len(stripped) < 40 \
                    and "Percent" not in stripped and ":" not in stripped:
                group = stripped
            continue
        if not sex or len(cells) != len(doses):
            continue
        label = ln[:cells[0].start()].strip()
        phase = None
        pm = re.search(r"\bSD\s*(\d+)\s*$", label)
        if pm:
            phase = f"SD{pm.group(1)}"
            label = label[:pm.start()].strip()
        label = re.sub(r"\s*\([^)]*\)\s*$", "", label).strip()
        if label.lower() in ("absolute", "relative") and group:
            label = f"{group} {label}"
        key = (sex, selection, label, phase)
        row = rows.setdefault(key, {"sex": sex, "selection": selection, "label": label,
                                    "phase_day": phase, "cells": {}})
        for d, c in zip(doses, cells):
            row["cells"][d] = (c.group(1).replace(",", ""), (c.group(2) or "").replace(",", ""),
                               int(c.group(3)), c.group(4))
    return {"study": study, "kind": kind, "rows": list(rows.values())}


# ---------------------------------------------------------------------------
# Individual-animal data
# ---------------------------------------------------------------------------

def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def load_endpoints(csv_path: str, selection: str | None, phase_day: str | None) -> dict[str, dict[float, list[float]]]:
    """{endpoint: {dose: [values]}} for one truth CSV, one selection (and phase
    day, when given).  Organ-weight CSVs gain '<organ> Relative' endpoints
    (mg organ / g terminal body weight, per animal)."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        rd = list(csv.DictReader(f))
    if not rd:
        return {}
    cols = list(rd[0].keys())
    meta_end = max(cols.index(c) for c in cols
                   if c in ("Observation Day", "Removal Day", "Selection"))
    endpoints = [c for c in cols[meta_end + 1:] if c not in ("Terminal Flag",)]
    out: dict[str, dict[float, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in rd:
        # A CSV without a Selection column holds one cohort (NIEHS-02 … 06);
        # an unlabelled published table counts the whole study.
        if selection and "Selection" in r and (r["Selection"] or "").strip().lower() != selection.lower():
            continue
        day = (r.get("Observation Day") or "").replace(" ", "")
        if phase_day and day and day != phase_day:
            continue
        dose = _num(r.get("Concentration") or r.get("Dose"))
        if dose is None:
            continue
        for ep in endpoints:
            v = _num(r.get(ep))
            if v is not None:
                out[ep][dose].append(v)
        tbw = _num(r.get("Terminal Body Weight"))
        if tbw:
            for ep in endpoints:
                v = _num(r.get(ep))
                if v is not None and ep != "Terminal Body Weight":
                    out[f"{ep} Relative"][dose].append(v / tbw * 1000)
    return out


def recorded_precision(csv_path: str) -> dict[str, int | None]:
    """{endpoint column: decimals its values are recorded with} for a truth CSV."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        rd = list(csv.DictReader(f))
    return {c: recorded_decimals(r.get(c) for r in rd) for c in (rd[0].keys() if rd else [])}


def precision_label(kind: str, endpoint: str) -> str:
    """The label the table builder hands display_precision.row_decimals."""
    if kind == "PA06" and endpoint != "Terminal Body Weight" and not endpoint.endswith(" Relative"):
        return f"{endpoint} Absolute"
    return endpoint


def _tokens(label: str) -> set[str]:
    t = label.lower().replace("r.", "right ").replace("l.", "left ")
    return {w.rstrip("s") for w in re.findall(r"[a-z0-9]+", t)}


def _name_score(published: str, endpoint: str) -> int:
    """Shared-word count, to break ties between endpoints with identical rounded
    values (left and right kidney of a mouse)."""
    return len(_tokens(published) & _tokens(endpoint))


def _decimals(s: str) -> int:
    return len(s.split(".")[1]) if "." in s else 0


def _matches(pub_cells: dict, data: dict[float, list[float]]) -> bool:
    for d, (mean_s, _se, n, _mk) in pub_cells.items():
        vals = data.get(d, [])
        if len(vals) != n:
            return False
        dp = _decimals(mean_s)
        if abs(round(sum(vals) / n, dp) - float(mean_s)) > 1.01 * 10 ** -dp:
            return False
    return True


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def convert_package(package: str, work: str) -> dict[str, str]:
    """{study number: directory of truth CSVs}."""
    dirs = {}
    for xlsx in sorted(glob.glob(os.path.join(package, "*Individual_Animal_*.xlsx"))):
        prefix = os.path.basename(xlsx).split("_Individual_Animal_")[0]
        out = os.path.join(work, prefix)
        os.makedirs(out, exist_ok=True)
        try:
            convert_workbook(xlsx, out)
        except Exception:
            continue
        dirs[prefix] = out
    return dirs


def compare_package(package: str, work: str) -> list[dict]:
    dirs = convert_package(package, work)
    cells: list[dict] = []
    pdfs = [p for p in glob.glob(os.path.join(package, "*.pdf"))
            if re.search(r"PA0?6|PA41|PA43", os.path.basename(p))]
    for pdf in sorted(pdfs):
        try:
            table = parse_pa_table(pdf)
        except Exception as e:
            print(f"  ! {os.path.basename(pdf)}: {e}")
            continue
        if table["kind"] not in _TABLE_KIND or not table["study"]:
            continue
        stem, family = _TABLE_KIND[table["kind"]]
        study_dir = dirs.get(table["study"]) or dirs.get(table["study"].replace("-", ""))
        if not study_dir:
            continue
        for row in table["rows"]:
            csv_path = os.path.join(study_dir, f"{stem}_truth_{row['sex'].lower()}.csv")
            base = {"package": os.path.basename(package), "study": table["study"],
                    "table": table["kind"], "sex": row["sex"], "label": row["label"]}
            sel = row["selection"]
            if not os.path.exists(csv_path) or (sel and not any(w in sel.lower() for w in _COUNTED_COHORT)):
                continue
            endpoints = load_endpoints(csv_path, sel.split(":")[0].strip() if sel and ":" in sel else sel,
                                       row["phase_day"])
            hits = [ep for ep, data in endpoints.items() if _matches(row["cells"], data)]
            if not hits:
                cells.append({**base, "status": "unmatched"})
                continue
            hits.sort(key=lambda ep: -_name_score(row["label"], ep))
            data = endpoints[hits[0]]
            doses = sorted(row["cells"])
            res = ntp_stats.ntp_pairwise({d: data.get(d, []) for d in doses}, family)
            dec = row_decimals(precision_label(table["kind"], hits[0]),
                               recorded_precision(csv_path).get(hits[0]))
            for d in doses:
                pub = row["cells"][d][3]
                ours = (ntp_stats.sig_marker(res.jonckheere_p) if d == doses[0]
                        else ntp_stats.sig_marker(res.pairwise_p.get(d, 1.0)))
                mean_s, se_s, n, _ = row["cells"][d]
                pub_cell = ours_cell = None
                if se_s and n >= 2 and dec is not None:  # one animal prints no SE
                    pub_cell = f"{mean_s} ± {se_s}"
                    ours_cell = format_mean_se(*mean_se(data[d]), dec).replace("\u00a0", " ")
                cells.append({**base, "status": "compared", "endpoint": hits[0],
                              "dose": d, "column": "trend" if d == doses[0] else "pairwise",
                              "method": res.method, "jonckheere_p": res.jonckheere_p,
                              "p": None if d == doses[0] else res.pairwise_p.get(d),
                              "published": pub, "ours": ours,
                              "published_cell": pub_cell, "ours_cell": ours_cell})
    return cells


def summarize(cells: list[dict]) -> str:
    out = []
    rows = defaultdict(lambda: [0, 0])
    unmatched = defaultdict(int)
    for c in cells:
        if c["status"] == "unmatched":
            unmatched[(c["package"], c["table"])] += 1
            continue
        k = (c["package"], c["table"], c["column"])
        rows[k][0] += c["published"] == c["ours"]
        rows[k][1] += 1
    tot = [0, 0]
    for k in sorted(rows):
        a, n = rows[k]
        tot[0] += a
        tot[1] += n
        out.append(f"{k[0]:9} {k[1]} {k[2]:8} {a:4}/{n:<4} agree"
                   + (f"   ({unmatched[(k[0], k[1])]} rows unmatched)" if k[2] == "trend" else ""))
    out.append(f"TOTAL {tot[0]}/{tot[1]} cells agree ({100 * tot[0] / max(tot[1], 1):.1f}%)")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("packages", nargs="+")
    ap.add_argument("--json")
    ap.add_argument("--show-diffs", action="store_true")
    a = ap.parse_args()
    cells = []
    with tempfile.TemporaryDirectory() as work:
        for pkg in a.packages:
            cells += compare_package(pkg, os.path.join(work, Path(pkg).name))
    print(summarize(cells))
    if a.show_diffs:
        for c in cells:
            if c["status"] == "compared" and c["published"] != c["ours"]:
                print(f"  {c['package']} {c['table']} {c['sex']:6} {c['label'][:32]:32} {c['dose']:>8g} "
                      f"pub={c['published'] or '-':2} ours={c['ours'] or '-':2} {c['method']:8} "
                      f"J={c['jonckheere_p']:.4f} p={c['p'] if c['p'] is None else round(c['p'], 4)}")
    if a.json:
        Path(a.json).write_text(json.dumps(cells, indent=1, default=str))


if __name__ == "__main__":
    main()
