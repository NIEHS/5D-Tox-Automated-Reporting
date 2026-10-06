#!/usr/bin/env python3
"""tooling/bookshelf_harvest.py — mirror the published NIEHS 5-day reports
(RR-8, NIEHS-02 … NIEHS-13) from NCBI Bookshelf as a reference set.

RUN THIS ON THE HOST.  From the sandbox every Bookshelf page (and E-utilities
for db=books) answers with Google's reCAPTCHA "Checking your browser" page.
Standard library only, so any python3 (>= 3.8) runs it from the repo root:

    python3 tooling/bookshelf_harvest.py                 # discover + fetch all
    python3 tooling/bookshelf_harvest.py --plan-only     # inventory, no page fetches
    python3 tooling/bookshelf_harvest.py --book NBK589955 --book niehs_13

How it works
------------
1. Discovery (E-utilities, db=books): search the series title phrase, keep the
   records whose rtype is "book", and name each report from its title
   ("NIEHS Report 13" → NIEHS-13, "Research Report 8" → RR-8).  `--book`
   seeds by NBK accession or Bookshelf book id instead.
2. Inventory: `<book id>[book]` lists every record of a book — the book, each
   part (front matter, chapters, appendices: each its own NBK), every section,
   table and figure.  A record's `id` path names its object:
   `niehs_13/bp3/table/t-2-20/PMC` is table t-2-20 of part NBK621727.
3. Fetch, into <out>/<REPORT>/ (default out: assets/cebs/_bookshelf):
     records.json            the E-utilities summaries (the catalogue)
     Bookshelf_<NBK>.pdf     the whole-report PDF, when Bookshelf offers one
     parts/<NBK>.html        each part page (book TOC page included)
     table/<NBK>_<id>.html   each table, ?report=objectonly (the full table)
     figure/<NBK>_<id>.html  each figure page, likewise (found from the part pages'
                             links — E-utilities lists no figure records)
     bin/<NBK>_<file>        every image a fetched page shows (/books/NBK…/bin/…)
     index.json              record → file, per-URL status
     CATALOGUE.md            parts → sections, tables, figures, with files
   Files already on disk are skipped, so an interrupted run resumes.

It stops (exit 2) on a reCAPTCHA page rather than saving it as content.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = "https://www.ncbi.nlm.nih.gov"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
DEFAULT_TERM = '"In Vivo Repeat Dose Biological Potency"'
# Record kinds whose id path is <book>/<part>/<kind>/<object id>/PMC and that
# Bookshelf serves as a stand-alone object page.
OBJECT_KINDS = ("table", "figure", "box")
_OBJ = re.compile(r'href="(?:https://www\.ncbi\.nlm\.nih\.gov)?/books/(NBK\d+)/(table|figure|box)/([^/"?#]+)/?')
_IMG = re.compile(r'(?:src|href)="((?:https://www\.ncbi\.nlm\.nih\.gov)?/books/(NBK\d+)/bin/([^"?#]+))"')


class Gated(RuntimeError):
    """NCBI answered with its reCAPTCHA interstitial instead of content."""


def is_gated(body: bytes) -> bool:
    head = body[:4000].lower()
    return b"recaptcha/challengepage" in head or b"checking your browser" in head


class Client:
    def __init__(self, delay: float, user_agent: str, api_key: str | None, email: str | None):
        self.delay, self.ua, self.api_key, self.email = delay, user_agent, api_key, email
        self._last = 0.0

    def get(self, url: str, data: dict | None = None, gate_check: bool = True) -> tuple[int, bytes]:
        """(status, body); retries 429/5xx; raises Gated on the reCAPTCHA page."""
        body_data = urllib.parse.urlencode(data).encode() if data is not None else None
        for attempt in range(4):
            wait = self.delay - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            req = urllib.request.Request(url, data=body_data, headers={"User-Agent": self.ua})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    status, body = r.status, r.read()
            except urllib.error.HTTPError as e:
                status, body = e.code, e.read()
            except (urllib.error.URLError, TimeoutError) as e:
                status, body = 0, str(e).encode()
            if status in (0, 429) or status >= 500:
                time.sleep(2 ** attempt * 2)
                continue
            break
        if gate_check and is_gated(body):
            raise Gated(url)
        return status, body

    def eutils(self, tool: str, params: dict) -> dict:
        p = dict(params, db="books", retmode="json")
        if self.api_key:
            p["api_key"] = self.api_key
        if self.email:
            p["email"], p["tool"] = self.email, "rlm-bmdx-bookshelf-harvest"
        status, body = self.get(f"{EUTILS}/{tool}.fcgi", data=p)
        if status != 200:
            raise RuntimeError(f"E-utilities {tool} HTTP {status}: {body[:300]!r}")
        return json.loads(body)

    def search(self, term: str) -> list[str]:
        return self.eutils("esearch", {"term": term, "retmax": 10000})["esearchresult"].get("idlist", [])

    def summaries(self, uids: list[str]) -> list[dict]:
        out = []
        for i in range(0, len(uids), 200):
            res = self.eutils("esummary", {"id": ",".join(uids[i:i + 200])})["result"]
            out += [res[u] for u in res.get("uids", [])]
        return out


# ── pure helpers (unit-tested offline) ────────────────────────────────────────

def book_id(record: dict) -> str:
    """Bookshelf book id of a record: 'niehs_13/bp3/table/t-2-20/PMC' → 'niehs_13'."""
    return record["id"].split("/")[0]


def report_name(title: str, fallback: str) -> str:
    """'… NIEHS Report 13' → 'NIEHS-13'; '… Research Report 8' → 'RR-8'."""
    m = re.search(r"NIEHS Report\s+(\d+)", title)
    if m:
        return f"NIEHS-{int(m.group(1)):02d}"
    m = re.search(r"Research Report\s+(\d+)", title)
    if m:
        return f"RR-{int(m.group(1))}"
    return fallback


def object_ref(record: dict) -> tuple[str, str] | None:
    """(kind, object id) for a table/figure/box record, else None."""
    parts = record["id"].split("/")
    if len(parts) >= 4 and parts[-3] in OBJECT_KINDS:
        return parts[-3], parts[-2]
    return None


def plan(records: list[dict]) -> list[dict]:
    """Every URL to fetch for one book's records, with its relative file path."""
    jobs, seen = [], set()

    def add(url, path, kind, optional=False):
        if url not in seen:
            seen.add(url)
            jobs.append({"url": url, "path": path, "kind": kind, "optional": optional})

    for r in records:
        if r.get("rtype") == "book":
            acc = r["accessionid"]
            add(f"{BASE}/books/{acc}/pdf/Bookshelf_{acc}.pdf", f"Bookshelf_{acc}.pdf", "pdf", optional=True)
    for r in sorted(records, key=lambda r: (r["accessionid"], r["id"])):
        acc = r["accessionid"]
        add(f"{BASE}/books/{acc}/", f"parts/{acc}.html", "part")
        ref = object_ref(r)
        if ref:
            kind, oid = ref
            add(f"{BASE}/books/{acc}/{kind}/{oid}/?report=objectonly", f"{kind}/{acc}_{oid}.html", kind)
    return jobs


