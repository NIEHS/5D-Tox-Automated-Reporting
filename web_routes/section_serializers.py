"""
JSON-row serialization helpers for the section-card pipeline.

The pool orchestrator builds Python TableRow / IncidenceRow objects from
the integrated dataset, but the browser receives them as plain JSON.
These three serializers (plus one small helper) bridge that gap, and a
fourth function — _build_clinical_obs_section — assembles the Clinical
Observations card directly from the underlying CSVs because it doesn't
go through the NTP-stats pipeline.

The functions are deliberately pure: they take dicts in, produce dicts
out, and depend on no module-level state.  They originally lived in
pool_orchestrator.py; they were lifted out unchanged as part of the
split that turned that 3700-line module into focused submodules.

Quirk worth preserving: _js_dose_key replicates the exact stringification
behavior of JavaScript's String(number) so that dose-keyed dicts produced
in Python match the keys the browser uses to read them back.  Without
this, dose 1.0 would become "1.0" in Python and "1" in JS, and the row
data wouldn't line up across the wire.
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from bmdx_pipe import build_clinical_obs_tables


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _js_dose_key(dose: float) -> str:
    """
    Convert a float dose to the string key JavaScript would produce via
    String(number).

    JavaScript's String(0.3) produces "0.3" but String(1.0) produces "1"
    (drops trailing ".0").  We replicate this so Python-generated table data
    matches the keys the browser expects when rendering dose columns.

    Args:
        dose: A numeric dose value (e.g., 0.0, 0.3, 1.0, 10.0).

    Returns:
        String representation matching JavaScript's String(number) behavior.
    """
    if dose == int(dose):
        return str(int(dose))
    return str(dose)


# ---------------------------------------------------------------------------
# Core serializers
# ---------------------------------------------------------------------------

def serialize_table_rows(table_data: dict) -> dict:
    """
    Convert a {sex: [TableRow, ...]} dict to JSON-friendly nested dicts.

    Each TableRow has values_by_dose, n_by_dose, and trend_marker attributes.
    BMD/BMDL are excluded — they belong in the separate BMD summary table
    (matching the NIEHS reference report structure: platform tables + Table 8).
    Dose float keys are converted via _js_dose_key() to match JavaScript's
    String(number) behavior.

    Used by /api/process-bm2 and /api/process-integrated to serialize
    the NTP stats pipeline output for the browser.

    Args:
        table_data: Dict mapping sex label ("Male", "Female") to lists of
                    TableRow objects from apical_report.build_table_data().

    Returns:
        Dict mapping sex label to lists of JSON-serializable row dicts.
    """
    tables_json = {}
    for sex, rows in table_data.items():
        tables_json[sex] = []
        for row in rows:
            sorted_doses = sorted(row.values_by_dose.keys())
            entry = {
                "label": row.label,
                "doses": sorted_doses,
                "values": {_js_dose_key(d): v for d, v in row.values_by_dose.items()},
                "n": {_js_dose_key(d): n for d, n in row.n_by_dose.items()},
                "trend_marker": row.trend_marker,
            }
            # Include missing-animal data when present, so the UI can
            # render footnotes for dose groups with dead animals.
            if row.missing_animals_by_dose:
                entry["missing_animals"] = {
                    _js_dose_key(d): n
                    for d, n in row.missing_animals_by_dose.items()
                }
            tables_json[sex].append(entry)
    return tables_json


def serialize_incidence_rows(incidence_data: dict) -> dict:
    """
    Convert a {sex: [IncidenceRow, ...]} dict to JSON-friendly nested dicts.

    Similar to serialize_table_rows() but for clinical observation incidence
    data.  Each row has pre-formatted "n/N" strings instead of mean±SE values.
    Dose keys are converted via _js_dose_key() for JavaScript compatibility.

    The output includes a "table_type": "incidence" marker so the frontend
    can detect this is an incidence table and render it differently (no "n"
    row, "Finding" header instead of "Endpoint", cells are literal strings).

    Args:
        incidence_data: Dict mapping sex label to lists of IncidenceRow
                        objects from build_clinical_obs_tables().

    Returns:
        Dict mapping sex label to lists of JSON-serializable row dicts.
    """
    tables_json = {}
    for sex, rows in incidence_data.items():
        tables_json[sex] = []
        for row in rows:
            sorted_doses = sorted(row.incidence_by_dose.keys())
            entry = {
                "label": row.label,
                "doses": sorted_doses,
                # Values are pre-formatted "n/N" strings — the frontend
                # renders them directly without further formatting.
                "values": {
                    _js_dose_key(d): v
                    for d, v in row.incidence_by_dose.items()
                },
                # Total N per dose group (for the frontend to use if needed)
                "n": {
                    _js_dose_key(d): n
                    for d, n in row.total_n_by_dose.items()
                },
            }
            tables_json[sex].append(entry)
    return tables_json


# ---------------------------------------------------------------------------
# Section-card assembly (Clinical Observations)
# ---------------------------------------------------------------------------

def _build_clinical_obs_section(
    integrated: dict,
    compound_name: str,
    dose_unit: str,
) -> dict | None:
    """
    Build the Clinical Observations section card from stored CSV paths.

    Reads the CSV paths from integrated._meta.clinical_obs_files, calls
    build_clinical_obs_tables() to produce incidence data, then serializes
    it into the same shape as apical section cards — but with
    table_type="incidence" so the frontend knows to render differently.

    Args:
        integrated:    The full merged BMDProject dict with _meta overlay.
        compound_name: Chemical name for narrative/caption.
        dose_unit:     Dose unit string (e.g., "mg/kg").

    Returns:
        Section card dict, or None if no clinical obs files or no findings.
    """
    meta = integrated.get("_meta", {})
    csv_paths = meta.get("clinical_obs_files", [])
    if not csv_paths:
        return None

    incidence_data = build_clinical_obs_tables(csv_paths)
    if not incidence_data:
        return None

    tables_json = serialize_incidence_rows(incidence_data)

    return {
        "platform": "Clinical Observations",
        "title": "Clinical Observations",
        "tables_json": tables_json,
        "table_type": "incidence",
        "narrative": [],  # No auto-generated narrative for incidence tables
    }
