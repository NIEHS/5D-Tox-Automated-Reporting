"""
jats_stylecheck.py — offline PMC/NLM StyleChecker gate for the JATS surface.

ADR-0004 names the PMC Style Checker as "the golden gate": emitted XML is
validated against the authoritative external validator, errors must be zero.
This module runs that validator **offline**, in-process, through the same
libxslt engine `jats_generator` already uses (`lxml.etree.XSLT`) — no network,
no `xsltproc` binary.  It is the real gate that replaces the clean-render proxy.

Two-stage transform (see assets/stylechecker/PROVENANCE.md):

  1. nlm-stylechecker.xsl  (param style=article|manuscript|book)
        input article  ->  <ERR> document (input + <error>/<warning> nodes)
  2. style-reporter.xsl
        <ERR> document  ->  human-readable HTML error/warning report

The vendored transform is v5.48; refresh per PROVENANCE.md when PMC updates it.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import lxml.etree as ET

# Vendored StyleChecker lives beside the fonts/templates under assets/.
STYLECHECKER_DIR = Path(__file__).resolve().parent.parent / "assets" / "stylechecker"
_MAIN_XSL = STYLECHECKER_DIR / "nlm-stylechecker.xsl"
_REPORTER_XSL = STYLECHECKER_DIR / "style-reporter.xsl"

# The checker announces the vocabulary/version; surfaced for provenance in logs.
STYLECHECKER_VERSION = "5.48"

# Vendored NISO JATS 1.3 Archiving DTD + its full module set (MathML, ISO char
# entities, OASIS/XHTML table models).  The StyleChecker validates TAGGING-
# GUIDELINE conformance, NOT the DTD content model — so it cannot catch a
# structural error like a <table-wrap> emitted after a <sec> (the JATS body model
# is (block)*, sec*).  The PMC Article Previewer DOES a real DTD parse and
# rejects that.  dtd_validate() reproduces that parse offline so the same class
# of error is caught locally.  The entry DTD's relative module refs resolve
# against this dir, so validation runs with the CWD pinned here.
JATS_DTD_DIR = Path(__file__).resolve().parent.parent / "assets" / "jats-dtd"
_JATS_DTD = JATS_DTD_DIR / "JATS-archivearticle1-3.dtd"

# Vendored BITS 2.0 Book Interchange DTD + its module set (BITS reuses the JATS
# 1.x modules, plus its own BITS-book*/BITS-bookmeta* modules and the MathML/ISO
# char-entity subtrees shared with the JATS set).  The reports are published as
# BITS <book>s (NBK589955 = NIEHS Report 10), so the book export validates
# against this.  Same offline parse as the JATS DTD, different root grammar.
BITS_DTD_DIR = Path(__file__).resolve().parent.parent / "assets" / "bits-dtd"
_BITS_DTD = BITS_DTD_DIR / "BITS-book2.dtd"

# The two vocabularies dtd_validate() can check against: the grammar dir + the
# entry DTD filename its relative module refs resolve against.
_DTD_GRAMMARS = {
    "article": (JATS_DTD_DIR, _JATS_DTD),
    "book": (BITS_DTD_DIR, _BITS_DTD),
}


@dataclass(frozen=True)
class StyleCheckResult:
    """Outcome of one StyleChecker run over a JATS document."""

    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    err_tree: ET._ElementTree  # the raw <ERR> document (stage-1 output)

    @property
    def ok(self) -> bool:
        """PMC's contract: a submission passes when it has zero errors."""
        return not self.errors

    def html_report(self) -> str:
        """Render the stage-2 HTML error/warning report (style-reporter.xsl)."""
        reporter = _load_reporter()
        return str(reporter(self.err_tree))


