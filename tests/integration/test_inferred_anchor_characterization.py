"""
Characterization of the INFERRED-pivot ↔ tox_study/anchor numerical relationship
on the golden DTXSID50469320 pool. Pre-work for ADR-0017 Increment D (derive a
derived file's dataType from its numerical match to the xlsx anchor).

These tests PIN CURRENT REALITY so the D-scope decision rests on measured data,
not on ADR-0017's a-priori assumption. They are characterization (they assert what
IS), not a spec (they do not assert what SHOULD be).

★ THERE ARE TWO DISTINCT INFERENCE MECHANISMS — do not conflate them:

  (1) DOSE-GROUP DROP — a whole (or partial) dead-out dose group is REMOVED from
      the inferred pivot (e.g. 333/1000 mg/kg, all animals died). Surviving-animal
      cells are byte-identical to truth. This is what the PFHxSAm golden pool
      exercises at the PIVOT-TXT layer, and it is what THIS test measures.

  (2) CELL IMPUTATION — an INDIVIDUAL missing cell (a dead animal / lost sample
      inside a SURVIVING dose group) is filled with the DOSE-GROUP AVERAGE, because
      BMDExpress curve-fitting can't tolerate gaps. This is exactly ADR-0017's
      "dose-group-average substitution", and it IS REAL: it lives in the
      legacy/inferred BMDExpress upload → flows into the .bm2 → the report footnotes
      it ("N missing individual values were imputed…", clinical_pathology_table.py).
      It is detected by `_detect_imputed_cells` (pipeline/bmd_project_schema.py) and
      pinned in tests/unit/test_bmd_project_schema.py::test_imputed_cell_recorded.
      The PFHxSAm reference report shows NO imputation footnote → this fixture is
      DROP-DOMINANT and does not visibly exercise mechanism (2) at the txt layer.

★ CONSEQUENCE FOR ADR-0017 D: a classifier that keys ONLY on cell-value matching is
insufficient for BOTH mechanisms. For (1) the discriminator is the ROSTER (present
dose groups) — overlapping cells match EXACTLY, so "exact match → tox_study" would
MISLABEL a dropped-dose inferred file. For (2) the discriminator IS cell values
(truth-missing / legacy-present), which is what `_detect_imputed_cells` already
does one layer down (truth/legacy .bm2 pair), NOT at the pivot-txt/xlsx-anchor
layer this test lives at. So D must reconcile: roster-relationship for the txt
tier, and the already-built imputation detection for the bm2 tier. See
docs/plans/bmdx-pipe-seam-recut.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_GOLDEN = Path(__file__).parents[1] / "fixtures" / "golden" / "DTXSID50469320"
_FILES = _GOLDEN / "files"

pytestmark = pytest.mark.skipif(
    not _FILES.exists(), reason="golden DTXSID50469320 fixture not present"
)


def _read_pivot(path: Path):
    """Parse a wide pivot txt (header=animal ids; Concentration/Dose row=doses;
    remaining rows=endpoint×animal). Returns (animals, {animal: dose},
    {(endpoint, animal): value_str})."""
    lines = [l.rstrip("\n") for l in path.read_text().splitlines()
             if l.strip() and not l.startswith("#")]
    rows = [l.split("\t") for l in lines]
    animals = rows[0][1:]
    doses: dict[str, float] = {}
    vals: dict[tuple[str, str], str] = {}
    for r in rows[1:]:
        label, cells = r[0], r[1:]
        if label.lower() in ("concentration", "dose"):
            for a, c in zip(animals, cells):
                try:
                    doses[a] = float(c)
                except ValueError:
                    pass
        else:
            for a, c in zip(animals, cells):
                vals[(label, a)] = c.strip()
    return animals, doses, vals


def _cells_equal(x: str, y: str) -> bool:
    if x == y:
        return True
    try:
        return abs(float(x) - float(y)) < 1e-9
    except ValueError:
        return False


# Platforms whose truth/inferred pivots share the SAME endpoint labelling and are
# therefore directly cell-comparable. (Clinical Chemistry & Hematology truth txt
# use a day-tag row labelling that differs from the inferred analyte-name rows, so
# a txt↔txt cell compare is not meaningful for them — the xlsx anchor is the only
# common reference there. That shape difference is itself pinned below.)
_COMPARABLE = [
    ("male_body_weight.txt", "body_weight_truth_male.txt"),
    ("male_organ_weights.txt", "organ_weights_truth_male.txt"),
    ("male_hormone_data.txt", "hormones_truth_male.txt"),
]


@pytest.mark.integration
@pytest.mark.parametrize("inferred_name,truth_name", _COMPARABLE)
def test_inferred_pivot_is_dose_drop_at_txt_layer(inferred_name, truth_name):
    """At the PIVOT-TXT layer for THIS fixture, the inferred pivot = truth with
    dead-out dose groups dropped; surviving cells byte-identical. (Cell imputation
    — mechanism 2 — lives in the .bm2 tier, not here; see module docstring.)"""
    ia, idz, iv = _read_pivot(_FILES / inferred_name)
    ta, tdz, tv = _read_pivot(_FILES / truth_name)

    # The inferred roster is a strict SUBSET of truth (some dose groups dropped).
    assert set(ia) <= set(ta), "inferred introduced animals not in truth"
    dropped_animals = set(ta) - set(ia)

    # Everything dropped is a WHOLE dose group at the high end (dead-out doses).
    inferred_doses = set(idz.values())
    truth_doses = set(tdz.values())
    dropped_doses = truth_doses - inferred_doses
    if dropped_animals:
        assert dropped_doses, "animals dropped but no dose group removed"
        # Dropped doses are the HIGHEST doses (dead-out at the top).
        assert min(dropped_doses) > max(inferred_doses), (
            "dropped dose groups are not the top doses — not a dead-out drop"
        )

    # Overlapping (endpoint, animal) cells are byte-identical: no gap-fill, no edit.
    common_animals = set(ia) & set(ta)
    common_eps = {k[0] for k in iv} & {k[0] for k in tv}
    mism = fill = 0
    for ep in common_eps:
        for a in common_animals:
            x, y = iv.get((ep, a), ""), tv.get((ep, a), "")
            if x == "" and y == "":
                continue
            if y == "" and x != "":
                fill += 1  # a true gap-fill would land here
                continue
            if x != "" and not _cells_equal(x, y):
                mism += 1
    assert mism == 0, f"{inferred_name}: {mism} surviving cells differ from truth"
    assert fill == 0, (
        f"{inferred_name}: {fill} cells gap-filled at the txt layer — in THIS "
        f"fixture the pivot inference is dose-drop, not cell-fill (cell imputation "
        f"is exercised in the .bm2 tier; see test_bmd_project_schema)"
    )


@pytest.mark.integration
def test_exact_match_alone_cannot_separate_dropdose_inferred_from_toxstudy():
    """Pins the classifier trap for the DOSE-DROP mechanism: on overlapping cells
    the inferred pivot matches the truth EXACTLY, so 'exact value match ⇒ tox_study'
    is unsound HERE. The roster (present dose groups) is the discriminator. (For the
    cell-imputation mechanism the opposite holds — there the value IS the signal;
    that path is covered by test_bmd_project_schema, not this txt-layer test.)"""
    ia, idz, iv = _read_pivot(_FILES / "male_organ_weights.txt")
    ta, tdz, tv = _read_pivot(_FILES / "organ_weights_truth_male.txt")
    common_animals = set(ia) & set(ta)
    common_eps = {k[0] for k in iv} & {k[0] for k in tv}
    compared = 0
    for ep in common_eps:
        for a in common_animals:
            x, y = iv.get((ep, a), ""), tv.get((ep, a), "")
            if x and y:
                assert _cells_equal(x, y)
                compared += 1
    assert compared > 100, "expected a substantial overlap of identical cells"
    # Yet the rosters differ — inferred is missing the top two dose groups.
    assert set(tdz.values()) - set(idz.values()) == {333.0, 1000.0}


@pytest.mark.integration
def test_clinchem_hematology_truth_uses_different_endpoint_labelling():
    """Pins WHY clin_chem/hematology are not txt↔txt comparable: the truth pivot
    rows are day-tagged (e.g. 'SD5'), the inferred rows are analyte names. Only
    the xlsx anchor (long format) is a common reference for these platforms."""
    _, _, truth_cc = _read_pivot(_FILES / "clin_chem_truth_male.txt")
    _, _, inf_cc = _read_pivot(_FILES / "male_clin_chem.txt")
    truth_eps = {k[0] for k in truth_cc}
    inf_eps = {k[0] for k in inf_cc}
    # Disjoint endpoint namespaces — no shared labels to compare on.
    assert truth_eps.isdisjoint(inf_eps), (
        "expected disjoint endpoint labels between truth (day-tag) and inferred "
        "(analyte-name) clin-chem pivots"
    )
    assert "Alanine aminotransferase" in inf_eps
    assert "Alanine aminotransferase" not in truth_eps
