"""Dev helper: derive a genuine .dotx TEMPLATE from the content-stripped base docx.

A .dotx is byte-for-byte a .docx EXCEPT the main document part's content-type
override, which is the template variant.  Word keys off this single override to
treat the file as a template (open -> spawn an untitled copy) rather than a
document.  The package-root relationship (`officeDocument`) is IDENTICAL for both
-- only [Content_Types].xml changes.

So this copies every part of assets/templates/niehs-10-base.docx VERBATIM and
rewrites exactly one string in [Content_Types].xml:
    /word/document.xml : ...wordprocessingml.document.main+xml
                      -> ...wordprocessingml.template.main+xml

Reproducible + reviewable: re-run to regenerate from the base.  Not shipped.
"""
from pathlib import Path
import zipfile

SRC = Path("assets/templates/niehs-10-base.docx")
OUT = Path("assets/templates/niehs-10-base.dotx")

DOC_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
TPL_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml"

# The exact override we rewrite -- pinned to /word/document.xml so we never flip
# some other part that happens to carry the document content-type string.
DOC_OVERRIDE = f'<Override PartName="/word/document.xml" ContentType="{DOC_CT}"/>'
TPL_OVERRIDE = f'<Override PartName="/word/document.xml" ContentType="{TPL_CT}"/>'


def derive() -> None:
    if not SRC.exists():
        raise SystemExit(f"missing base: {SRC} (run _build_docx_base.py first)")

    zin = zipfile.ZipFile(SRC, "r")
    ct = zin.read("[Content_Types].xml").decode("utf-8")
    if DOC_OVERRIDE not in ct:
        raise SystemExit(
            "expected /word/document.xml document-override not found in "
            "[Content_Types].xml -- base layout changed; inspect before rewriting."
        )
    ct_new = ct.replace(DOC_OVERRIDE, TPL_OVERRIDE)
    assert ct_new.count(TPL_CT) == 1, "template override did not apply exactly once"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "[Content_Types].xml":
                data = ct_new.encode("utf-8")
            # Preserve each entry's own compression type; rewritten part rezips.
            zout.writestr(item, data)
    zin.close()

    size = OUT.stat().st_size
    print(f"wrote {OUT} ({size} bytes) -- {SRC.name} with template content-type")


if __name__ == "__main__":
    derive()
