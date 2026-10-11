"""Appendix C.1 PCA: the published recipe (mean-centred, unscaled SVD with
scikit-learn's sign convention) over the integrated gene-expression matrix."""

import numpy as np
from genomics.pca_figure import build_pca_figure, pca_scores


def test_scores_are_the_mean_centred_principal_components():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(12, 30))
    scores, pct = pca_scores(x)
    xc = x - x.mean(axis=0)
    evals, evecs = np.linalg.eigh(xc.T @ xc)
    order = np.argsort(evals)[::-1][:3]
    ref = xc @ evecs[:, order]
    assert np.allclose(np.abs(scores), np.abs(ref))          # same axes, up to sign
    assert np.allclose(pct, 100 * evals[order] / evals.sum())


def test_largest_score_of_each_component_is_positive():
    rng = np.random.default_rng(1)
    scores, _ = pca_scores(rng.normal(size=(10, 20)))
    for k in range(3):
        assert scores[np.argmax(np.abs(scores[:, k])), k] > 0


def _experiment(organ, n=8, probes=12, dtype="gene_expression"):
    rng = np.random.default_rng(2)
    doses = [0.0, 0.0, 10.0, 10.0, 100.0, 100.0, 300.0, 300.0][:n]
    return {
        "experimentDescription": {"dataType": dtype, "organ": organ, "sex": "male"},
        "treatments": [{"name": f"s{i}", "dose": d} for i, d in enumerate(doses)],
        "probeResponses": [{"probe": {"id": f"p{j}"},
                            "responses": list(rng.normal(size=n) + j)} for j in range(probes)],
    }


def test_figure_from_gene_expression_experiments_only():
    payload = build_pca_figure({"doseResponseExperiments": [
        _experiment("liver"), _experiment("kidney"), _experiment("liver", dtype="tox_study")]})
    assert payload["png_b64"] and payload["filename"] == "appendix-c-pca.png"
    assert payload["caption"].startswith("Principal Component Analysis")


def test_no_expression_data_no_figure():
    assert build_pca_figure({"doseResponseExperiments": []}) is None
