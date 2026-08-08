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
STYLECHECKER_DIR = Path(__file__).resolve().parent / "assets" / "stylechecker"
_MAIN_XSL = STYLECHECKER_DIR / "nlm-stylechecker.xsl"
_REPORTER_XSL = STYLECHECKER_DIR / "style-reporter.xsl"

# The checker announces the vocabulary/version; surfaced for provenance in logs.
STYLECHECKER_VERSION = "5.48"


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