@lru_cache(maxsize=1)
def _load_checker() -> ET.XSLT:
    # Parsing from the real path lets libxslt resolve the three xsl:include
    # helpers relative to the stylesheet — they must sit in the same dir.
    if not _MAIN_XSL.exists():  # vendored asset missing -> actionable message
        raise FileNotFoundError(
            f"StyleChecker transform not found at {_MAIN_XSL}. "
            "It is vendored under assets/stylechecker/ (see PROVENANCE.md); "
            "the sandbox firewall blocks PMC, so fetch it on the host."
        )
    return ET.XSLT(ET.parse(str(_MAIN_XSL)))


@lru_cache(maxsize=1)
def _load_reporter() -> ET.XSLT:
    return ET.XSLT(ET.parse(str(_REPORTER_XSL)))


def _message(node: ET._Element) -> str:
    """Flatten an <error>/<warning> to a normalized single-line message.

    The checker nests a <tlink>(Tagging Guidelines)</tlink> link and sometimes a
    trailing "(context: <xpath> )" into the element; both are stripped so the
    message is a stable signature for baseline comparison.
    """
    text = " ".join("".join(node.itertext()).split())
    for noise in ("(Tagging Guidelines)",):
        text = text.replace(noise, "")
    # Drop a trailing "(context: ...)" — the xpath is position-dependent noise.
    if "(context:" in text:
        text = text[: text.index("(context:")]
    return text.strip()


def stylecheck(xml: str | bytes, style: str = "article") -> StyleCheckResult:
    """Run the NLM StyleChecker over a JATS/BITS document.

    `style` selects the ruleset (article | manuscript | book); the checker also
    auto-sniffs `book` from a <book-part>/<book> root, but we pass it explicitly.
    """
    doc = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    checker = _load_checker()
    err_doc = checker(doc, style=ET.XSLT.strparam(style))
    root = err_doc.getroot()
    errors = tuple(_message(e) for e in root.findall(".//error"))
    warnings = tuple(_message(w) for w in root.findall(".//warning"))
    return StyleCheckResult(errors=errors, warnings=warnings, err_tree=err_doc)


def dtd_validate(xml: str | bytes, grammar: str = "article") -> tuple[str, ...]:
    """Validate a document against a vendored NISO DTD and return the content-
    model errors (empty tuple = valid).

    `grammar` selects the vocabulary: "article" → NISO JATS 1.3 Archiving (a
    journal <article>), "book" → BITS 2.0 Book Interchange (a <book>).  This is
    the check the PMC/Bookshelf pipeline runs and the StyleChecker does NOT: the
    DTD content model (e.g. <body> is (block)*, sec* — a <table-wrap> after a
    <sec> is invalid).  The parse resolves the DTD's relative module entities
    against the grammar's dir, so we pin CWD there for the duration (lxml
    resolves a relative SYSTEM id against the current directory).  Deduplicated,
    first-seen order; only genuine validity errors are returned (a missing module
    file would surface here too, signalling the vendored set is incomplete)."""
    import os

    try:
        dtd_dir, entry = _DTD_GRAMMARS[grammar]
    except KeyError:
        raise ValueError(f"unknown DTD grammar {grammar!r}; use 'article' or 'book'")
    if not entry.exists():
        raise FileNotFoundError(
            f"{grammar} DTD not found at {entry}. The module set is vendored under "
            f"{dtd_dir.relative_to(entry.parents[2])}/ (fetched from "
            "jats.nlm.nih.gov)."
        )
    data = xml.encode("utf-8") if isinstance(xml, str) else xml
    parser = ET.XMLParser(
        load_dtd=True, dtd_validation=True, no_network=True, resolve_entities=True,
    )
    cwd = os.getcwd()
    os.chdir(dtd_dir)
    try:
        try:
            ET.fromstring(data, parser)
        except ET.XMLSyntaxError:
            pass  # errors captured in parser.error_log below
        seen: dict[str, None] = {}
        for e in parser.error_log:
            msg = " ".join(e.message.split())
            seen.setdefault(f"L{e.line}: {msg}", None)
        return tuple(seen)
    finally:
        os.chdir(cwd)
