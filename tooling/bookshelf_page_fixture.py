"""tooling/bookshelf_page_fixture.py — keep a real NCBI Bookshelf page (saved
from a browser; the sandbox cannot reach Bookshelf) as a reference fixture for
the facsimile.

The page is trimmed to the reader content (pre-content, main-content,
post-content) and the Views / collection portlets; NCBI's site chrome, the
Recent Activity portlet and all scripts are dropped.  It is written to
tests/fixtures/reference/<REPORT>/bookshelf-pages/<page>.html, <page> being the
page's Bookshelf location (foreword1, fm-authors, a-2-C …; "toc" for the
landing page).

    python -m tooling.bookshelf_page_fixture saved-page.html [...] [--report NIEHS-10]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "reference"


def _between(text: str, start: str, end: str) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i)
    return text[i:j if j >= 0 else len(text)]


def page_info(page: str) -> dict:
    """The page's Bookshelf accession, book domain and location."""
    acc = re.search(r'name="ncbi_acc" content="([^"]+)"', page)
    domain = re.search(r'name="ncbi_domain" content="([^"]+)"', page)
    loc = re.search(r'name="bk-non-canon-loc" content="/books/n/[^/]+/([^"/]*)/?"', page)
    return {"acc": acc.group(1) if acc else "",
            "domain": domain.group(1) if domain else "",
            "page": (loc.group(1) if loc and loc.group(1) else "toc")}


def report_name(domain: str) -> str:
    """ntpniehs10 → NIEHS-10 (the published-report naming of tooling.bits_structure)."""
    m = re.fullmatch(r"ntpniehs(\d+)", domain)
    return f"NIEHS-{int(m.group(1)):02d}" if m else domain


def trim(page: str) -> str:
    """The reader content and the Views / collection portlets, scripts removed."""
    page = re.sub(r"<script\b.*?</script>", "", page, flags=re.S)
    content = (_between(page, '<div class="document">', "<!-- Custom content below content -->")
               or _between(page, '<div class="source">', "<!-- Custom content below content -->"))
    portlets = [p for p in re.findall(r'<div class="portlet">.*?(?=<div class="portlet">|<!-- Custom content below discovery)',
                                      page, flags=re.S)
                if "Recent Activity" not in p]
    return content.rstrip() + '\n<div id="rightcolumn">\n' + "".join(portlets).rstrip() + "\n</div>\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pages", nargs="+", type=Path, help="saved Bookshelf page HTML")
    ap.add_argument("--report", help="published report name (default: from the page's book)")
    ap.add_argument("--date", default="", help="the date the page was saved, for the header")
    args = ap.parse_args()
    for path in args.pages:
        page = path.read_text(encoding="utf-8")
        info = page_info(page)
        report = args.report or report_name(info["domain"])
        out = FIXTURES / report / "bookshelf-pages" / f"{info['page']}.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        when = f" as served {args.date}" if args.date else ""
        header = (f"<!-- NCBI Bookshelf page {info['acc']} ({report}, /books/n/{info['domain']}/"
                  f"{'' if info['page'] == 'toc' else info['page'] + '/'}){when}, saved from a\n"
                  "     browser.  Trimmed by tooling/bookshelf_page_fixture.py to the reader content\n"
                  "     and the Views / collection portlets.  The reference for the facsimile\n"
                  "     (rendering/bookshelf_preview.py). -->\n")
        out.write_text(header + trim(page), encoding="utf-8")
        print(f"wrote {out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
