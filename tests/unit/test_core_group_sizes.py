"""Materials and Methods group sizes count the Core cohort — or, in a study
whose files mark no cohort (NIEHS-02 … 06, RR-8: selection "Unknown"), every
animal.  Requiring "Core" there left the Methods without group sizes."""

import json

from narrative.methods_extract import _extract_core_group_sizes


def _session(tmp_path, selections):
    files = tmp_path / "files"
    files.mkdir()
    animals = {str(i): {"dose": dose, "selection": sel}
               for i, (dose, sel) in enumerate(selections)}
    (files / "body_weight_truth_male.sidecar.json").write_text(json.dumps({"sex": "Male", "animals": animals}))
    return str(tmp_path)


def test_unmarked_study_counts_every_animal(tmp_path):
    sel = [(0.0, "Unknown")] * 5 + [(1.35, "Unknown")] * 5
    assert _extract_core_group_sizes(_session(tmp_path, sel)) == (5, 5)


def test_marked_study_counts_core_only(tmp_path):
    sel = [(0.0, "Core Animals")] * 10 + [(4.0, "Core Animals")] * 5 + [(4.0, "Biosampling Animals")] * 3
    assert _extract_core_group_sizes(_session(tmp_path, sel)) == (5, 10)
