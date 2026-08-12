"""
Bulk-corpus pipeline via the Semantic Scholar Datasets API.

An alternative to the per-paper graph crawl (citegraph.py): instead of walking
references/citations at ~1 req/sec, download whole-corpus snapshots (papers,
abstracts, citations, tldrs) as gzipped JSONL shards, then filter locally to the
toxicogenomics slice. Output is written in the SAME contract citegraph.py emits
(citegraph_output_<name>/papers.json + edges.json), so extract.py and build_db.py
consume it unchanged.

Three stages, independently runnable:
  manifest  — fetch shard download URLs from the API host (works today)
  download  — pull shards from S3 (needs the ai2-s2ag.s3 host allowlisted)
  filter    — stream shards, keep tox-relevant papers, emit papers.json/edges.json

The manifest/download split matters here: the API host (api.semanticscholar.org)
is reachable, but the shard bytes live on a separate S3 host that may be
firewalled. Keeping the stages separate lets the manifest + filter logic be built
and tested before S3 is open (see --local-shards for offline testing).

Record schemas (S2 Datasets, join key = corpusid):
  papers    : corpusid, title, year, venue, citationcount, referencecount,
              externalids{DOI,ArXiv,PubMed,PubMedCentral}, publicationtypes,
              s2fieldsofstudy[{category,source}], url, isopenaccess
  abstracts : corpusid, abstract
  citations : citingcorpusid, citedcorpusid
  tldrs     : corpusid, text
"""

import gzip
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Iterator

import requests

from citegraph import (
    Paper,
    GovernorConfig,
    score_relevance,
    tag_organs,
    resolve_s2_api_key,
    log_s2_auth_status,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DATASETS_BASE = "https://api.semanticscholar.org/datasets/v1"

# Datasets we pull. `papers` is the spine; the others are joined on corpusid.
CORE_DATASETS = ["papers", "abstracts", "tldrs", "citations"]

# Where shards land and where the filtered corpus is written.
SHARD_DIR = Path("datasets_shards")
OUTPUT_DIR = Path("citegraph_output_datasets")


# ---------------------------------------------------------------------------
# Stage 1: manifest (API host — reachable today)
# ---------------------------------------------------------------------------

def _get_json(url: str, api_key: str | None, retries: int = 5) -> dict | list | None:
    """GET with the S2 auth header and exponential backoff on 429/5xx."""
    headers = {"x-api-key": api_key} if api_key else {}
    delay = 10
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=40)
        except requests.RequestException as e:
            print(f"  [request error: {e}]")
            if attempt == retries - 1:
                return None
            time.sleep(delay)
            delay *= 2
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504):
            print(f"  [HTTP {r.status_code}, backing off {delay}s "
                  f"(attempt {attempt + 1}/{retries})]")
            time.sleep(delay)
            delay *= 2
            continue
        print(f"  [HTTP {r.status_code} for {url}]")
        return None
    return None


def get_latest_release(api_key: str | None) -> str | None:
    """Return the latest release id (e.g. '2026-06-24')."""
    data = _get_json(f"{DATASETS_BASE}/release/latest", api_key)
    if isinstance(data, dict):
        return data.get("release_id")
    return None