def images(html: bytes) -> list[tuple[str, str]]:
    """(absolute URL, file name) for every Bookshelf image a page references."""
    out = {}
    for src, acc, name in _IMG.findall(html.decode("utf-8", "replace")):
        url = src if src.startswith("http") else BASE + src
        out[url] = f"bin/{acc}_{name.replace('/', '_')}"
    return sorted(out.items())


def object_links(html: bytes) -> list[dict]:
    """Table/figure/box pages a fetched page links to — figures in particular,
    which E-utilities does not list as records."""
    out = {}
    for acc, kind, oid in _OBJ.findall(html.decode("utf-8", "replace")):
        url = f"{BASE}/books/{acc}/{kind}/{oid}/?report=objectonly"
        out[url] = {"url": url, "path": f"{kind}/{acc}_{oid}.html", "kind": kind, "optional": False}
    return [out[u] for u in sorted(out)]


def record_file(record: dict) -> str:
    ref = object_ref(record)
    return f"{ref[0]}/{record['accessionid']}_{ref[1]}.html" if ref else f"parts/{record['accessionid']}.html"


def catalogue(report: str, records: list[dict]) -> str:
    """Markdown outline: each part, then its sections, tables and figures."""
    book = next((r for r in records if r.get("rtype") == "book"), None)
    lines = [f"# {report}: {book['title'] if book else ''}".rstrip(), ""]
    if book:
        lines += [f"Book {book['accessionid']} (`{book_id(book)}`), published {book.get('pubdate', '')[:10]}", ""]
    by_part: dict[str, list[dict]] = {}
    for r in records:
        if r.get("rtype") != "book":
            by_part.setdefault(r["accessionid"], []).append(r)

    def natural(r):
        return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", r["id"])]

    for acc, recs in sorted(by_part.items()):
        heads = [r for r in recs if r["id"].count("/") == 3 and r.get("rtype") in ("sec", "appendix", "chapter")]
        head = heads[0] if heads else recs[0]
        lines.append(f"## {head['title']}  ({acc}, `parts/{acc}.html`)")
        for r in sorted(recs, key=natural):
            if r is head:
                continue
            ref = object_ref(r)
            lines.append(f"- {r['rtype']}: {r['title']}" + (f"  `{record_file(r)}`" if ref else ""))
        lines.append("")
    return "\n".join(lines)


# ── harvest ──────────────────────────────────────────────────────────────────

