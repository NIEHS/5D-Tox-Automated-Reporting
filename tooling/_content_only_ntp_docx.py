"""Test (stronger): content-only docx referencing the CUSTOM NTP style names.

Same idea as _content_only_docx.py, but the paragraphs reference the NTP styles
the reference report ACTUALLY uses (1-03_Report_Title, 3-02a_Head1_NoNumber,
3-03_Head2, 3-04_Head3, 0-03_Paragraph) instead of the Word built-ins.  Those
names are fully DEFINED in niehs-10-base.dotx, so attaching that template with
"automatically update document styles" restyles every paragraph to the NIEHS
look -- the built-in path could not restyle the title (built-in 'Title' is only
a latent placeholder in the reference; the report uses 1-03_Report_Title).

We add each NTP style to the fresh Document as an EMPTY paragraph style (a stub
carrying the right NAME + styleId but no formatting) so the content is well-formed
in isolation yet has nothing of its own to override the attached template.  The
content file thus carries the NAMES; the dotx carries the DEFINITIONS.

Not shipped -- a separation test harness.
"""
from pathlib import Path

from docx import Document
from docx.enum.style import WD_STYLE_TYPE

OUT = Path("output") / "content-only-ntp.docx"

# (display text, NTP style NAME, styleId).  Mirrors the reference's opening.
CONTENT = [
    ("NIEHS Report on the In Vivo Repeat Dose Biological Potency Study of "
     "Perfluorohexanesulfonamide", "1-03_Report_Title", "1-03ReportTitle"),
    ("Section-level heading", "3-02a_Head1_NoNumber", "3-02aHead1NoNumber"),
    ("Subsection heading", "3-03_Head2", "3-03Head2"),
    ("Sub-subsection heading", "3-04_Head3", "3-04Head3"),
    ("Body text in the NTP paragraph style.  Carries the NTP style NAME but no "
     "local definition -- attaching niehs-10-base.dotx supplies the look.",
     "0-03_Paragraph", "0-03Paragraph"),
]


def build() -> None:
    doc = Document()  # MS Word defaults; no NTP definitions.

    # Add each NTP style as an EMPTY stub (name + styleId, no formatting).  A
    # fresh Document has none of these names; without the stub, assigning the
    # style would raise KeyError.  The stub deliberately holds no rPr/pPr so it
    # cannot mask what the attached template defines.
    for _text, name, style_id in CONTENT:
        if name not in {s.name for s in doc.styles}:
            st = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
            # Force the styleId to the NTP form so it matches the dotx exactly
            # (python-docx would otherwise derive its own id from the name).
            st.element.set(
                "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}styleId",
                style_id,
            )

    for text, name, _sid in CONTENT:
        doc.add_paragraph(text, style=name)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(OUT))
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
    for text, name, sid in CONTENT:
        print(f"    [{name} / {sid}] {text[:50]}")


if __name__ == "__main__":
    build()
