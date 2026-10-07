"""Method profiles (ADR-0027): closed schema, layered resolution with sources,
immutable pins."""

import json

import pytest
import yaml

from pipeline import method_profile as mp


def test_shipped_profiles_load_and_validate():
    names = {p["name"] for p in mp.list_profiles()}
    assert {"ntp-5day-2025", "ntp-5day-2021"} <= names
    assert mp.newest_profile() == "ntp-5day-2025"


def test_profile_values_carry_their_source():
    s = mp.resolve("ntp-5day-2025")
    assert s.get("apical.statistics.trend_select_p") == 0.01
    assert s.source("apical.statistics.trend_select_p") == "profile:ntp-5day-2025"
    assert s.pairwise("Clinical Chemistry") == "shirley_or_dunn"
    assert s.get("apical.statistics.outliers") is None                    # null → default
    assert s.source("apical.statistics.outliers") == "default"
    assert s.stats_method().family("Organ Weight") == "parametric"
    assert s.acceptance_criteria().r2_min == 0.6
    assert not s.deviations


def test_unimplemented_engine_is_a_stated_deviation_not_a_silent_one():
    s = mp.resolve("ntp-5day-2021")
    assert s.get("apical.bmd.engine") == "toxicr_model_average"
    assert "not implemented" in s.source("apical.bmd.engine")
    assert any("bmds_2_7_high_dose_drop" in d for d in s.deviations)
    assert s.source("genomics.go_ranking") == "default"                  # "to confirm"


def test_overlay_and_request_layers_override_in_order():
    s = mp.resolve("ntp-5day-2025",
                   overlay={"apical": {"statistics": {"min_group_n": 3}}}, overlay_label="study:X",
                   request={"genomics": {"go_ranking": ["median"]}})
    assert (s.get("apical.statistics.min_group_n"), s.source("apical.statistics.min_group_n")) \
        == (3, "study:X")
    assert (s.get("genomics.go_ranking"), s.source("genomics.go_ranking")) == (["median"], "request")
    assert s.signature() != mp.resolve("ntp-5day-2025").signature()


@pytest.mark.parametrize("mutate,message", [
    (lambda d: d["apical"]["statistics"].update(trend_selct_p=0.01), "unknown key"),
    (lambda d: d["apical"]["statistics"].pop("alpha"), "missing key"),
    (lambda d: d["apical"]["statistics"]["pairwise"].update({"Body Weight": "t_test"}), "unknown pairwise"),
    (lambda d: d["apical"]["statistics"].update(alpha=5), "number in [0, 1]"),
])
def test_schema_fails_loudly(tmp_path, monkeypatch, mutate, message):
    doc = yaml.safe_load((mp.PROFILES_DIR / "ntp-5day-2025.yaml").read_text())
    mutate(doc)
    doc["name"] = "broken"
    (tmp_path / "broken.yaml").write_text(yaml.safe_dump(doc))
    monkeypatch.setattr(mp, "PROFILES_DIR", tmp_path)
    with pytest.raises(mp.MethodProfileError, match=message.replace("[", r"\[").replace("]", r"\]")):
        mp.load_profile("broken")


def test_pin_is_explicit_and_a_changed_profile_is_refused(tmp_path, monkeypatch):
    import common.paths

    monkeypatch.setattr(common.paths, "SESSIONS_DIR", tmp_path)
    (tmp_path / "DTXSIDX").mkdir()
    assert mp.read_pin("DTXSIDX") is None
    s = mp.session_method("DTXSIDX")                       # unpinned: newest, said so
    assert s.profile == "ntp-5day-2025" and any("no profile pinned" in d for d in s.deviations)
    assert mp.read_pin("DTXSIDX") is None                  # reading never pins

    pin = mp.ensure_pin("DTXSIDX")
    assert pin["name"] == "ntp-5day-2025" and pin["pinned_by"] == "default"
    assert mp.pin_profile("DTXSIDX", "ntp-5day-2025")["pinned_by"] == "user"   # confirmed
    assert mp.read_pin("DTXSIDX")["pinned_by"] == "user"
    assert mp.ensure_pin("DTXSIDX")["pinned_by"] == "user"                     # never downgraded
    mp.pin_profile("DTXSIDX", "ntp-5day-2021")
    assert mp.read_pin("DTXSIDX")["name"] == "ntp-5day-2021"
    assert list((tmp_path / "DTXSIDX" / "history" / "_method_profile").glob("*.json"))

    bad = mp.read_pin("DTXSIDX") | {"hash": "0" * 16}
    (tmp_path / "DTXSIDX" / mp.PIN_FILE).write_text(json.dumps(bad))
    with pytest.raises(mp.MethodProfileError, match="immutable"):
        mp.session_method("DTXSIDX")


