"""Dev helper: regenerate output/DTXSID50469320-report.docx from session cache.

Mirrors how the app assembles the PFHxSAm report so we can iterate on the docx
generator against the real session data.  Not part of the shipped surface.
"""
from pathlib import Path
from rendering.latex_export import load_session_data
from rendering.docx_generator import generate_docx

DTXSID = "DTXSID50469320"
OUT = Path("output") / f"{DTXSID}-report.docx"

data = load_session_data(
    DTXSID,
    chemical_name="Perfluorohexanesulfonamide",
    casrn="41997-13-1",
)
blob = generate_docx(data)
OUT.write_bytes(blob)
print(f"wrote {OUT} ({len(blob)} bytes)")
