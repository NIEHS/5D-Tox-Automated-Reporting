"""
front_matter.py — human-set report front-matter (authors, contributors, publication).

The Authors and Contributors parts and parts of "Publication Details"
(report number, DOI, date) are STUDY-SPECIFIC metadata a human supplies — the study
pipeline can't derive personnel names or an as-yet-unassigned DOI. They are persisted
per session in `sessions/<dtxsid>/front_matter.json` (written by the Configure UI) and
overlaid into the render data on both export paths (marshal + session-reload).

This module owns:
  * the persisted-shape → render-shape transform, so BOTH overlay paths format
    identically, and
  * merging publication overrides onto the boilerplate scaffold.

Persisted shape (front_matter.json):
    {
      "authors":      [ {"name","affiliation","role"} , ... ],   # ordered = author order
      "contributors": [ {"name","role"} , ... ],
      "publication":  { "report_number", "doi", "report_date" },  # any subset
      "strain_designation": "(Hsd:Sprague Dawley® SD®)"   # the title's supplier
    }                                                        # designation, optional

Render shape: the `authors` and `contributors` keys (ADR-0028 — two front-matter
parts, as the published book has them; formerly one labeled `about_report`) are
plain paragraph lists, one roster line per paragraph, which every surface's
front-matter resolver already renders:
    {"paragraphs": ["Name, Role, Affiliation", ...]}
The structured roster itself is kept on `data["front_matter"]` (cleaned) for the
BITS projection, which groups names by affiliation and role and builds the
book-meta <contrib-group>.
"""

from __future__ import annotations


def _author_line(a: dict) -> str:
    """Format one author roster entry as 'Name, Role, Affiliation' (blanks dropped).
    Position in the roster is the author order and is not printed."""
    if not isinstance(a, dict):
        return ""
    parts = [(a.get("name") or "").strip()]
    for key in ("role", "affiliation"):
        v = (a.get(key) or "").strip()
        if v:
            parts.append(v)
    parts = [p for p in parts if p]
    return ", ".join(parts)


def _contributor_line(c: dict) -> str:
    """Format one contributor as 'Name — Role' (role optional)."""
    if not isinstance(c, dict):
        return ""
    name = (c.get("name") or "").strip()
    role = (c.get("role") or "").strip()
    if name and role:
        return f"{name} — {role}"
    return name or role


def build_authors(front_matter: dict) -> dict | None:
    """The `authors` render value — one 'Name, Role, Affiliation' paragraph per
    roster entry, in author order — or None when no authors are set."""
    if not isinstance(front_matter, dict):
        return None
    lines = [ln for ln in (_author_line(a) for a in front_matter.get("authors") or []) if ln]
    return {"paragraphs": lines} if lines else None


def build_contributors(front_matter: dict) -> dict | None:
    """The `contributors` render value — one 'Name — Role' paragraph per roster
    entry — or None when no contributors are set."""
    if not isinstance(front_matter, dict):
        return None
    lines = [ln for ln in (_contributor_line(c) for c in front_matter.get("contributors") or []) if ln]
    return {"paragraphs": lines} if lines else None


# The publication_details scaffold lines this overrides, keyed by their "Prefix:".
_PUBLICATION_OVERRIDES = {
    "report_number": "Report Series Number",
    "doi": "DOI",
    "report_date": "Publication Date",
}


def apply_publication_overrides(publication_details: dict, front_matter: dict) -> dict:
    """Return a copy of the boilerplate `publication_details` with the human-set
    fields (report number, DOI, date) overridden. Unknown/blank overrides leave the
    scaffold line untouched; a date override is appended if no scaffold line exists.
    """
    pub = (front_matter or {}).get("publication") or {}
    if not isinstance(publication_details, dict) or not pub:
        return publication_details

    lines = list(publication_details.get("paragraphs") or [])
    for field, label in _PUBLICATION_OVERRIDES.items():
        val = (str(pub.get(field)) if pub.get(field) is not None else "").strip()
        if not val:
            continue
        new_line = f"{label}: {val}"
        for i, ln in enumerate(lines):
            if ln.split(":", 1)[0].strip() == label:
                lines[i] = new_line
                break
        else:
            lines.append(new_line)
    return {**publication_details, "paragraphs": lines}


