"""Clinical observations worded as the NIEHS reports word them
(narrative.clinical_signs)."""

from types import SimpleNamespace

from narrative.clinical_signs import sign_phrases


def _rows(*cols):
    return [SimpleNamespace(parts=dict(zip(("observation", "site", "modifier", "severity"), c)))
            for c in cols]


def test_niehs10_signs_read_as_the_report_lists_them():
    # NIEHS-10: "red discharge from nose/snout and penis, clear or red discharge
    # from eyes, labored breathing, pale appearance, salivation, hunched posture,
    # prone positioning, and lethargy" — the partially cannibalized animal is not a sign.
    phrases = sign_phrases(_rows(
        ("Breathing, labored", "", "", ""),
        ("Discharge", "Eye", "Bilateral, Clear", ""),
        ("Discharge", "Eye", "Bilateral, Red", ""),
        ("Discharge", "Eye", "Left, Red", ""),
        ("Discharge", "Nose/Snout", "Red", ""),
        ("Discharge", "Penis", "Red", ""),
        ("Hunched", "", "", ""),
        ("Lethargic", "", "", ""),
        ("Pale", "", "", ""),
        ("Partially Cannibalized", "", "", ""),
        ("Prone", "", "", ""),
    ))
    assert phrases == ["labored breathing", "clear or red discharge from eyes",
                       "red discharge from nose/snout and penis", "hunched posture",
                       "lethargy", "pale appearance", "prone positioning"]


def test_niehs07_coat_feces_and_urogenital():
    phrases = sign_phrases(_rows(
        ("Coat Ruffled", "", "", ""), ("Coat Unkempt", "", "", ""),
        ("Feces", "", "Soft", ""), ("Wet", "Urogenital", "", ""), ("Cold To Touch", "", "", ""),
    ))
    assert phrases == ["ruffled or unkempt coat", "soft feces", "wet urogenital area",
                       "cold to touch"]


def test_severity_leads_timing_follows_and_an_implied_site_keeps_its_side():
    # NIEHS-13: "piloerection, bilateral dilated pupil, and moderate tremors …
    # lacrimation post exposure"; NIEHS-12: "mild ataxia".
    phrases = sign_phrases(_rows(
        ("Lacrimation", "", "", "Post Dosing"), ("Pupil Dilated", "Eye", "Bilateral", ""),
        ("Tremors", "", "", "Moderate"), ("Ataxia", "", "", "Mild"),
    ), inhaled=True)
    assert phrases == ["lacrimation post exposure", "bilateral dilated pupil",
                       "moderate tremors", "mild ataxia"]
    assert sign_phrases(_rows(("Salivation", "", "", "Post Dosing"))) == ["salivation post dosing"]


def test_diarrhea_and_weight_loss():
    # NIEHS-05: "lethargy, and diarrhea, as well as a 13%–25% decrease in body weight".
    assert sign_phrases(_rows(("Feces", "", "Diarrhea, Soft", ""), ("Weight loss", "", "13%", ""),
                              ("Weight loss", "", ">20%", ""))) == ["diarrhea", "weight loss"]


def test_a_term_outside_the_vocabulary_is_kept_as_recorded():
    assert sign_phrases(_rows(("Hypoactivity", "", "", ""), ("Swelling", "Paw", "Left", ""))) == \
        ["hypoactivity", "swelling (paw)"]
