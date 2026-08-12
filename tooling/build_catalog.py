"""Build a consolidated corpus catalog from Semantic Scholar.

One enriched pass over every unique paper across all citegraph_output* dirs,
using the S2 batch endpoint (500 ids/request) so the whole corpus resolves in a
handful of requests rather than thousands of serial calls.

Output: catalog.json — a dict keyed by paper GUID (S2 paperId) whose values
carry the full citation record (title, authors, journal/publisher, all external
ids, dates, counts, fields of study, abstract, tldr, open-access pdf + landing
url). This is the single source of truth that the full-text fetch + extraction
stages read from. It is also the GUID->title map.

Usage:
    S2_API_KEY=<key> python build_catalog.py [--out catalog.json] [--glob 'citegraph_output*']

Reads S2_API_KEY from the environment (falls back to --s2-key). Rate-limited to
stay under the 1 req/s cumulative key limit. Resumable: existing catalog entries
are kept and only missing ids are fetched.
"""
from __future__ import annotations

import argparse
import glob as globmod
import json
import os
import sys
import time
from pathlib import Path

import requests

S2_BATCH = "https://api.semanticscholar.org/graph/v1/paper/batch"

# Everything we want in one pass. publicationVenue carries ISSN + publisher URL;
# journal carries name/volume/pages; externalIds carries DOI/PubMed/PMC/CorpusId.
CATALOG_FIELDS = ",".join([
    "paperId", "corpusId", "externalIds", "url", "title", "abstract",
    "venue", "publicationVenue", "year", "publicationDate",
    "referenceCount", "citationCount", "influentialCitationCount",
    "isOpenAccess", "openAccessPdf", "fieldsOfStudy", "s2FieldsOfStudy",
    "publicationTypes", "journal", "authors", "tldr",
])

BATCH_SIZE = 500
REQUEST_DELAY = 1.2  # seconds between batch requests — under the 1 req/s ceiling


def collect_unique_ids(glob_pattern: str) -> dict[str, str]:
    """Return {paper_id: title} across every papers.json matching the pattern."""
    seen: dict[str, str] = {}
    for f in sorted(globmod.glob(f"{glob_pattern}/papers.json")):
        try:
            papers = json.load(open(f))
        except (json.JSONDecodeError, OSError):
            continue
        for p in papers:
            pid = p.get("paper_id")
            if pid and pid not in seen:
                seen[pid] = p.get("title", "")
    return seen


def _landing_url(rec: dict) -> str | None:
    """Best front-page URL: DOI resolver > S2 venue url > S2 paper url."""
    ext = rec.get("externalIds") or {}
    doi = ext.get("DOI")
    if doi:
        return f"https://doi.org/{doi}"
    return rec.get("url")


def normalize(rec: dict) -> dict:
    """Flatten an S2 record into our catalog schema."""
    ext = rec.get("externalIds") or {}
    journal = rec.get("journal") or {}
    venue = rec.get("publicationVenue") or {}
    oa = rec.get("openAccessPdf") or {}
    authors = rec.get("authors") or []
    tldr = rec.get("tldr") or {}
    return {
        "paper_id": rec.get("paperId"),
        "corpus_id": rec.get("corpusId"),
        "title": rec.get("title"),
        "abstract": rec.get("abstract"),
        "tldr": tldr.get("text"),
        # citation / bibliographic
        "authors": [{"name": a.get("name"), "author_id": a.get("authorId")}
                    for a in authors],
        "year": rec.get("year"),
        "publication_date": rec.get("publicationDate"),
        "venue": rec.get("venue"),
        "journal_name": journal.get("name"),
        "journal_volume": journal.get("volume"),
        "journal_pages": journal.get("pages"),
        "publisher_venue": venue.get("name"),
        "publisher_type": venue.get("type"),
        "issn": venue.get("issn"),
        "publisher_url": venue.get("url"),
        "publication_types": rec.get("publicationTypes"),
        "fields_of_study": rec.get("fieldsOfStudy"),
        # identifiers
        "doi": ext.get("DOI"),
        "pmid": ext.get("PubMed"),
        "pmcid": ext.get("PubMedCentral"),
        "arxiv_id": ext.get("ArXiv"),
        "external_ids": ext,
        # access
        "is_open_access": rec.get("isOpenAccess"),
        "open_access_pdf": oa.get("url"),
        "open_access_status": oa.get("status"),
        "landing_url": _landing_url(rec),
        # graph metrics
        "citation_count": rec.get("citationCount"),
        "reference_count": rec.get("referenceCount"),
        "influential_citation_count": rec.get("influentialCitationCount"),
    }