def discover(client: Client, term: str, seeds: list[str]) -> dict[str, list[dict]]:
    """{book id: records}.  Seeds are NBK accessions or book ids."""
    ids: set[str] = set()
    if seeds:
        for s in seeds:
            if re.fullmatch(r"NBK\d+", s):
                recs = client.summaries(client.search(f"{s}[accn]") or client.search(s))
                ids |= {book_id(r) for r in recs if r.get("accessionid") == s} or {book_id(r) for r in recs}
            else:
                ids.add(s)
    else:
        recs = client.summaries(client.search(term))
        ids = {book_id(r) for r in recs if r.get("rtype") == "book"}
    books = {}
    for b in sorted(ids):
        recs = [r for r in client.summaries(client.search(f"{b}[book]")) if book_id(r) == b]
        if recs:
            books[b] = recs
        else:
            print(f"  ! {b}: E-utilities returned no records", file=sys.stderr)
    return books


def harvest_book(client: Client, out_dir: str, report: str, records: list[dict], plan_only: bool) -> dict:
    d = os.path.join(out_dir, report)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "records.json"), "w") as f:
        json.dump(records, f, indent=1)
    with open(os.path.join(d, "CATALOGUE.md"), "w") as f:
        f.write(catalogue(report, records))
    jobs = plan(records)
    status: dict[str, dict] = {}
    if not plan_only:
        queue = list(jobs)
        while queue:
            job = queue.pop(0)
            path = os.path.join(d, job["path"])
            if os.path.exists(path):
                body, code = open(path, "rb").read(), 200
            else:
                code, body = client.get(job["url"], gate_check=job["kind"] != "image")
                if code == 200:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "wb") as f:
                        f.write(body)
                elif not job["optional"]:
                    print(f"  ! {report} HTTP {code} {job['url']}", file=sys.stderr)
            status[job["url"]] = {"path": job["path"], "kind": job["kind"], "http": code}
            if code == 200 and job["path"].endswith(".html"):
                found = object_links(body) + [{"url": u, "path": p, "kind": "image", "optional": False}
                                              for u, p in images(body)]
                for job2 in found:
                    if job2["url"] not in status and all(q["url"] != job2["url"] for q in queue):
                        queue.append(job2)
    index = {
        "report": report, "book": next((r for r in records if r.get("rtype") == "book"), None),
        "harvested": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "records": [{"uid": r["uid"], "rtype": r["rtype"], "title": r["title"], "id": r["id"],
                     "accession": r["accessionid"], "file": record_file(r)} for r in records],
        "fetched": status, "planned": len(jobs),
    }
    with open(os.path.join(d, "index.json"), "w") as f:
        json.dump(index, f, indent=1)
    return index


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default="assets/cebs/_bookshelf")
    ap.add_argument("--term", default=DEFAULT_TERM, help="E-utilities search that finds the books")
    ap.add_argument("--book", action="append", default=[], help="NBK accession or book id (repeatable)")
    ap.add_argument("--records", help="offline: a saved esummary records.json instead of E-utilities")
    ap.add_argument("--plan-only", action="store_true", help="write records/catalogue, fetch no pages")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between requests (default 1)")
    ap.add_argument("--api-key", default=os.environ.get("NCBI_API_KEY"))
    ap.add_argument("--email", default=os.environ.get("NCBI_EMAIL"))
    ap.add_argument("--user-agent", default="rlm-bmdx-bookshelf-harvest/1.0 (python-urllib)")
    a = ap.parse_args()

    client = Client(a.delay, a.user_agent, a.api_key, a.email)
    try:
        if a.records:
            recs = json.load(open(a.records))
            books = {}
            for r in recs:
                books.setdefault(book_id(r), []).append(r)
        else:
            books = discover(client, a.term, a.book)
        summary = []
        for b, recs in sorted(books.items()):
            book = next((r for r in recs if r.get("rtype") == "book"), None)
            report = report_name(book["title"] if book else "", b)
            idx = harvest_book(client, a.out, report, recs, a.plan_only or bool(a.records))
            ok = sum(1 for s in idx["fetched"].values() if s["http"] == 200)
            kinds = {}
            for r in recs:
                kinds[r["rtype"]] = kinds.get(r["rtype"], 0) + 1
            line = (f"{report:9} {book['accessionid'] if book else '?':10} {b:14} records {kinds} "
                    f"planned {idx['planned']} fetched {ok}/{len(idx['fetched'])}")
            print(line)
            summary.append({"report": report, "book_id": b,
                            "nbk": book["accessionid"] if book else None,
                            "title": book["title"] if book else None, "records": len(recs)})
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, "books.json"), "w") as f:
            json.dump(summary, f, indent=1)
    except Gated as g:
        print(f"\nSTOPPED: NCBI served its reCAPTCHA page for {g}.\n"
              "Open https://www.ncbi.nlm.nih.gov/books/NBK621725/ in a browser on this machine, "
              "then re-run (finished files are kept).", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
