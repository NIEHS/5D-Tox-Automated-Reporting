"""
pipeline/bmds27/oracle.py — NTP's recorded BMDS 2.7 runs, as a test oracle.

Every BMDS-era CEBS deposit (NIEHS-02 … NIEHS-10) carries the package's own
output: Parameter workbooks with one row per model per high-dose-drop round —
the dfile sent to the executable, the output file it wrote, the parsed BMD,
BMDL, AIC, the rule bin and notes, and the recommendation. Those rows are
what NTP's run produced, so they are the oracle for this engine:

  - replay: the engine run on a recorded dataset, with the executable step
    answered from the recording (runner.ReplayExecutor), must write the same
    dfiles and reach the same bins, recommendations and BMDs;
  - Wine: the real executables, given the recorded dfiles, must write
    outputs that parse to the recorded values.

`read_workbooks` turns a report's workbooks into the compact record that
`tooling/bmds27_oracle.py` stores as tests/fixtures/reference/<R>/bmds27_runs.json.xz.
"""

from __future__ import annotations

import json
import lzma
import math
from pathlib import Path

FIXTURE_NAME = "bmds27_runs.json.xz"
_DATA_HEADER = "Dose NumAnimals Response Stdev"

# Per-model columns kept from the workbook (NTP's _df_ordered_dict names).
RUN_FIELDS = ("doses_dropped", "model_index", "model_name", "model_version", "has_output",
              "execution_halted", "BMD", "BMDL", "BMDU", "AIC", "pvalue1", "pvalue2",
              "pvalue3", "pvalue4", "residual_of_interest", "logic_bin", "logic_cautions",
              "logic_warnings", "logic_failures", "recommended", "recommended_variable",
              "dfile", "outfile", "stdout", "stderr")
# Per-dataset columns (the same on every row of a dataset).
DATASET_FIELDS = ("DEPOSITOR_STUDY_NUMBER", "ENDPOINT", "ENDPOINT_UNIT", "SEX", "table_id",
                  "STE", "MULT_COMP_SIGNIF", "NUM_DECIMAL_DIGIT", "DOSE_UNIT")


def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if hasattr(v, "item"):  # numpy scalar
        v = v.item()
    return v


def read_workbooks(paths: list[Path]) -> list[dict]:
    """The datasets recorded in a report's Parameter workbook(s), each with
    its model runs in recorded order."""
    import pandas as pd

    datasets = []
    for path in paths:
        for sheet, df in pd.read_excel(path, sheet_name=None, keep_default_na=False, na_values=[""]).items():
            if "dfile" not in df.columns:
                continue
            for idx, g in df.groupby("dataset_index", sort=True):
                first = g.iloc[0]
                datasets.append({
                    "workbook": Path(path).name,
                    "sheet": sheet,
                    "dataset_index": int(idx),
                    **{k.lower(): _clean(first.get(k)) for k in DATASET_FIELDS if k in g.columns},
                    "runs": [{k: _clean(r.get(k)) for k in RUN_FIELDS}
                             for _, r in g.sort_values(["doses_dropped", "model_index"]).iterrows()],
                })
    return datasets


def write_fixture(datasets: list[dict], dest: Path, *, report: str, sources: list[str]) -> None:
    blob = json.dumps({"report": report, "sources": sources, "datasets": datasets},
                      ensure_ascii=False, separators=(",", ":"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(lzma.compress(blob.encode(), preset=9))


def load_fixture(path: Path) -> dict:
    return json.loads(lzma.decompress(Path(path).read_bytes()))


def dataset_rows(dfile: str) -> list[tuple[float, int, float, float]]:
    """(dose, n, mean, sd) rows of a continuous dfile's data block."""
    lines = dfile.split("\n")
    i = lines.index(_DATA_HEADER)
    rows = [ln.split() for ln in lines[i + 1:] if ln.strip()]
    return [(float(r[0]), int(r[1]), float(r[2]), float(r[3])) for r in rows]


def recorded_runs(dataset: dict) -> dict[str, dict]:
    """dfile → recorded run, for runner.ReplayExecutor."""
    return {r["dfile"]: r for r in dataset["runs"] if r.get("dfile")}
