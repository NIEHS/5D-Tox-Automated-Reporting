"""Approved ExperimentDescriptions survive re-integration.

Integration re-infers metadata from experiment names every run; an approved
description must win (NIEHS-13: "rat_4D_HE_No0" — heart — re-inferred as blood).
"""

from bmdx_pipe.pool_integrator import _apply_approved_metadata


def test_approved_description_replaces_the_inferred_one():
    exps = [{"name": "rat_4D_HE_No0", "experimentDescription": {"organ": "blood", "sex": "female"}},
            {"name": "rat_4D_KI_No0", "experimentDescription": {"organ": "kidney"}}]
    approved = {"rat_4D_HE_No0": {"organ": "heart", "sex": "female"}, "gone_exp": {"organ": "x"}}
    assert _apply_approved_metadata(exps, approved) == 1
    assert exps[0]["experimentDescription"] == {"organ": "heart", "sex": "female"}
    assert exps[1]["experimentDescription"] == {"organ": "kidney"}      # not approved: inferred kept
    # A copy, not the approval record itself (later reconciles mutate descriptions).
    assert exps[0]["experimentDescription"] is not approved["rat_4D_HE_No0"]
