"""narrative.unified_narrative.extract_mortality — early removals from body-weight sidecars.

An animal that never reaches the scheduled sacrifice is an early removal even when
no removal weight was recorded (its only observation is SD0).  Missing it made the
animal-condition paragraph report 2 deaths in a group the body-weight table shows
had none surviving.
"""

import json

from narrative.unified_narrative import extract_mortality


def _obs(day, terminal):
    return {"day": day, "endpoint": "Body Weight", "value": "1", "terminal": terminal}


def test_animal_without_terminal_observation_counts_as_early_removal(tmp_path):
    animals = {
        "1": {"dose": 0.0, "observations": [_obs("SD0", False), _obs("SD5", True)]},
        "2": {"dose": 0.0, "observations": [_obs("SD0", False), _obs("SD5", True)]},
        "3": {"dose": 1000.0, "observations": [_obs("SD0", False), _obs("SD3", True)]},
        "4": {"dose": 1000.0, "observations": [_obs("SD0", False)]},
    }
    sc = tmp_path / "bw.sidecar.json"
    sc.write_text(json.dumps({"animals": animals}))
    m = extract_mortality({"Male": str(sc)})
    assert m["expected_terminal_day"] == "SD5"
    high = m["by_dose"][1000.0]["Male"]
    assert high["early_deaths"] == 2
    assert high["death_days"] == {"SD3": 1}  # the unrecorded day is not invented
    assert m["all_survived_doses"] == [0.0]
