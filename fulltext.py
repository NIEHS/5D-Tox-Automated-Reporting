"""
Full text retrieval for the extraction pipeline.

Fetches full paper text from multiple open-access and proxy-based sources,
in priority order (cheapest/fastest first):

1. PMC — Europe PMC REST API (free, XML)
2. arXiv — ar5iv HTML mirror (free, HTML)
3. S2 openAccessPdf — direct PDF URL from Semantic Scholar
4. Unpaywall — free OA discovery API (requires email)
5. DOI resolver + proxy — institutional proxy for paywalled content

Caches fetched texts to disk to avoid re-fetching.
"""

import json
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

# PDF extraction via the from-scratch parser (no external deps).
# Always available — no optional dependency dance needed.
from pdf_text import parse_pdf_bytes, chunks_to_text
HAS_PDF = True


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FullTextResult:
    paper_id: str
    source: str           # "pmc", "arxiv", "s2_oa", "unpaywall", "doi_proxy"
    text: str             # plain text (not HTML/XML)
    char_count: int = 0
    truncated: bool = False
    raw_kind: str = ""    # "pdf" | "html" | "xml" — kind of the stored raw artifact
    resolved_url: str = ""  # the URL the artifact actually came from (post-redirect)

    def __post_init__(self):
        if not self.char_count:
            self.char_count = len(self.text)


@dataclass
class _Fetched:
    """Internal: what a source fetcher returns — extracted text plus the raw
    artifact bytes and the URL they came from, so the raw file can be cached."""
    text: str
    raw_bytes: Optional[bytes]
    raw_kind: str          # "pdf" | "html" | "xml"
    resolved_url: str


# ---------------------------------------------------------------------------
# Text cleaning utilities
# ---------------------------------------------------------------------------

_REFERENCE_PATTERNS = [
    re.compile(r'\n\s*References\s*\n.*', re.DOTALL | re.IGNORECASE),
    re.compile(r'\n\s*Bibliography\s*\n.*', re.DOTALL | re.IGNORECASE),
    re.compile(r'\n\s*Literature Cited\s*\n.*', re.DOTALL | re.IGNORECASE),
]


def _clean_text(text: str, max_chars: int = 500_000) -> tuple[str, bool]:
    """Strip tags, normalize whitespace, remove references, truncate."""
    # Strip any remaining XML/HTML tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Normalize whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()

    # Remove references/bibliography sections (noise for extraction)
    for pattern in _REFERENCE_PATTERNS:
        text = pattern.sub('', text)

    text = text.strip()

    truncated = False
    if len(text) > max_chars:
        text = text[:max_chars]
        truncated = True

    return text, truncated


def _extract_text_from_xml(xml_str: str) -> str:
    """Extract body text from PMC-style XML."""
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        return ""

    # PMC full text XML: body is in <body> element
    body = root.find('.//body')
    if body is None:
        # Try to get all text as fallback
        return ET.tostring(root, encoding='unicode', method='text')

    return ET.tostring(body, encoding='unicode', method='text')


def _extract_text_from_html(html: str) -> str:
    """Simple HTML-to-text extraction (no external dependencies)."""
    # Remove script and style blocks
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # Convert block elements to newlines
    html = re.sub(r'<(?:p|div|br|h[1-6]|li|tr)[^>]*>', '\n', html, flags=re.IGNORECASE)
    # Strip all remaining tags
    text = re.sub(r'<[^>]+>', ' ', html)
    # Decode common HTML entities
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&nbsp;', ' ').replace('&#39;', "'").replace('&quot;', '"')
    return text