def clean_front_matter(fm: dict) -> dict:
    """The persisted shape of a front-matter submission (the Configure UI's save, the
    CLI's --front-matter): known keys only, strings stripped, blanks dropped."""
    def _people(rows, keys):
        out = []
        for r in rows if isinstance(rows, list) else []:
            if isinstance(r, dict):
                out.append({k: str(r.get(k, "")).strip() for k in keys})
        return out

    clean = {
        "authors": _people(fm.get("authors"), ("name", "affiliation", "role")),
        "contributors": _people(fm.get("contributors"), ("name", "role")),
        "publication": {
            k: str(v).strip()
            for k, v in (fm.get("publication") or {}).items()
            if k in _PUBLICATION_OVERRIDES and str(v).strip()
        },
    }
    designation = str(fm.get("strain_designation") or "").strip()
    if designation:
        clean["strain_designation"] = designation
    return clean


def overlay_front_matter(data: dict, front_matter: dict) -> None:
    """Overlay persisted front-matter onto the render `data` in place: the Authors and
    Contributors parts (plus the cleaned roster on `data["front_matter"]`), the Publication Details overrides and the title's
    supplier strain designation. A no-op when front_matter is empty. Used by both the
    marshal and session-reload export paths so they agree."""
    if not front_matter:
        return
    designation = (front_matter.get("strain_designation") or "").strip()
    if designation:
        data["strain"] = designation
    for key, build in (("authors", build_authors), ("contributors", build_contributors)):
        value = build(front_matter)
        if value:
            data[key] = value
    data["front_matter"] = clean_front_matter(front_matter)
    if isinstance(data.get("publication_details"), dict):
        data["publication_details"] = apply_publication_overrides(
            data["publication_details"], front_matter
        )


# ---------------------------------------------------------------------------
# Front-matter workflow status (for the Sections screen)
# ---------------------------------------------------------------------------
# The workflow Sections screen lists the 7 authored/boilerplate front-matter sections
# (foreword, authors, contributors, peer_review, publication_details, acknowledgments,
# abstract)
# as display-only rows and needs their FILLED-vs-PENDING status. It must NOT run the
# full ~1.5s report render just to learn that — this resolves the same content the
# render does, but cheaply, from the two inputs that actually vary per session:
#   * authors / contributors ← front_matter.json — empty until authored;
#   * abstract     ← processing outputs — empty until the session is processed;
#   * the other four are fixed boilerplate → always present.

# The keys the Sections screen surfaces, in document order.
FRONT_MATTER_STATUS_KEYS: tuple[str, ...] = (
    "foreword", "authors", "contributors", "peer_review",
    "publication_details", "acknowledgments", "abstract",
)


def resolve_front_matter_status(
    front_matter: dict | None,
    *,
    abstract_filled: bool,
) -> dict[str, dict]:
    """Return `{data_key: {"has_content": bool, "paragraphs": int}}` for the
    front-matter sections, WITHOUT rendering the report.

    Inputs are the only two per-session variables:
      * `front_matter` — the session's `front_matter.json` (or None); gives the
        Authors and Contributors parts their rosters. Empty/None → both pending.
      * `abstract_filled` — whether processing has produced abstract content (the
        caller derives this from the presence of processed results, e.g. a background
        `abstract_background` sentence or a bmd summary). The abstract is boilerplate-
        structured but has no real text until the study is processed.

    The other four sections (foreword, peer_review, publication_details,
    acknowledgments) are fixed boilerplate present on every report, so they always
    report `has_content=True`. `paragraphs` is an indicative count for the row's
    "N paragraphs" label (the boilerplate lengths are stable).
    """
    fm = front_matter or {}
    authors = len((build_authors(fm) or {}).get("paragraphs") or [])
    contributors = len((build_contributors(fm) or {}).get("paragraphs") or [])
    # Boilerplate paragraph counts (stable scaffold lengths) for the row label; the
    # exact number is cosmetic — what matters is has_content True/False.
    return {
        "foreword": {"has_content": True, "paragraphs": 3},
        "authors": {"has_content": authors > 0, "paragraphs": authors},
        "contributors": {"has_content": contributors > 0, "paragraphs": contributors},
        "peer_review": {"has_content": True, "paragraphs": 1},
        "publication_details": {"has_content": True, "paragraphs": 6},
        "acknowledgments": {"has_content": True, "paragraphs": 1},
        "abstract": {"has_content": bool(abstract_filled),
                     "paragraphs": 4 if abstract_filled else 0},
    }
