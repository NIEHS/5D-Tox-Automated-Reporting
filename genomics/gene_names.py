"""
genomics/gene_names.py — a gene's full name, as the books print it beside its
symbol: "Spp1 (secreted phosphoprotein 1)" (NIEHS-12, 13 Results).

The name is NCBI Gene's (its ``description``: "LCK proto-oncogene, Src family
tyrosine kinase" for rat Lck, gene 313050), keyed by the gene's Entrez id, which
the genomic results carry (``top_genes[].entrez_id``) and which names one gene
of one species.  Names are public reference data, kept in a version-controlled
cache (``assets/gene_names.json``: {entrez id: name}) that rendering reads.

Filling the cache asks NCBI about the study's genes — a list derived from the
study, so, like Enrichr (knowledge_base.enrichr_client), the lookup fails
CLOSED: it runs only with ``BMDX_ALLOW_NCBI_GENE=1``, which a dev run on
published data may set.  A gene the cache does not name is printed with a
visible pending marker instead of a name.
"""

from __future__ import annotations

import json
import logging
import os
import threading

from common.paths import REPO_ROOT

logger = logging.getLogger(__name__)

CACHE_FILE = REPO_ROOT / "assets" / "gene_names.json"
ALLOW_ENV = "BMDX_ALLOW_NCBI_GENE"
ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
_BATCH = 200

_lock = threading.Lock()


def lookup_allowed() -> bool:
    return os.environ.get(ALLOW_ENV, "").strip().lower() in ("1", "true", "yes")


def _read_cache() -> dict[str, str]:
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _fetch(ids: list[str]) -> dict[str, str]:
    """{entrez id: name} from NCBI Gene's esummary for ``ids``."""
    import requests
    found: dict[str, str] = {}
    for i in range(0, len(ids), _BATCH):
        batch = ids[i:i + _BATCH]
        resp = requests.get(ESUMMARY, params={"db": "gene", "id": ",".join(batch),
                                              "retmode": "json"}, timeout=30)
        resp.raise_for_status()
        result = resp.json().get("result") or {}
        for gid in result.get("uids") or []:
            name = (result.get(gid) or {}).get("description") or ""
            if name:
                found[str(gid)] = name
    return found


def gene_names(entrez_ids) -> dict[str, str]:
    """{entrez id: full name} for the ids the cache names — after asking NCBI
    for the others when the lookup is allowed (BMDX_ALLOW_NCBI_GENE=1)."""
    ids = sorted({str(i).strip() for i in entrez_ids if str(i or "").strip().isdigit()})
    with _lock:
        cache = _read_cache()
        missing = [i for i in ids if i not in cache]
        if missing and lookup_allowed():
            try:
                fetched = _fetch(missing)
            except Exception as e:                  # network-dependent
                logger.warning("NCBI gene names unavailable (%s); %d gene(s) unnamed", e,
                               len(missing))
                fetched = {}
            if fetched:
                cache.update(fetched)
                CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                CACHE_FILE.write_text(json.dumps(dict(sorted(cache.items(), key=lambda kv: int(kv[0]))),
                                                 indent=0, ensure_ascii=False) + "\n",
                                      encoding="utf-8")
        elif missing:
            logger.info("%d gene name(s) not cached; set %s=1 to look them up at NCBI",
                        len(missing), ALLOW_ENV)
    return {i: cache[i] for i in ids if i in cache}