def _extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes using the from-scratch parser.

    Uses parse_pdf_bytes() to extract semantically-classified text chunks,
    then joins them into plain text via chunks_to_text(). Table detection
    is disabled since we only need raw text for full-text search.

    Returns empty string on any error (e.g., encrypted/image-only PDFs).
    """
    try:
        chunks = parse_pdf_bytes(pdf_bytes, detect_tables=False)
        return chunks_to_text(chunks)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# FullTextFetcher
# ---------------------------------------------------------------------------

class FullTextFetcher:
    """
    Fetches full text from multiple sources in priority order.
    Caches results to disk.
    """

    def __init__(
        self,
        email: str = "user@example.com",
        proxy_url: str | None = None,
        max_chars: int = 500_000,
        cache_dir: str = ".fulltext_cache",
        rate_limit: float = 1.0,
    ):
        self.email = email
        self.proxy_url = proxy_url
        self.max_chars = max_chars
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.rate_limit = rate_limit
        self.session = requests.Session()
        self.session.headers["User-Agent"] = (
            "FullTextFetcher/1.0 (literature mining; mailto:{})".format(email)
        )

        self.stats = {
            "cache_hits": 0,
            "pmc": 0,
            "arxiv": 0,
            "s2_oa": 0,
            "unpaywall": 0,
            "doi": 0,
            "failed": 0,
        }

    # -------------------------------------------------------------------
    # Cache
    # -------------------------------------------------------------------

    @staticmethod
    def _safe(paper_id: str) -> str:
        return re.sub(r'[^\w\-]', '_', paper_id)

    def _cache_key(self, paper_id: str) -> Path:
        return self.cache_dir / f"{self._safe(paper_id)}.txt"

    def _cache_meta_key(self, paper_id: str) -> Path:
        return self.cache_dir / f"{self._safe(paper_id)}.meta.json"

    def _raw_path(self, paper_id: str, kind: str) -> Path:
        ext = {"pdf": "pdf", "html": "html", "xml": "xml"}.get(kind, "bin")
        return self.cache_dir / f"{self._safe(paper_id)}.{ext}"

    def _get_cached(self, paper_id: str) -> FullTextResult | None:
        txt_path = self._cache_key(paper_id)
        meta_path = self._cache_meta_key(paper_id)
        if txt_path.exists() and meta_path.exists():
            text = txt_path.read_text(encoding="utf-8")
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            return FullTextResult(
                paper_id=paper_id,
                source=meta.get("source", "cache"),
                text=text,
                char_count=len(text),
                truncated=meta.get("truncated", False),
                raw_kind=meta.get("raw_kind", ""),
                resolved_url=meta.get("resolved_url", ""),
            )
        return None

    def _put_cache(self, result: FullTextResult, raw_bytes: Optional[bytes] = None):
        txt_path = self._cache_key(result.paper_id)
        meta_path = self._cache_meta_key(result.paper_id)
        txt_path.write_text(result.text, encoding="utf-8")
        raw_rel = ""
        if raw_bytes and result.raw_kind:
            raw_path = self._raw_path(result.paper_id, result.raw_kind)
            raw_path.write_bytes(raw_bytes)
            raw_rel = raw_path.name
        meta_path.write_text(json.dumps({
            "source": result.source,
            "char_count": result.char_count,
            "truncated": result.truncated,
            "raw_kind": result.raw_kind,
            "raw_file": raw_rel,
            "resolved_url": result.resolved_url,
        }), encoding="utf-8")

    # -------------------------------------------------------------------
    # Source fetchers
    # -------------------------------------------------------------------

    def _bytes_to_fetched(self, r, min_pdf: int = 200,
                          min_html: int = 500) -> _Fetched | None:
        """Classify an HTTP response body as PDF or HTML, extract text, and
        return it together with the raw bytes + resolved (post-redirect) URL."""
        resolved = str(r.url)
        ctype = r.headers.get("Content-Type", "").lower()
        is_pdf = "pdf" in ctype or r.content[:1024].find(b'%PDF') != -1
        if is_pdf:
            if not HAS_PDF:
                return None
            text = _extract_text_from_pdf(r.content)
            if text and len(text.strip()) > min_pdf:
                return _Fetched(text, r.content, "pdf", resolved)
            return None
        # treat as HTML
        text = _extract_text_from_html(r.text)
        if text and len(text.strip()) > min_html:
            return _Fetched(text, r.content, "html", resolved)
        return None

    def _fetch_pmc(self, pmcid: str) -> _Fetched | None:
        """Fetch full text XML from Europe PMC."""
        if not pmcid.startswith("PMC"):
            pmcid = f"PMC{pmcid}"
        url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
        try:
            time.sleep(self.rate_limit)
            r = self.session.get(url, timeout=30)
            if r.status_code != 200:
                return None
            text = _extract_text_from_xml(r.text)
            if text and len(text.strip()) > 200:
                return _Fetched(text, r.content, "xml", str(r.url))
        except requests.RequestException:
            pass
        return None

    def _fetch_arxiv(self, arxiv_id: str) -> _Fetched | None:
        """Fetch HTML from ar5iv mirror and extract text."""
        url = f"https://ar5iv.labs.arxiv.org/html/{arxiv_id}"
        try:
            time.sleep(self.rate_limit)
            r = self.session.get(url, timeout=60)
            if r.status_code != 200:
                return None
            text = _extract_text_from_html(r.text)
            if text and len(text.strip()) > 500:
                return _Fetched(text, r.content, "html", str(r.url))
        except requests.RequestException:
            pass
        return None

    def _fetch_s2_oa(self, pdf_url: str) -> _Fetched | None:
        """Fetch the S2 openAccessPdf URL (PDF or HTML) and extract text."""
        try:
            time.sleep(self.rate_limit)
            r = self.session.get(pdf_url, timeout=60, allow_redirects=True)
            if r.status_code != 200:
                return None
            return self._bytes_to_fetched(r)
        except requests.RequestException:
            pass
        return None

    def _fetch_unpaywall(self, doi: str) -> _Fetched | None:
        """Find OA copy via Unpaywall API, then fetch the PDF or landing page."""
        url = f"https://api.unpaywall.org/v2/{doi}"
        try:
            time.sleep(self.rate_limit)
            r = self.session.get(url, params={"email": self.email}, timeout=30)
            if r.status_code != 200:
                return None
            data = r.json()
            best = data.get("best_oa_location") or {}
            pdf_url = best.get("url_for_pdf")
            landing_url = best.get("url_for_landing_page")

            for target in (pdf_url, landing_url):
                if not target:
                    continue
                try:
                    time.sleep(self.rate_limit)
                    rr = self.session.get(target, timeout=60, allow_redirects=True)
                    if rr.status_code != 200:
                        continue
                    got = self._bytes_to_fetched(rr)
                    if got:
                        return got
                except requests.RequestException:
                    continue
        except (requests.RequestException, ValueError, KeyError):
            pass
        return None

    def _fetch_doi(self, doi: str) -> _Fetched | None:
        """Resolve the DOI (following redirects to the publisher) and fetch.

        Uses the institutional proxy when configured, else a direct request —
        inside NIH the direct path already carries institutional access.
        """
        doi_url = f"https://doi.org/{doi}"
        proxies = ({"http": self.proxy_url, "https": self.proxy_url}
                   if self.proxy_url else None)
        try:
            time.sleep(self.rate_limit)
            r = self.session.get(doi_url, proxies=proxies, timeout=60,
                                 allow_redirects=True)
            if r.status_code != 200:
                return None
            return self._bytes_to_fetched(r)
        except requests.RequestException:
            pass
        return None

    # -------------------------------------------------------------------
    # Main fetch logic
    # -------------------------------------------------------------------

    def fetch(self, paper: dict) -> FullTextResult | None:
        """Try all sources in priority order, return first success."""
        paper_id = paper.get("paper_id", "")
        if not paper_id:
            return None

        # Check cache first
        cached = self._get_cached(paper_id)
        if cached:
            self.stats["cache_hits"] += 1
            return cached

        pmcid = paper.get("pmcid")
        arxiv_id = paper.get("arxiv_id")
        oa_pdf = paper.get("open_access_pdf")
        doi = paper.get("doi")

        # Try sources in priority order. PMC (structured XML) and arXiv first,
        # then the direct OA PDF, then Unpaywall discovery, then the DOI resolver
        # (follows redirects to the publisher — inside NIH this reaches paywalled
        # content). Each returns a _Fetched carrying raw bytes + resolved URL.
        sources = []
        if pmcid:
            sources.append(("pmc", lambda: self._fetch_pmc(pmcid)))
        if arxiv_id:
            sources.append(("arxiv", lambda: self._fetch_arxiv(arxiv_id)))
        if oa_pdf:
            sources.append(("s2_oa", lambda: self._fetch_s2_oa(oa_pdf)))
        if doi:
            sources.append(("unpaywall", lambda: self._fetch_unpaywall(doi)))
            sources.append(("doi", lambda: self._fetch_doi(doi)))

        for source_name, fetch_fn in sources:
            try:
                got = fetch_fn()
            except Exception:
                continue

            if got and got.text:
                text, truncated = _clean_text(got.text, self.max_chars)
                if len(text.strip()) > 200:
                    result = FullTextResult(
                        paper_id=paper_id,
                        source=source_name,
                        text=text,
                        char_count=len(text),
                        truncated=truncated,
                        raw_kind=got.raw_kind,
                        resolved_url=got.resolved_url,
                    )
                    self._put_cache(result, raw_bytes=got.raw_bytes)
                    self.stats[source_name] += 1
                    return result

        self.stats["failed"] += 1
        return None

    def fetch_batch(
        self,
        papers: list[dict],
        max_workers: int = 4,
    ) -> dict[str, FullTextResult]:
        """Fetch full text for a batch of papers in parallel."""
        results: dict[str, FullTextResult] = {}
        total = len(papers)

        def _fetch_one(paper: dict, index: int) -> tuple[str, FullTextResult | None]:
            pid = paper.get("paper_id", "")
            result = self.fetch(paper)
            status = f"[{result.source}] {result.char_count:,} chars" if result else "MISS"
            title = paper.get("title", "")[:60]
            print(f"  [{index}/{total}] {title}... {status}")
            return pid, result

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(_fetch_one, paper, i + 1): paper
                for i, paper in enumerate(papers)
            }
            for future in as_completed(futures):
                pid, result = future.result()
                if result:
                    results[pid] = result

        return results

    def print_stats(self):
        """Print fetching statistics."""
        total = sum(v for k, v in self.stats.items() if k != "failed")
        print(f"\nFull text fetch stats:")
        print(f"  Total fetched: {total}")
        for source in ["cache_hits", "pmc", "arxiv", "s2_oa", "unpaywall", "doi"]:
            count = self.stats[source]
            if count:
                print(f"  {source}: {count}")
        print(f"  Failed/unavailable: {self.stats['failed']}")


# ---------------------------------------------------------------------------
# Backfill utility for existing papers.json
# ---------------------------------------------------------------------------

def backfill_metadata(
    papers_json_path: str,
    s2_api_key: str | None = None,
    rate_limit: float = 1.5,
):
    """
    Re-fetch S2 metadata for papers missing pmid/pmcid/open_access_pdf.

    Loads papers from JSON, fetches missing fields from S2 API,
    updates and re-saves the JSON. Rate-limited.
    """
    from citegraph import S2Client

    path = Path(papers_json_path)
    with open(path) as f:
        papers = json.load(f)

    client = S2Client(api_key=s2_api_key, delay=rate_limit)
    updated = 0
    skipped = 0

    for i, paper in enumerate(papers):
        # Skip papers that already have the fields
        if paper.get("pmid") and paper.get("pmcid") and paper.get("open_access_pdf"):
            skipped += 1
            continue

        pid = paper.get("paper_id", "")
        if not pid:
            continue

        data = client.get_paper(pid)
        if not data:
            continue

        ext = data.get("externalIds") or {}
        oa = (data.get("openAccessPdf") or {}).get("url")

        changed = False
        if not paper.get("pmid") and ext.get("PubMed"):
            paper["pmid"] = ext["PubMed"]
            changed = True
        if not paper.get("pmcid") and ext.get("PubMedCentral"):
            paper["pmcid"] = ext["PubMedCentral"]
            changed = True
        if not paper.get("open_access_pdf") and oa:
            paper["open_access_pdf"] = oa
            changed = True

        if changed:
            updated += 1

        if (i + 1) % 50 == 0:
            print(f"  Backfill progress: {i+1}/{len(papers)} "
                  f"(updated: {updated}, skipped: {skipped})")

    # Save back
    with open(path, "w") as f:
        json.dump(papers, f, indent=2, default=str)

    print(f"\nBackfill complete: {updated} updated, {skipped} already had fields, "
          f"{len(papers) - updated - skipped} no new data")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python fulltext.py <papers.json>              — fetch full texts")
        print("  python fulltext.py catalog <catalog.json>     — fetch full text for whole catalog")
        print("  python fulltext.py backfill <papers.json>     — backfill S2 metadata")
        print()
        print("Options:")
        print("  --email EMAIL       Unpaywall email (default: user@example.com)")
        print("  --proxy URL         Institutional proxy URL")
        print("  --max-workers N     Parallel fetch workers (default: 4)")
        print("  --s2-key KEY        Semantic Scholar API key (for backfill)")
        print("  --limit N           Only process first N papers (debug)")
        sys.exit(1)

    # Parse args
    args = sys.argv[1:]
    email = "user@example.com"
    proxy = None
    max_workers = 4
    s2_key = None

    i = 0
    positional = []
    limit = None
    while i < len(args):
        if args[i] == "--email" and i + 1 < len(args):
            email = args[i + 1]
            i += 2
        elif args[i] == "--proxy" and i + 1 < len(args):
            proxy = args[i + 1]
            i += 2
        elif args[i] == "--max-workers" and i + 1 < len(args):
            max_workers = int(args[i + 1])
            i += 2
        elif args[i] == "--s2-key" and i + 1 < len(args):
            s2_key = args[i + 1]
            i += 2
        elif args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        else:
            positional.append(args[i])
            i += 1

    if positional and positional[0] == "backfill":
        if len(positional) < 2:
            print("Usage: python fulltext.py backfill <papers.json>")
            sys.exit(1)
        backfill_metadata(positional[1], s2_api_key=s2_key, rate_limit=1.5)
    elif positional and positional[0] == "catalog":
        catalog_file = positional[1] if len(positional) > 1 else "catalog.json"
        catalog = json.load(open(catalog_file))
        # catalog is {guid: record}; record already carries paper_id/pmcid/
        # arxiv_id/open_access_pdf/doi under the same names fetch_batch expects.
        papers = list(catalog.values())
        if limit:
            papers = papers[:limit]
        print(f"Fetching full text + raw artifacts for {len(papers)} papers "
              f"from {catalog_file}...")
        fetcher = FullTextFetcher(email=email, proxy_url=proxy)
        results = fetcher.fetch_batch(papers, max_workers=max_workers)
        fetcher.print_stats()
        print(f"\nFull text available for {len(results)}/{len(papers)} papers "
              f"({100*len(results)/max(len(papers),1):.1f}%)")
    else:
        papers_file = positional[0] if positional else "citegraph_output/papers.json"
        with open(papers_file) as f:
            papers = json.load(f)

        print(f"Fetching full text for {len(papers)} papers...")
        fetcher = FullTextFetcher(
            email=email,
            proxy_url=proxy,
        )
        results = fetcher.fetch_batch(papers, max_workers=max_workers)
        fetcher.print_stats()

        print(f"\nFull text available for {len(results)}/{len(papers)} papers "
              f"({100*len(results)/max(len(papers),1):.1f}%)")
