"""
narrative/clinical_signs.py — clinical observations as the reports word them.

The clinical-observation files record each finding in four NTP columns
(Observation, Site, Modifier, Severity), and the incidence table labels a row
"Discharge — Eye, Bilateral, Red" or "Tremors (Moderate)".  Prose needs
English: the published Animal Condition paragraphs say "red discharge from
nose/snout and penis, clear or red discharge from eyes, labored breathing,
pale appearance, salivation, hunched posture, prone positioning, and lethargy"
(NIEHS-10), "ruffled or unkempt coat … soft feces … wet urogenital area"
(NIEHS-07), "piloerection, bilateral dilated pupil, and moderate tremors"
(NIEHS-13), "mild ataxia" (NIEHS-12), "red discharge from eyes and nose,
lethargy, and diarrhea" (NIEHS-05).

``sign_phrases`` turns IncidenceRows (their ``parts``) into those phrases and
merges the ones that share a noun:
  - a severity leads ("moderate tremors"); a timing follows ("lacrimation post
    exposure");
  - an inverted term is put right ("Breathing, labored" → "labored breathing");
    the terms that aren't prose as they stand are in ``_TERMS``;
  - a discharge names where it came from, the paired organs plural and the side
    dropped ("from eyes"); a site the noun already implies (a pupil's eye)
    gives its side to the noun instead ("bilateral dilated pupil");
  - phrases differing only in their adjectives merge with "or" ("clear or red
    discharge from eyes"), then those differing only in their site with "and"
    ("red discharge from nose/snout and penis");
  - a percentage modifier is dropped ("Weight loss, 13%" → "weight loss"); a
    finding on a dead animal (``_POSTMORTEM``) is not a sign.
A term outside the vocabulary is lower-cased as recorded.  This is wording of
the NTP vocabulary, not a study fact.
"""

from __future__ import annotations

import re

_SEVERITIES = ("minimal", "slight", "mild", "moderate", "marked", "severe")
_SIDES = ("bilateral", "unilateral", "left", "right")
_PAIRED = {"eye": "eyes", "ear": "ears", "forelimb": "forelimbs", "hindlimb": "hindlimbs"}

# NTP terms that are not prose as they stand: (adjective, noun).
_TERMS = {
    "coat ruffled": ("ruffled", "coat"),
    "coat unkempt": ("unkempt", "coat"),
    "pupil dilated": ("dilated", "pupil"),
    "pupil constricted": ("constricted", "pupil"),
    "hunched": ("hunched", "posture"),
    "prone": ("prone", "positioning"),
    "pale": ("pale", "appearance"),
    "lethargic": ("", "lethargy"),
}
# An adjective term whose site is its noun: "Wet | Urogenital" → "wet urogenital area".
_SITE_NOUN = {"wet": "{site} area", "loose": "{site}", "stained": "{site}"}
# A noun that already names its site: the side goes to the noun.
_IMPLIED_SITE = {"pupil": "eye"}
# Findings on a dead animal, not signs of toxicity.
_POSTMORTEM = {"partially cannibalized", "cannibalized", "autolysis"}


def _sign(parts: dict, inhaled: bool) -> dict | None:
    obs = (parts.get("observation") or "").strip().lower()
    if not obs or obs == "normal" or obs in _POSTMORTEM:
        return None
    site = (parts.get("site") or "").strip().lower()
    mods = [m.strip().lower() for m in (parts.get("modifier") or "").split(",") if m.strip()]
    severity = (parts.get("severity") or "").strip().lower()

    if obs in _TERMS:
        adj, noun = _TERMS[obs]
    elif "," in obs:                          # "breathing, labored"
        noun, adj = (p.strip() for p in obs.split(",", 1))
    else:
        adj, noun = "", obs
    if obs in _SITE_NOUN and site:
        adj, noun, site = obs, _SITE_NOUN[obs].format(site=site), ""
    if noun == "feces" and "diarrhea" in mods:
        return {"adjs": "", "noun": "diarrhea", "where": "", "timing": ""}

    sides = [m for m in mods if m in _SIDES]
    others = [m for m in mods if m not in _SIDES and not re.search(r"\d|%", m)]
    adjs = ([severity] if severity in _SEVERITIES else []) + others + ([adj] if adj else [])
    where = ""
    if site and _IMPLIED_SITE.get(noun) == site:
        adjs = sides + adjs
    elif site:
        where = f" from {_PAIRED.get(site, site)}" if noun == "discharge" else f" ({site})"
    timing = ""
    if severity and severity not in _SEVERITIES:
        timing = " post exposure" if inhaled and severity == "post dosing" else f" {severity}"
    return {"adjs": " ".join(adjs), "noun": noun, "where": where, "timing": timing}


def _join(items: list[str], word: str) -> str:
    if len(items) <= 1:
        return "".join(items)
    if len(items) == 2:
        return f"{items[0]} {word} {items[1]}"
    return f"{', '.join(items[:-1])}, {word} {items[-1]}"


def sign_phrases(rows: list, inhaled: bool = False) -> list[str]:
    """The prose phrases for clinical-observation rows (IncidenceRow, or any
    object with ``parts`` / ``label``), in row order, merged as the module
    says.  A row without ``parts`` gives its label lower-cased."""
    signs: list[dict] = []
    for row in rows:
        parts = getattr(row, "parts", None)
        if not parts:
            label = str(getattr(row, "label", row)).strip().lower()
            if label and label not in _POSTMORTEM:
                signs.append({"adjs": "", "noun": label, "where": "", "timing": ""})
            continue
        sign = _sign(parts, inhaled)
        if sign:
            signs.append(sign)

    # 1. One noun, site and timing: the adjectives with "or".
    by_noun: dict[tuple, list[str]] = {}
    for s in signs:
        adjs = by_noun.setdefault((s["noun"], s["where"], s["timing"]), [])
        if s["adjs"] not in adjs:
            adjs.append(s["adjs"])
    merged = [(_join(sorted(a for a in adjs if a), "or"), noun, where, timing)
              for (noun, where, timing), adjs in by_noun.items()]

    # 2. One adjective, noun and timing, several sites: the sites with "and".
    by_site: dict[tuple, list[str]] = {}
    for adjs, noun, where, timing in merged:
        key = (adjs, noun, timing, where.startswith(" from "))
        by_site.setdefault(key, []).append(where)
    out = []
    for (adjs, noun, timing, from_site), wheres in by_site.items():
        if from_site and len(wheres) > 1:
            groups = [_join([w[len(" from "):] for w in wheres], "and")]
            wheres = [f" from {groups[0]}"]
        for where in wheres:
            out.append(f"{adjs + ' ' if adjs else ''}{noun}{where}{timing}")
    return list(dict.fromkeys(out))
