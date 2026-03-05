"""
report_pdf.py — Build a PDF/UA-1 compliant report from approved session data.

Compiles the report.typ Typst template with the provided report data,
producing a tagged PDF with full StructTreeRoot, semantic heading hierarchy
(H1-H6), proper table structure (TH/TD), XMP metadata, and PDF/UA-1
identifier.  The output passes the Matterhorn Protocol machine-checkable
conditions for government 508 compliance.

The Typst compiler is embedded in the `typst` Python package (a pre-built
Rust binary shipped as a wheel — no Rust toolchain needed).  Compilation
is sub-second for typical report sizes.

Usage:
    from report_pdf import build_report_pdf
    pdf_bytes = build_report_pdf(report_data_dict)

    # report_data_dict matches the JSON schema consumed by report.typ:
    # {
    #   "title": str,
    #   "chemical_name": str,
    #   "background": {"paragraphs": [...], "references": [...]},
    #   "methods": {"sections": [...]},
    #   "apical_sections": [...],
    #   "bmd_summary": {"endpoints": [...]},
    #   "genomics_sections": [...],
    #   "summary": {"paragraphs": [...]},
    # }
"""

import json
from pathlib import Path

import typst


# --- Path to the Typst template ---
# Resolved relative to this file so it works regardless of cwd.
_TEMPLATE_PATH = str(Path(__file__).parent / "report.typ")


def build_report_pdf(data: dict) -> bytes:
    """
    Compile the NIEHS-styled report to PDF/UA-1.

    Serializes `data` to JSON, passes it to the Typst template via
    sys.inputs, and compiles with the ua-1 PDF standard.

    Args:
        data: Report data dictionary matching the report.typ JSON schema.
              All top-level keys are optional — missing sections are
              simply omitted from the output.

    Returns:
        The compiled PDF as raw bytes, ready to write to a file or
        return as an HTTP response.

    Raises:
        typst.TypstError: If the template fails to compile (e.g., due
            to missing alt text on figures under PDF/UA-1 strict mode).
    """
    # Ensure required metadata fields have defaults so PDF/UA-1
    # validation doesn't fail on missing title or language.
    data.setdefault("title", "5dToxReport")
    data.setdefault("author", "5dToxReport")

    pdf_bytes = typst.compile(
        _TEMPLATE_PATH,
        sys_inputs={"data": json.dumps(data, default=str)},
        # PDF/UA-1 (ISO 14289-1) — enforces:
        #   - StructTreeRoot with full tag hierarchy
        #   - /MarkInfo << /Marked true >>
        #   - PDF/UA identifier in XMP metadata
        #   - /Lang in the document catalog
        #   - Compile-time validation of heading order, alt text, etc.
        pdf_standards=["ua-1"],
    )

    return pdf_bytes


def marshal_export_data(body: dict) -> dict:
    """
    Convert the /api/export-pdf request body (same schema as /api/export-docx)
    into the report.typ JSON schema.

    The web UI sends the same payload to both endpoints for consistency.
    This function reshapes it into the structure the Typst template expects.

    Args:
        body: The request JSON body from the web UI export call.

    Returns:
        A dict ready to pass to build_report_pdf().
    """
    chemical_name = body.get("chemical_name", "Chemical")

    # Title and running header match the NIEHS format:
    # "In Vivo Repeat Dose Biological Potency Study of <chemical> in Sprague Dawley Rats"
    full_title = f"In Vivo Repeat Dose Biological Potency Study of {chemical_name} in Sprague Dawley Rats"

    data = {
        "title": full_title,
        "author": "5dToxReport",
        "running_header": full_title,
        "chemical_name": chemical_name,
        "subtitle": "",
        "casrn": body.get("casrn", ""),
        "dtxsid": body.get("dtxsid", ""),
    }

    # --- Background ---
    paragraphs = body.get("paragraphs", [])
    references = body.get("references", [])
    if paragraphs:
        data["background"] = {
            "paragraphs": paragraphs,
            "references": references,
        }

    # --- Materials and Methods ---
    # Accept either structured format (methods_data with sections array)
    # or legacy flat format (methods_paragraphs list).
    methods_data = body.get("methods_data")
    methods_paragraphs = body.get("methods_paragraphs", [])
    if methods_data and methods_data.get("sections"):
        data["methods"] = {
            "sections": methods_data["sections"],
        }
    elif methods_paragraphs:
        data["methods"] = {
            "sections": [],
            "paragraphs": methods_paragraphs,
        }

    # --- Apical endpoint sections ---
    # The web UI sends these with table data already resolved.
    apical_sections = body.get("apical_sections", [])
    if apical_sections:
        data["apical_sections"] = []
        for sec in apical_sections:
            data["apical_sections"].append({
                "title": sec.get("section_title", "Apical Endpoints"),
                "caption": sec.get("table_caption_template", ""),
                "compound": sec.get("compound_name", chemical_name),
                "dose_unit": sec.get("dose_unit", "mg/kg"),
                "narrative": _split_narrative(sec.get("narrative_paragraphs")),
                "table_data": sec.get("table_data", {}),
            })

    # --- BMD Summary ---
    bmd_endpoints = body.get("bmd_summary_endpoints", [])
    if bmd_endpoints:
        data["bmd_summary"] = {"endpoints": bmd_endpoints}

    # --- Genomics ---
    genomics = body.get("genomics_sections", [])
    if genomics:
        data["genomics_sections"] = genomics

    # --- Summary ---
    summary_paragraphs = body.get("summary_paragraphs", [])
    if summary_paragraphs:
        data["summary"] = {"paragraphs": summary_paragraphs}

    return data


def _split_narrative(narrative) -> list[str]:
    """
    Normalize narrative input to a list of paragraph strings.

    The narrative may arrive as:
      - A list of strings (one per paragraph) — return as-is
      - A single string with double-newline separators — split
      - None — return empty list
    """
    if narrative is None:
        return []
    if isinstance(narrative, list):
        return narrative
    if isinstance(narrative, str):
        return [p.strip() for p in narrative.split("\n\n") if p.strip()]
    return []
