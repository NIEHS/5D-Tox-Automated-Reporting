"""A source that could not be queried is not evidence of a data gap.

The Background's data-gap paragraph is written from build_data_gap_analysis.
When ATSDR/IRIS are unreachable (firewall, outage) or never gathered (RfC),
their items must read "unknown", not "missing" — otherwise the report claims
"no IRIS assessment exists" for a chemical that has one.
"""

from narrative.chem_resolver import ChemicalIdentity
from narrative.data_gatherer import BackgroundData, build_data_gap_analysis


def _status(data, item):
    return next(g["status"] for g in data.data_gaps if g["item"] == item)


def test_unreachable_sources_make_their_items_unknown():
    data = BackgroundData(identity=ChemicalIdentity(name="X", casrn="1-2-3"))
    data.unreachable_sources = ["ATSDR", "IRIS", "CTX"]
    build_data_gap_analysis(data)
    assert _status(data, "ATSDR Toxicological Profile") == "unknown"
    assert _status(data, "EPA IRIS assessment") == "unknown"
    assert _status(data, "Oral reference dose (RfD)") == "unknown"
    assert _status(data, "Inhalation reference concentration (RfC)") == "unknown"


def test_reachable_but_empty_sources_are_missing():
    data = BackgroundData(identity=ChemicalIdentity(name="X", casrn="1-2-3"))
    build_data_gap_analysis(data)
    assert _status(data, "ATSDR Toxicological Profile") == "missing"
    assert _status(data, "EPA IRIS assessment") == "missing"
    # IRIS reachable, CTX not: the RfD could still have come from IRIS → missing.
    data.unreachable_sources = ["CTX"]
    build_data_gap_analysis(data)
    assert _status(data, "Oral reference dose (RfD)") == "missing"
