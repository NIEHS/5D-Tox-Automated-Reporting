"""
sample_sheet — which animal each genomic sample came from.

A genomic experiment's treatments are samples ("Plate5-116", a CEL file name),
not animals.  The study's sample sheet maps them to the animals of the study
workbooks (study_structure), so each sample's dose and sex can be checked
against the animal's, and its tissue gives the experiment's organ.  CEBS
publishes it with the genomic data:

  * NIEHS-07 … 10: ``per_sample_summary … .xlsx`` — "Sample name" → "Animal ID",
    "Tissue";
  * NIEHS-02 … 06: the microarray sample list — "GeneChip File Name" →
    "Animal #".

A sheet is recognised by its column names (a sample column and an animal
column in one of its first rows), whatever the file is called.

Without a sheet, a sample resolves only when its name ends in a number that is
one of the study's animals ("Plate5-116" → 116).  Anything else stays
unresolved: it is reported, never guessed.
"""

from __future__ import annotations

import os
import re

_SAMPLE_COLS = ("sample name", "genechip file name", "fastq file id")
_ANIMAL_COLS = ("animal id", "animal #", "animal number")
_TISSUE_COLS = ("tissue", "tissue or cell-type")

# How far down a sheet its header may sit (the microarray list has two header rows).
_HEADER_ROWS = 3


def _norm(v) -> str:
    return re.sub(r"\s+", " ", str(v)).strip().lower() if v is not None else ""


def _animal_text(v) -> str:
    """101, 101.0, "101" → "101"."""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip() if v is not None else ""


def sample_key(name: str) -> str:
    """A sample name as the sheet and the project may each write it: without
    a ".CEL"/".fastq.gz" ending, lower case."""
    n = str(name).strip()
    n = re.sub(r"\.(cel|fastq(\.gz)?|fq(\.gz)?)$", "", n, flags=re.I)
    return n.lower()


def _columns(header: list) -> tuple[int | None, int | None, int | None]:
    names = [_norm(h) for h in header]

    def find(options):
        return next((i for i, n in enumerate(names) if n in options), None)

    return find(_SAMPLE_COLS), find(_ANIMAL_COLS), find(_TISSUE_COLS)


def read_sample_sheet(path: str) -> dict[str, dict]:
    """{sample key: {"sample", "animal_id", "tissue"}} from a sample sheet; {}
    when the file has no sheet with a sample and an animal column."""
    import openpyxl

    try:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    except Exception:
        return {}
    out: dict[str, dict] = {}
    try:
        for ws in wb.worksheets:
            rows = ws.iter_rows(values_only=True)
            head: list = []
            sample_i = animal_i = tissue_i = None
            for _ in range(_HEADER_ROWS):
                row = next(rows, None)
                if row is None:
                    break
                sample_i, animal_i, tissue_i = _columns(list(row))
                if sample_i is not None and animal_i is not None:
                    head = list(row)
                    break
            if not head:
                continue
            for row in rows:
                if row is None or max(sample_i, animal_i) >= len(row):
                    continue
                sample, animal = row[sample_i], _animal_text(row[animal_i])
                if sample is None or not str(sample).strip() or not animal:
                    continue
                tissue = row[tissue_i] if tissue_i is not None and tissue_i < len(row) else None
                out[sample_key(sample)] = {
                    "sample": str(sample).strip(),
                    "animal_id": animal,
                    "tissue": str(tissue).strip() if tissue else None,
                }
    finally:
        wb.close()
    return out


def is_sample_sheet(path: str) -> bool:
    return bool(read_sample_sheet(path))


_TRAILING_NUMBER = re.compile(r"(?:^|[^0-9A-Za-z])([0-9]+)$")


def resolve_sample(name: str, samples: dict[str, dict], animals) -> dict | None:
    """{"animal_id", "tissue"} for a genomic sample, or None.

    The sample sheet first (``samples``: read_sample_sheet's map); else a name
    ending in a number that is one of ``animals`` ("Plate5-116" → 116)."""
    hit = samples.get(sample_key(name)) if samples else None
    if hit:
        return {"animal_id": hit["animal_id"], "tissue": hit.get("tissue")}
    m = _TRAILING_NUMBER.search(str(name).strip())
    if m and m.group(1) in animals:
        return {"animal_id": m.group(1), "tissue": None}
    return None


def sheet_name(path: str) -> str:
    return os.path.basename(path)
