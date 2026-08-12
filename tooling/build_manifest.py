"""Build a navigable manifest of the retrieved corpus.

Joins catalog.json (citation metadata, keyed by paper GUID) with the on-disk
.fulltext_cache/ artifacts (raw PDF/HTML/XML + cleaned text + meta sidecar),
so downstream tools can consume the corpus by title/DOI without decoding S2
paper IDs.

Outputs (default):
  manifest.json  — one record per retrieved paper: GUID, full citation fields,
                   source, and absolute paths to every cached artifact.
  manifest.csv   — flat spreadsheet view (one row per paper, key columns).
  manifest_misses.csv — catalog papers with no retrieved full text.

Usage:
    python build_manifest.py [--catalog catalog.json] [--cache .fulltext_cache]
                             [--out-json manifest.json] [--out-csv manifest.csv]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path


def _first_existing(cache: Path, stem: str, exts: list[str]) -> str | None:
    for ext in exts:
        p = cache / f"{stem}.{ext}"
        if p.exists():
            return f"{cache.as_posix()}/{p.name}"
    return None


def build(catalog_path: str, cache_dir: str) -> tuple[list[dict], list[dict]]:
    catalog = json.load(open(catalog_path))
    # Keep cache path relative so the manifest is portable across machines
    # (e.g. copied to the host where the parsing software runs).
    cache = Path(cache_dir)

    hits: list[dict] = []
    misses: list[dict] = []

    for guid, rec in catalog.items():
        meta_path = cache / f"{guid}.meta.json"
        txt_path = cache / f"{guid}.txt"

        citation = {
            "guid": guid,
            "title": rec.get("title"),
            "authors": "; ".join(a.get("name", "") for a in (rec.get("authors") or [])),
            "year": rec.get("year"),
            "publication_date": rec.get("publication_date"),
            "journal": rec.get("journal_name"),
            "journal_volume": rec.get("journal_volume"),
            "journal_pages": rec.get("journal_pages"),
            "publisher": rec.get("publisher_venue"),
            "issn": rec.get("issn"),
            "doi": rec.get("doi"),
            "pmid": rec.get("pmid"),
            "pmcid": rec.get("pmcid"),
            "landing_url": rec.get("landing_url"),
            "open_access_pdf": rec.get("open_access_pdf"),
            "fields_of_study": rec.get("fields_of_study"),
            "citation_count": rec.get("citation_count"),
            "abstract": rec.get("abstract"),
        }

        if not (meta_path.exists() and txt_path.exists()):
            misses.append({k: citation[k] for k in
                           ("guid", "title", "doi", "pmid", "pmcid",
                            "journal", "landing_url", "open_access_pdf")})
            continue

        meta = json.loads(meta_path.read_text())
        record = dict(citation)
        record.update({
            "source": meta.get("source"),
            "char_count": meta.get("char_count"),
            "truncated": meta.get("truncated", False),
            "raw_kind": meta.get("raw_kind", ""),
            "resolved_url": meta.get("resolved_url", ""),
            "text_path": f"{cache.as_posix()}/{txt_path.name}",
            "raw_path": _first_existing(cache, guid, ["pdf", "html", "xml"]),
            "meta_path": f"{cache.as_posix()}/{meta_path.name}",
        })
        hits.append(record)

    return hits, misses


CSV_COLUMNS = [
    "guid", "title", "authors", "year", "journal", "publisher", "doi",
    "pmid", "pmcid", "source", "raw_kind", "char_count", "landing_url",
    "resolved_url", "text_path", "raw_path",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="catalog.json")
    ap.add_argument("--cache", default=".fulltext_cache")
    ap.add_argument("--out-json", default="manifest.json")
    ap.add_argument("--out-csv", default="manifest.csv")
    ap.add_argument("--out-misses", default="manifest_misses.csv")
    args = ap.parse_args()

    hits, misses = build(args.catalog, args.cache)

    with open(args.out_json, "w") as f:
        json.dump(hits, f, indent=2, default=str)

    with open(args.out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(hits)

    with open(args.out_misses, "w", newline="") as f:
        cols = ["guid", "title", "doi", "pmid", "pmcid", "journal",
                "landing_url", "open_access_pdf"]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(misses)

    # raw-kind breakdown for the summary
    from collections import Counter
    by_kind = Counter(h.get("raw_kind") or "(none)" for h in hits)
    by_source = Counter(h.get("source") for h in hits)
    with_raw = sum(1 for h in hits if h.get("raw_path"))

    print(f"Manifest: {len(hits)} retrieved, {len(misses)} misses "
          f"({len(hits)}/{len(hits)+len(misses)} = "
          f"{100*len(hits)//(len(hits)+len(misses))}%)")
    print(f"  by source: {dict(by_source)}")
    print(f"  raw artifact on disk: {with_raw}/{len(hits)}  by kind: {dict(by_kind)}")
    print(f"  wrote: {args.out_json}, {args.out_csv}, {args.out_misses}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
