"""
Author notebooks/workflow_walkthrough.ipynb programmatically.

The notebook is the headless report workflow one step per cell: the same step
functions `python -m tooling.generate_report` runs (which call the UI-agnostic
core, `workflow.steps`, ADR-0014), so the notebook, the command line and the
browser can never disagree about what a step does.  Each cell that changes the
session ends by re-printing the DERIVED workflow state (phase + legal actions):
the phase is a function of the files on disk, never stored.

Every step is preceded by a long explanation of its purpose and of how it is
implemented (module:function, the order things happen in, what it reads and
writes, how it fails).  Keep those explanations true when the code changes.

It builds a published study (NIEHS-10 by default) into a scratch session,
starting from the CEBS data package (tooling.cebs_to_pool) and the facts the
published report states, renders the deliverables and compares them with the
published book.

The cells are in _nb_cells_data.py (introduction + data preparation) and
_nb_cells_report.py (Process → compare).  Edit those, not the .ipynb, then
regenerate:
    .venv/bin/python notebooks/_build_workflow_notebook.py
Run it headless (writes the outputs into the notebook):
    .venv/bin/python -m nbconvert --to notebook --execute --inplace \\
        --ExecutePreprocessor.timeout=3600 notebooks/workflow_walkthrough.ipynb
"""

from __future__ import annotations

from pathlib import Path

import nbformat as nbf
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

nb = new_notebook()
cells: list = []


def md(text: str) -> None:
    cells.append(new_markdown_cell(text.strip("\n")))


def code(src: str) -> None:
    cells.append(new_code_cell(src.strip("\n")))


# The cells live in two modules beside this one, by arc (data preparation, then
# the report); this script runs from notebooks/, so they import by name.
import _nb_cells_data  # noqa: E402
import _nb_cells_report  # noqa: E402

for part in (_nb_cells_data, _nb_cells_report):
    for kind, text in part.CELLS:
        (md if kind == "md" else code)(text)

# ---------------------------------------------------------------------------
nb["cells"] = cells
nb["metadata"]["kernelspec"] = {
    "display_name": "Python 3 (rlm-bmdx .venv)",
    "language": "python",
    "name": "python3",
}
nb["metadata"]["language_info"] = {"name": "python"}
out = Path(__file__).parent / "workflow_walkthrough.ipynb"
with open(out, "w", encoding="utf-8") as fh:
    nbf.write(nb, fh)
print(f"wrote {out}  ({len(cells)} cells)")