def fetch_batch(ids: list[str], api_key: str, _retries: int = 4) -> list[dict | None]:
    headers = {"x-api-key": api_key} if api_key else {}
    try:
        r = requests.post(S2_BATCH, params={"fields": CATALOG_FIELDS},
                          json={"ids": ids}, headers=headers, timeout=120)
    except requests.RequestException as e:
        if _retries > 0:
            print(f"  [request error: {e}; retrying]")
            time.sleep(5)
            return fetch_batch(ids, api_key, _retries - 1)
        return [None] * len(ids)
    if r.status_code == 429:
        wait = int(r.headers.get("Retry-After", 10))
        print(f"  [rate limited, waiting {wait}s]")
        time.sleep(wait)
        if _retries > 0:
            return fetch_batch(ids, api_key, _retries - 1)
        return [None] * len(ids)
    if r.status_code != 200:
        print(f"  [API error {r.status_code}: {r.text[:200]}]")
        if r.status_code >= 500 and _retries > 0:
            time.sleep(5)
            return fetch_batch(ids, api_key, _retries - 1)
        return [None] * len(ids)
    return r.json()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="catalog.json")
    ap.add_argument("--glob", default="citegraph_output*")
    ap.add_argument("--s2-key", default=None)
    args = ap.parse_args()

    api_key = args.s2_key or os.environ.get("S2_API_KEY", "")
    if not api_key:
        print("WARNING: no S2_API_KEY — running against throttled public pool")

    out_path = Path(args.out)
    catalog: dict[str, dict] = {}
    if out_path.exists():
        catalog = json.load(open(out_path))
        print(f"Resuming: {len(catalog)} papers already in {out_path}")

    id_to_title = collect_unique_ids(args.glob)
    all_ids = list(id_to_title)
    todo = [pid for pid in all_ids if pid not in catalog]
    print(f"Corpus: {len(all_ids)} unique papers; {len(todo)} to fetch "
          f"({len(catalog)} cached)")

    fetched = 0
    for i in range(0, len(todo), BATCH_SIZE):
        batch = todo[i:i + BATCH_SIZE]
        records = fetch_batch(batch, api_key)
        for pid, rec in zip(batch, records):
            if rec:
                catalog[pid] = normalize(rec)
                fetched += 1
            else:
                # keep a stub so we know it was tried and can map guid->title
                catalog[pid] = {"paper_id": pid, "title": id_to_title.get(pid),
                                "_resolved": False}
        # checkpoint after every batch (resumable)
        with open(out_path, "w") as f:
            json.dump(catalog, f, indent=2, default=str)
        print(f"  batch {i // BATCH_SIZE + 1}/"
              f"{(len(todo) + BATCH_SIZE - 1) // BATCH_SIZE}: "
              f"{fetched} fetched, {len(catalog)} total")
        if i + BATCH_SIZE < len(todo):
            time.sleep(REQUEST_DELAY)

    resolved = sum(1 for v in catalog.values() if v.get("_resolved") is not False)
    oa = sum(1 for v in catalog.values() if v.get("open_access_pdf"))
    pmc = sum(1 for v in catalog.values() if v.get("pmcid"))
    print(f"\nCatalog complete: {len(catalog)} papers -> {out_path}")
    print(f"  resolved: {resolved}, open-access pdf: {oa}, pmc: {pmc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
