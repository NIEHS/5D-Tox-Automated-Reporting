"""genomics/pca_figure.py — Appendix C.1 principal component analysis figure.

NIEHS Report 10's Appendix C shows, per tissue × sex, a PCA of the normalized
expression data "employed in dose response modeling": each animal a dot,
coloured by dose group, in three panels (PC1×PC2, PC1×PC3, PC2×PC3).

The recipe reproduces the published figures exactly (project_appendix_c_pca):
columns mean-centred, no scaling, SVD, and scikit-learn's sign convention (the
largest-magnitude score of each component positive).  The input is the
integrated project's gene-expression experiments — the matrix BMDExpress
modeled — so nothing is read around the integrated dataset.

One figure, one row of three panels per experiment (liver, kidney, then the
other tissues; male before female), so any number of tissues fits the single
template node.
"""

from __future__ import annotations

import base64
import io
import math

import numpy as np

_ORGAN_RANK = {"liver": 0, "kidney": 1}
_SEX_RANK = {"male": 0, "female": 1}
_PAIRS = ((0, 1), (0, 2), (1, 2))

CAPTION = "Principal Component Analysis of the Normalized Transcriptomic Data"


def _experiments(integrated: dict) -> list[dict]:
    out = []
    for exp in integrated.get("doseResponseExperiments") or []:
        desc = exp.get("experimentDescription") or {}
        if (desc.get("dataType") or "").lower() != "gene_expression":
            continue
        out.append(exp)
    out.sort(key=lambda e: (
        _ORGAN_RANK.get(str((e.get("experimentDescription") or {}).get("organ") or "").lower(), 99),
        str((e.get("experimentDescription") or {}).get("organ") or ""),
        _SEX_RANK.get(str((e.get("experimentDescription") or {}).get("sex") or "").lower(), 99),
    ))
    return out


def pca_scores(matrix: np.ndarray, n: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """(scores [samples × n], explained-variance %) of a samples × features
    matrix: mean-centred, unscaled, SVD, sklearn's svd_flip sign convention."""
    x = matrix - matrix.mean(axis=0)
    u, s, _vt = np.linalg.svd(x, full_matrices=False)
    signs = np.sign(u[np.argmax(np.abs(u), axis=0), range(u.shape[1])])
    signs[signs == 0] = 1.0
    u = u * signs
    scores = u * s
    var = s ** 2
    pct = 100.0 * var / var.sum() if var.sum() > 0 else np.zeros_like(var)
    return scores[:, :n], pct[:n]


def _matrix(exp: dict) -> tuple[np.ndarray, list[float]] | None:
    treatments = exp.get("treatments") or []
    rows = []
    for pr in exp.get("probeResponses") or []:
        vals = pr.get("responses") or []
        if len(vals) != len(treatments):
            continue
        try:
            row = [float(v) for v in vals]
        except (TypeError, ValueError):
            continue
        if all(math.isfinite(v) for v in row):
            rows.append(row)
    if len(rows) < 3 or len(treatments) < 4:
        return None
    return np.asarray(rows).T, [float(t.get("dose") or 0.0) for t in treatments]


def _dose_label(d: float) -> str:
    return f"{d:g}"


def build_pca_figure(integrated: dict, dose_unit: str = "mg/kg") -> dict | None:
    """The figure payload ``{png_b64, caption}`` for Appendix C, or None when the
    project has no gene-expression experiment large enough for a PCA."""
    panels = []
    for exp in _experiments(integrated):
        m = _matrix(exp)
        if m is None:
            continue
        matrix, doses = m
        scores, pct = pca_scores(matrix)
        if scores.shape[1] < 3:
            continue
        desc = exp.get("experimentDescription") or {}
        label = f"{str(desc.get('organ') or '').title()}, {str(desc.get('sex') or '').title()}".strip(", ")
        panels.append((label or exp.get("name", ""), scores, pct, doses))
    if not panels:
        return None

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    all_doses = sorted({d for *_x, doses in panels for d in doses})
    cmap = plt.get_cmap("viridis", max(len(all_doses), 2))
    colour = {d: cmap(i) for i, d in enumerate(all_doses)}

    fig, axes = plt.subplots(len(panels), 3, figsize=(10.5, 3.2 * len(panels)), squeeze=False)
    for r, (label, scores, pct, doses) in enumerate(panels):
        for c, (i, j) in enumerate(_PAIRS):
            ax = axes[r][c]
            for d in sorted(set(doses)):
                idx = [k for k, dd in enumerate(doses) if dd == d]
                ax.scatter(scores[idx, i], scores[idx, j], s=18, color=colour[d],
                           label=_dose_label(d), edgecolors="none")
            ax.set_xlabel(f"PC{i + 1} ({pct[i]:.2f}%)", fontsize=8)
            ax.set_ylabel(f"PC{j + 1} ({pct[j]:.2f}%)", fontsize=8)
            ax.tick_params(labelsize=7)
            if c == 0:
                ax.set_title(f"{label} — PCA ({pct.sum():.2f}%)", fontsize=9, loc="left")
        handles, labels = axes[r][2].get_legend_handles_labels()
        axes[r][2].legend(handles, labels, title=f"Dose ({dose_unit})", fontsize=7,
                          title_fontsize=7, ncol=2, loc="center left",
                          bbox_to_anchor=(1.02, 0.5), frameon=False)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return {"png_b64": base64.b64encode(buf.getvalue()).decode("ascii"),
            "filename": "appendix-c-pca.png", "caption": CAPTION}