def test_a_process_request_overrides_only_what_it_states(tmp_path, monkeypatch):
    import common.paths
    from pipeline.process_integrated import _resolve_request_method

    monkeypatch.setattr(common.paths, "SESSIONS_DIR", tmp_path)
    (tmp_path / "DTXSIDX").mkdir()
    m = _resolve_request_method("DTXSIDX", {})
    assert m.get("genomics.go_ranking") == ["fifth_pct", "median"]
    m = _resolve_request_method("DTXSIDX", {"bmd_stats": ["median"], "go_min_genes": 40})
    assert m.get("genomics.go_ranking") == ["median"] and m.source("genomics.go_ranking") == "request"
    assert m.get("genomics.go_display") == {"pct": 5, "min_genes": 40, "max_genes": 500, "min_bmd": 3}


def test_recorded_settings_that_disagree_are_reported_not_overridden():
    integrated = {"bMDResult": [{"name": "rat_4D_LI_No0_BMD", "analysisInfo": {"notes": [
        "Data Source: rat_4D_LI_No0", "Model Averaging Method: Laplace Model Averaging",
        "BMR Type: Relative Deviation", "BMR Factor: 0.25"]}}]}
    assert mp.recorded_mismatches(integrated, mp.resolve("ntp-5day-2025")) == []
    found = mp.recorded_mismatches(integrated, mp.resolve("ntp-5day-2021"))
    assert {f["setting"] for f in found} == {"genomics.recorded.bmr", "genomics.recorded.model_selection"}
    assert "1 SD" in found[0]["message"] or "1 SD" in found[1]["message"]


def test_footnotes_name_the_tests_the_profile_ran():
    s = mp.resolve("ntp-5day-2025")
    assert mp.statistics_sentence(s, s.pairwise("Hematology")) == (
        "Statistical analysis performed by the Jonckheere (trend) and Shirley or Dunn "
        "(pairwise) tests.")
    assert mp.statistics_sentence(s, "none") is None
    assert mp.marker_legend(s) == "*Statistically significant at p ≤ 0.05; **p ≤ 0.01."


def test_integration_pins_and_flags_recorded_disagreements(tmp_path, monkeypatch):
    """integrate_step's method hook: pins the newest profile when none is pinned,
    and puts each recorded-vs-profile disagreement in the validation report."""
    import common.paths
    from workflow.steps import _pin_and_check_method

    monkeypatch.setattr(common.paths, "SESSIONS_DIR", tmp_path)
    (tmp_path / "DTXSIDX").mkdir()
    mp.pin_profile("DTXSIDX", "ntp-5day-2021")

    class Store:
        report = {"issues": [{"issue_type": "method_mismatch", "message": "stale"},
                             {"issue_type": "roster_subset", "message": "kept"}]}

        def read_json(self, dtxsid, name):
            return self.report

        def write_json(self, dtxsid, name, data):
            self.report = data

    store = Store()
    integrated = {"bMDResult": [{"name": "rat_4D_LI_No0_BMD", "analysisInfo": {"notes": [
        "Data Source: rat_4D_LI_No0", "BMR Type: Relative Deviation", "BMR Factor: 0.25"]}}]}
    summary = _pin_and_check_method("DTXSIDX", integrated, store)
    assert summary["profile"] == "ntp-5day-2021" and summary["pinned_by"] == "user"
    assert any("bmds_2_7" in d for d in summary["deviations"])
    kinds = [i["issue_type"] for i in store.report["issues"]]
    assert kinds == ["roster_subset", "method_mismatch"]
    assert store.report["issues"][1]["details"]["setting"] == "genomics.recorded.bmr"
