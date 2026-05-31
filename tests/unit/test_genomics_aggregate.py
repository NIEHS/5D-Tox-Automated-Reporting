"""
Unit tests for `aggregate_organ_llm_narratives` — the shared helper that
folds per-(organ, sex) LLM narratives into per-organ paragraph lists.

The helper is the single source of truth for three call sites
(process_integrated Layer 3.5a, the session-reload path in session_routes,
and the per-organ Regenerate endpoint in llm_routes).  These tests pin the
behaviour those three paths rely on: fixed male-then-female ordering, the
"Male:"/"Female:" label on the first paragraph of each sex block, and the
user-override-wins merge.
"""

from genomics_narratives import aggregate_organ_llm_narratives


def test_male_then_female_ordering_and_labels():
    # Female appears first in the dict but must render after male, and the
    # first paragraph of each sex block gets a capitalised label prefix.
    gs, gn = aggregate_organ_llm_narratives({
        "liver": {
            "female": {"gs": ["f1", "f2"], "gn": ["fg1"]},
            "male": {"gs": ["m1"], "gn": ["mg1", "mg2"]},
        },
    })
    assert gs["liver"] == ["Male: m1", "Female: f1", "f2"]
    assert gn["liver"] == ["Male: mg1", "mg2", "Female: fg1"]


def test_organ_with_no_paragraphs_is_omitted():
    # An organ whose blocks carry empty lists produces no key at all.
    gs, gn = aggregate_organ_llm_narratives({
        "kidney": {"male": {"gs": [], "gn": []}},
    })
    assert gs == {}
    assert gn == {}


def test_override_replaces_llm_output_and_is_case_insensitive():
    # An override (cased "Liver") wins over the aggregated LLM output and is
    # matched against the lower-cased organ key.
    gs, gn = aggregate_organ_llm_narratives(
        {"liver": {"male": {"gs": ["m1"], "gn": ["mg1"]}}},
        overrides={"gene_set": {"Liver": ["EDIT"]}, "gene_bmd": {}},
    )
    assert gs["liver"] == ["EDIT"]          # override wins
    assert gn["liver"] == ["Male: mg1"]     # untouched kind keeps LLM output


def test_empty_override_list_leaves_llm_output_in_place():
    # An empty override list must NOT clobber the LLM output (that is how the
    # override file represents "cleared" — the LLM tier should win again).
    gs, _ = aggregate_organ_llm_narratives(
        {"liver": {"male": {"gs": ["m1"], "gn": []}}},
        overrides={"gene_set": {"liver": []}, "gene_bmd": {}},
    )
    assert gs["liver"] == ["Male: m1"]


def test_none_overrides_skips_merge():
    # The Regenerate path passes overrides=None; the helper must not crash and
    # must return the bare LLM aggregation.
    gs, gn = aggregate_organ_llm_narratives(
        {"liver": {"male": {"gs": ["m1"], "gn": ["mg1"]}}},
        overrides=None,
    )
    assert gs == {"liver": ["Male: m1"]}
    assert gn == {"liver": ["Male: mg1"]}
