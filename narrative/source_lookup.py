"""
narrative/source_lookup.py — is a cited source real?  The questions asked of
the outside world, and what was answered (ADR-0038).

Two questions, each about a public identifier and nothing else:

  * is a DOI registered?  Asked of the DOI system itself
    (``https://doi.org/api/handles/<doi>``), which answers for every
    registration agency.  A registered DOI stays registered, so a "yes" is
    kept for good; a "no" is kept as the last answer and asked again next
    time.
  * does an address answer?  One GET.  An answer is kept for a month.

The answers are kept in ``OUTPUT_DIR/_source_lookups.json``, one file for all
studies: a DOI is the same DOI whichever report cites it.

What is never asked here: anything that carries a study's data.  And the DOIs
of a knowledge base's papers are asked for the knowledge base as a whole
(``check_dois`` over all of them, ``tooling/citations.py kb-dois``), never for
the papers one study cites: which papers a study's interpretations cite says
something about what the study found, and the DOI system is a public service.
The citation check reads those answers with ``known_doi`` and asks nothing.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

REGISTERED = "registered"
NOT_REGISTERED = "not_registered"
NOT_CHECKED = "not_checked"          # the registry could not be asked

ANSWERS = "answers"
REFUSES = "refuses"                  # the address exists and turns a program away
NOT_FOUND = "not_found"
NOT_REACHED = "not_reached"          # no answer from here (firewall, outage)

_FILE = "_source_lookups.json"
_URL_KEPT_FOR = timedelta(days=30)
_TIMEOUT = 20
_AGENT = "Mozilla/5.0 (X11; Linux x86_64) rlm-bmdx citation check"
_lock = threading.Lock()


def _path() -> Path:
    from common.paths import OUTPUT_DIR
    return Path(OUTPUT_DIR) / _FILE


def _read() -> dict:
    try:
        blob = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        blob = {}
    blob.setdefault("doi", {})
    blob.setdefault("url", {})
    return blob


def _keep(kind: str, key: str, state: str) -> None:
    with _lock:
        blob = _read()
        blob[kind][key] = {"state": state, "asked_at": _now()}
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(blob, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get(url: str, accept: str = "*/*"):
    request = urllib.request.Request(url, headers={"User-Agent": _AGENT, "Accept": accept})
    return urllib.request.urlopen(request, timeout=_TIMEOUT)  # noqa: S310 — http(s) only, checked by callers


# ---------------------------------------------------------------------------
# DOIs
# ---------------------------------------------------------------------------

def known_doi(doi: str) -> str:
    """What is on file about a DOI, asking nothing: ``registered``,
    ``not_registered`` (the last answer) or ``not_checked``."""
    kept = _read()["doi"].get(str(doi or "").strip().lower()) or {}
    return kept["state"] if kept.get("state") in (REGISTERED, NOT_REGISTERED) else NOT_CHECKED


def ask_doi(doi: str) -> str:
    """Ask the DOI system whether ``doi`` is registered (no file read or
    written)."""
    doi = str(doi or "").strip().lower()
    if not doi:
        return NOT_CHECKED
    url = "https://doi.org/api/handles/" + urllib.parse.quote(doi, safe="/")
    try:
        with _get(url, "application/json") as response:
            code = json.loads(response.read().decode("utf-8")).get("responseCode")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            return NOT_CHECKED
        try:
            code = json.loads(e.read().decode("utf-8")).get("responseCode")
        except (ValueError, OSError):
            code = 100
    except (OSError, ValueError):
        return NOT_CHECKED
    # The handle system's codes: 1 = found, 100 = no such handle.
    return REGISTERED if code == 1 else NOT_REGISTERED if code == 100 else NOT_CHECKED


def check_doi(doi: str, ask=ask_doi) -> str:
    """``registered`` / ``not_registered`` / ``not_checked`` for a DOI: from
    what is on file when it says registered, else by asking."""
    doi = str(doi or "").strip().lower()
    if not doi:
        return NOT_CHECKED
    if known_doi(doi) == REGISTERED:
        return REGISTERED
    state = ask(doi)
    if state in (REGISTERED, NOT_REGISTERED):
        _keep("doi", doi, state)
    return state


def check_dois(dois, ask=ask_doi, workers: int = 8, progress=None) -> dict[str, str]:
    """``check_doi`` over many DOIs, several at a time; {doi: state}."""
    wanted = sorted({str(d or "").strip().lower() for d in dois} - {""})
    out: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, (doi, state) in enumerate(zip(wanted, pool.map(lambda d: check_doi(d, ask), wanted)), 1):
            out[doi] = state
            if progress and i % 200 == 0:
                progress(i, len(wanted))
    return out


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------

def ask_url(url: str) -> str:
    if not str(url or "").lower().startswith(("http://", "https://")):
        return NOT_FOUND
    try:
        with _get(url):
            return ANSWERS
    except urllib.error.HTTPError as e:
        return NOT_FOUND if e.code in (404, 410) else REFUSES
    except (OSError, ValueError):
        return NOT_REACHED


def check_url(url: str, ask=ask_url) -> str:
    """``answers`` / ``refuses`` / ``not_found`` / ``not_reached`` for an
    address: from what is on file when it answered within the last month, else
    by asking."""
    url = str(url or "").strip()
    kept = _read()["url"].get(url)
    if kept and kept.get("state") in (ANSWERS, REFUSES):
        try:
            asked = datetime.strptime(kept["asked_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - asked < _URL_KEPT_FOR:
                return kept["state"]
        except (KeyError, ValueError):
            pass
    state = ask(url)
    if state in (ANSWERS, REFUSES):
        _keep("url", url, state)
    return state