def fetch_manifest(datasets: list[str] | None = None,
                   api_key: str | None = None,
                   release_id: str | None = None) -> dict:
    """Fetch shard download URLs for each dataset.

    Returns {release_id, datasets: {name: [shard_urls]}}. Persisted to
    SHARD_DIR/manifest.json so the (short-lived, signed) URLs can be reused by
    the download stage without re-hitting the API.
    """
    datasets = datasets or CORE_DATASETS
    if release_id is None:
        release_id = get_latest_release(api_key) or "latest"
    print(f"Release: {release_id}")

    manifest: dict = {"release_id": release_id, "datasets": {}}
    for name in datasets:
        url = f"{DATASETS_BASE}/release/{release_id}/dataset/{name}"
        data = _get_json(url, api_key)
        files = data.get("files", []) if isinstance(data, dict) else []
        manifest["datasets"][name] = files
        print(f"  {name}: {len(files)} shard URLs")

    SHARD_DIR.mkdir(exist_ok=True)
    with open(SHARD_DIR / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Saved manifest to {SHARD_DIR / 'manifest.json'}")
    return manifest


# ---------------------------------------------------------------------------
# Stage 2: download (S3 host — needs allowlist)
# ---------------------------------------------------------------------------

def download_shards(manifest: dict, datasets: list[str] | None = None,
                    max_shards_per_dataset: int | None = None) -> dict:
    """Download shard files to SHARD_DIR/<dataset>/, resuming if present.

    Returns {dataset: [local_paths]}. S3 URLs are pre-signed and expire, so run
    this soon after fetch_manifest. Skips files already fully downloaded.
    """
    datasets = datasets or list(manifest["datasets"].keys())
    local: dict[str, list[str]] = {}

    for name in datasets:
        urls = manifest["datasets"].get(name, [])
        if max_shards_per_dataset:
            urls = urls[:max_shards_per_dataset]
        dest = SHARD_DIR / name
        dest.mkdir(parents=True, exist_ok=True)
        paths = []
        for i, url in enumerate(urls):
            out = dest / f"{name}-{i:04d}.gz"
            if out.exists() and out.stat().st_size > 0:
                print(f"  [{name} {i + 1}/{len(urls)}] cached")
                paths.append(str(out))
                continue
            print(f"  [{name} {i + 1}/{len(urls)}] downloading...")
            if not _download_one(url, out):
                print(f"    [failed: {out.name}]")
                continue
            paths.append(str(out))
        local[name] = paths
    return local


def _download_one(url: str, out: Path, retries: int = 3) -> bool:
    """Stream one shard to disk. Returns True on success."""
    tmp = out.with_suffix(out.suffix + ".part")
    for attempt in range(retries):
        try:
            with requests.get(url, stream=True, timeout=120) as r:
                if r.status_code != 200:
                    print(f"    [HTTP {r.status_code}]")
                    if r.status_code in (429, 500, 502, 503, 504):
                        time.sleep(5 * (attempt + 1))
                        continue
                    return False
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        if chunk:
                            f.write(chunk)
            tmp.rename(out)
            return True
        except requests.RequestException as e:
            print(f"    [download error: {e}]")
            time.sleep(5 * (attempt + 1))
    if tmp.exists():
        tmp.unlink()
    return False


# ---------------------------------------------------------------------------
# Stage 3: filter (local — no network)
# ---------------------------------------------------------------------------

def _iter_shard_records(paths: list[str]) -> Iterator[dict]:
    """Yield JSON records from a set of gzipped-JSONL shard files."""
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue


# Fields of study S2 assigns that are relevant to our domain. Used as a cheap
# first-pass gate before the (more expensive) keyword relevance scoring.
RELEVANT_FIELDS = {
    "Biology", "Medicine", "Chemistry",
    "Environmental Science", "Agricultural and Food Sciences",
}


def _paper_from_s2_record(rec: dict, abstract: str | None,
                          config: GovernorConfig) -> Paper | None:
    """Map an S2 Datasets `papers` record (+ joined abstract) to our Paper."""
    corpusid = rec.get("corpusid")
    if corpusid is None:
        return None

    ext = rec.get("externalids") or {}
    pubtypes = rec.get("publicationtypes") or []
    # s2fieldsofstudy is a list of {category, source}
    fields = {f.get("category") for f in (rec.get("s2fieldsofstudy") or [])
              if isinstance(f, dict)}

    authors = [a.get("name", "") for a in (rec.get("authors") or [])][:10]

    p = Paper(
        paper_id=str(corpusid),  # corpusid is the datasets join key + our pid
        title=rec.get("title") or "",
        authors=authors,
        year=rec.get("year"),
        abstract=abstract,
        venue=rec.get("venue") or "",
        citation_count=rec.get("citationcount") or 0,
        reference_count=rec.get("referencecount") or 0,
        doi=ext.get("DOI"),
        arxiv_id=ext.get("ArXiv"),
        url=rec.get("url"),
        pmid=ext.get("PubMed"),
        pmcid=ext.get("PubMedCentral"),
        is_review="Review" in pubtypes,
    )
    p.relevance_score = score_relevance(p, config)
    p.organs_tagged = tag_organs(p, config)
    p._fields = fields  # transient, used by the field gate below
    return p


def filter_corpus(local_shards: dict[str, list[str]] | None = None,
                  config: GovernorConfig | None = None,
                  relevance_threshold: float | None = None,
                  require_abstract: bool = True) -> dict:
    """Stream the papers/abstracts/citations shards and emit the tox slice.

    Pass 1: build corpusid -> abstract from the abstracts shards.
    Pass 2: stream papers; score relevance; keep those above threshold (and,
            when require_abstract, that actually have an abstract, since the
            Claude extractor needs text).
    Pass 3: stream citations; keep edges where BOTH endpoints survived filtering.

    Writes OUTPUT_DIR/papers.json + edges.json in the citegraph.py contract.
    """
    config = config or GovernorConfig()
    threshold = (relevance_threshold if relevance_threshold is not None
                 else config.relevance_threshold)

    # Resolve shard paths: explicit (offline test) or from downloaded layout.
    if local_shards is None:
        local_shards = {
            name: sorted(str(p) for p in (SHARD_DIR / name).glob("*.gz"))
            for name in CORE_DATASETS
        }

    # Pass 1 — abstracts index
    print("Pass 1: indexing abstracts...")
    abstracts: dict[str, str] = {}
    for rec in _iter_shard_records(local_shards.get("abstracts", [])):
        cid = rec.get("corpusid")
        ab = rec.get("abstract")
        if cid is not None and ab:
            abstracts[str(cid)] = ab
    print(f"  {len(abstracts)} abstracts indexed")

    # Pass 2 — papers, scored + filtered
    print("Pass 2: filtering papers...")
    kept: dict[str, Paper] = {}
    scanned = 0
    for rec in _iter_shard_records(local_shards.get("papers", [])):
        scanned += 1
        cid = rec.get("corpusid")
        if cid is None:
            continue
        abstract = abstracts.get(str(cid))
        if require_abstract and not abstract:
            continue
        p = _paper_from_s2_record(rec, abstract, config)
        if p is None:
            continue
        # cheap field-of-study gate, then keyword relevance
        if p._fields and not (p._fields & RELEVANT_FIELDS):
            continue
        if p.relevance_score < threshold:
            continue
        kept[p.paper_id] = p
    print(f"  scanned {scanned}, kept {len(kept)} tox-relevant papers")

    # Pass 3 — citation edges internal to the kept set
    print("Pass 3: filtering citation edges...")
    edges = []
    seen_pairs: set[tuple[str, str]] = set()
    for rec in _iter_shard_records(local_shards.get("citations", [])):
        src = rec.get("citingcorpusid")
        tgt = rec.get("citedcorpusid")
        if src is None or tgt is None:
            continue
        src, tgt = str(src), str(tgt)
        if src in kept and tgt in kept:
            pair = (src, tgt)
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                edges.append({"source": src, "target": tgt, "type": "references"})
    print(f"  {len(edges)} internal citation edges")

    _write_output(kept, edges)
    return {"papers": len(kept), "edges": len(edges)}


def _write_output(papers: dict[str, Paper], edges: list[dict]) -> None:
    """Write papers.json + edges.json in the citegraph.py output contract."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    rows = []
    for p in sorted(papers.values(), key=lambda x: x.relevance_score, reverse=True):
        d = asdict(p)
        d.pop("_fields", None)  # drop transient field
        rows.append(d)
    with open(OUTPUT_DIR / "papers.json", "w") as f:
        json.dump(rows, f, indent=2, default=str)
    with open(OUTPUT_DIR / "edges.json", "w") as f:
        json.dump(edges, f, indent=2)
    print(f"Wrote {len(rows)} papers + {len(edges)} edges to {OUTPUT_DIR}/")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    if not argv:
        print("Usage: python datasets_pipeline.py <stage> [options]")
        print("Stages:")
        print("  manifest              — fetch shard URLs (API host)")
        print("  download              — pull shards from S3 (needs allowlist)")
        print("  filter                — stream shards → tox papers.json/edges.json")
        print("  all                   — manifest → download → filter")
        print("Options:")
        print("  --max-shards N        — cap shards per dataset (testing)")
        print("  --local-shards DIR    — filter from a local shard dir (offline)")
        print("  --threshold F         — relevance cutoff (default from GovernorConfig)")
        return 1

    stage = argv[0]
    max_shards = None
    local_dir = None
    threshold = None
    i = 1
    while i < len(argv):
        if argv[i] == "--max-shards" and i + 1 < len(argv):
            max_shards = int(argv[i + 1]); i += 2
        elif argv[i] == "--local-shards" and i + 1 < len(argv):
            local_dir = argv[i + 1]; i += 2
        elif argv[i] == "--threshold" and i + 1 < len(argv):
            threshold = float(argv[i + 1]); i += 2
        else:
            i += 1

    api_key = resolve_s2_api_key()
    log_s2_auth_status(api_key)
    config = GovernorConfig()

    if stage in ("manifest", "all"):
        manifest = fetch_manifest(api_key=api_key)
    if stage in ("download", "all"):
        with open(SHARD_DIR / "manifest.json") as f:
            manifest = json.load(f)
        download_shards(manifest, max_shards_per_dataset=max_shards)
    if stage in ("filter", "all"):
        local_shards = None
        if local_dir:
            base = Path(local_dir)
            local_shards = {
                name: sorted(str(p) for p in (base / name).glob("*.gz"))
                for name in CORE_DATASETS
            }
        filter_corpus(local_shards=local_shards, config=config,
                      relevance_threshold=threshold)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
