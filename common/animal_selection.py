"""
common/animal_selection.py — which cohort an animal belongs to.

NTP study files tag each animal with a Selection: "Core Animals" (the
scheduled-sacrifice cohort every table and statistic is built from) or the
internal-dose cohort, sacrificed on its own schedule for plasma/tissue
concentrations.  The CEBS packages spell the latter two ways — "Biosampling
Animals" (NIEHS-10) and "Biosample Animals" (NIEHS-07, -12, -13) — so match
the stem, as bmdx-pipe's animal report does.  Kept in the dependency-free
`common` package so tables/, narrative/ and pipeline/ share one rule.
"""


def is_biosampling(selection: str | None) -> bool:
    """True for the internal-dose (biosampling) cohort, in either spelling."""
    return "biosamp" in str(selection or "").lower()
