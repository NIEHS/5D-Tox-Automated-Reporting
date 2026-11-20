"""
narrative/sources.py — the sources a report may cite, and how text cites them.

A report cites sources of several origins (ADR-0038):

  * papers of the study's knowledge base, offered to the model that wrote a
    gene-level interpretation;
  * the public sources gathered about the chemical, offered to the model that
    wrote the Background;
  * boilerplate sources: what a document of this kind cites whatever the study
    (the statistical procedures, the software), kept in the definitions'
    source library (``templates/sources.yaml``);
  * sources a person added to a study (``sources.json`` in its session).

Every source is one **record** with a stable ``slug``.  Text cites a source by
its slug, as the token ``[[cite:<slug>]]``, never by a number: the numbers and
the reference list are derived from what a presented report prints
(rendering.citations), the way table numbers are.

The record::

    {"slug": "s3fa9c1d2e0", "identity": "doi:10.1042/bcj20200768",
     "kind": "paper" | "website" | "report" | "book" | "dataset" | "software" | "other",
     "origin": {"from": "knowledge_base" | "background" | "library" | "person", ...},
     "authors": [...], "title": ..., "container": ..., "year": ..., "volume": ...,
     "issue": ..., "pages": ..., "doi": ..., "url": ..., "accessed": ...,
     "text": <the entry as given, for a source recorded as one line>}

Identity decides sameness: a DOI, else an address, else the entry's text.  Two
records of one identity are one source, whatever their origin, so a paper two
studies of a report cite is listed once.

No I/O beyond reading the library and a session's own file; no LLM; no network.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

TOKEN_RE = re.compile(r"\[\[cite:([A-Za-z0-9_.\-]+)\]\]")
# A run of tokens that belong to one bracket: "[[cite:a]][[cite:b]]", with or
# without a comma or space between them.
RUN_RE = re.compile(r"\[\[cite:[A-Za-z0-9_.\-]+\]\](?:[ ,]{0,2}\[\[cite:[A-Za-z0-9_.\-]+\]\])*")

KINDS = ("paper", "website", "report", "book", "dataset", "software", "other")
ORIGINS = ("knowledge_base", "background", "library", "person")

LIBRARY_FILE = "sources.yaml"            # in templates/, beside the definitions
SESSION_FILE = "sources.json"            # a study's own, added by people

_HASHED_SLUG = re.compile(r"^s[0-9a-f]{10}$")
_LIBRARY_KEY = re.compile(r"^[a-z][a-z0-9_\-]*$")
_UNKNOWN = "unknown-"

# A numbered citation as the Background's model writes it: "[3]", "[1, 4]",
# "[2-4]".  And a knowledge-base token: "[P3]", "[P1, P3]".
_NUMERIC_BRACKET = re.compile(r"\[(\d+(?:\s*[,\-–]\s*\d+)*)\]")
_POOL_BRACKET = re.compile(r"\[P\d+(?:\s*,\s*P\d+)*\]")
_POOL_TOKEN = re.compile(r"P\d+")
_URL = re.compile(r"https?://\S+")
_LEADING_NUMBER = re.compile(r"^\s*\[\d+\]\s*")


def token(slug: str) -> str:
    return f"[[cite:{slug}]]"


def cited_slugs(text: str) -> list[str]:
    """The slugs a text cites, in order, each once."""
    return list(dict.fromkeys(TOKEN_RE.findall(text or "")))


def is_unknown(slug: str) -> bool:
    """A citation that names no source record (a number the Background's list
    does not have)."""
    return slug.startswith(_UNKNOWN)


# ---------------------------------------------------------------------------
# Identity and records
# ---------------------------------------------------------------------------

def normalize_doi(doi) -> str:
    doi = str(doi or "").strip()
    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", doi, flags=re.IGNORECASE)
    return doi.strip().lower()


def identity_of(record: dict) -> str:
    """What makes two records the same source: the DOI, else the address,
    else the entry's own words."""
    doi = normalize_doi(record.get("doi"))
    if doi:
        return f"doi:{doi}"
    url = str(record.get("url") or "").strip()
    if url:
        return f"url:{url.rstrip('/')}"
    words = " ".join(str(record.get("text") or record.get("title") or "").lower().split())
    return f"text:{words}"


def slug_for(identity: str) -> str:
    return "s" + hashlib.sha1(identity.encode("utf-8")).hexdigest()[:10]


def register(sources: dict, record: dict) -> str:
    """Add a source to ``sources`` ({slug: record}) and return its slug.  A
    record of an identity already there is the same source: its slug is
    returned, and the fields the earlier record lacks are filled from this one
    (the earlier origin stays)."""
    identity = identity_of(record)
    for slug, known in sources.items():
        if known.get("identity") == identity:
            for key, value in record.items():
                if value not in (None, "", []) and known.get(key) in (None, "", []):
                    known[key] = value
            return slug
    slug = record.get("slug") or slug_for(identity)
    sources[slug] = {**record, "slug": slug, "identity": identity,
                     "doi": normalize_doi(record.get("doi")) or None}
    return slug


def merge(sources: dict, others: dict | None) -> dict[str, str]:
    """Register every record of ``others`` in ``sources``; returns
    {their slug: the slug in ``sources``} (equal unless an identity was
    already there under another slug)."""
    return {slug: register(sources, dict(record)) for slug, record in (others or {}).items()}


# ---------------------------------------------------------------------------
# Where sources come from
# ---------------------------------------------------------------------------

def paper_source(paper: dict, knowledge_base: str | None = None) -> dict:
    """A paper of a knowledge base (a reference pool's entry) as a record."""
    doi = normalize_doi(paper.get("doi"))
    return {
        "kind": "paper",
        "origin": {"from": "knowledge_base", "knowledge_base": knowledge_base,
                   "paper_id": paper.get("paper_id")},
        "authors": list(paper.get("authors") or []),
        "title": (paper.get("title") or "").strip() or None,
        "container": (paper.get("venue") or "").strip() or None,
        "year": paper.get("year"),
        "doi": doi or None,
        "url": f"https://doi.org/{doi}" if doi else None,
        "genes": list(paper.get("genes") or []),
    }


def background_source(line: str) -> dict:
    """One line of the Background's reference list ("[2] ATSDR Toxicological
    Profile … (government report). https://…") as a record."""
    text = _LEADING_NUMBER.sub("", str(line or "")).strip()
    found = _URL.search(text)
    url = found.group(0).rstrip(".,;") if found else None
    words = (text[:found.start()] + text[found.end():]).strip() if found else text
    return {"kind": "website" if url else "other",
            "origin": {"from": "background"},
            "text": " ".join(words.split()), "url": url}


def background_sources(lines: list) -> tuple[dict, dict[int, str]]:
    """The Background's reference list as records, and {its number: slug}."""
    sources: dict = {}
    by_number: dict[int, str] = {}
    for i, line in enumerate(lines or [], start=1):
        if not isinstance(line, str) or not line.strip():
            continue
        m = re.match(r"^\s*\[(\d+)\]", line)
        by_number[int(m.group(1)) if m else i] = register(sources, background_source(line))
    return sources, by_number


_LIBRARY_CACHE: dict[str, tuple[float, dict]] = {}


def library_path() -> Path:
    from common.paths import REPO_ROOT
    return REPO_ROOT / "templates" / LIBRARY_FILE


def load_library(path: Path | None = None) -> dict:
    """The definitions' source library as records, {key: record}; the key is
    the slug text cites it by.  {} when there is no library."""
    path = Path(path) if path else library_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    cached = _LIBRARY_CACHE.get(str(path))
    if cached and cached[0] == mtime:
        return cached[1]
    import yaml
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict = {}
    for key, entry in (raw.get("sources") or {}).items():
        if not _LIBRARY_KEY.match(str(key)) or _HASHED_SLUG.match(str(key)):
            raise ValueError(f"{path.name}: {key!r} is not a usable source key "
                             "(lower-case letters, digits, '-' and '_', starting with a letter)")
        record = {**(entry or {}), "slug": key, "origin": {"from": "library", "key": key}}
        record.setdefault("kind", "paper")
        record["identity"] = identity_of(record)
        record["doi"] = normalize_doi(record.get("doi")) or None
        if record["doi"] and not record.get("url"):
            record["url"] = f"https://doi.org/{record['doi']}"
        out[key] = record
    _LIBRARY_CACHE[str(path)] = (mtime, out)
    return out


def load_session_sources(session_dir) -> dict:
    """The sources people added to a study, {slug: record}."""
    try:
        blob = json.loads((Path(session_dir) / SESSION_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {slug: record for slug, record in (blob.get("sources") or {}).items()
            if isinstance(record, dict)}


def add_session_source(session_dir, record: dict, *, added_by: str, added_at: str) -> str:
    """Record a source a person adds to a study; returns its slug.  A source of
    an identity the study already has is not added twice."""
    path = Path(session_dir) / SESSION_FILE
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        blob = {}
    sources = blob.setdefault("sources", {})
    kind = record.get("kind") or "other"
    if kind not in KINDS:
        raise ValueError(f"kind {kind!r} is not one of: {', '.join(KINDS)}")
    slug = register(sources, {**record, "kind": kind, "origin": {
        "from": "person", "added_by": added_by, "added_at": added_at}})
    path.write_text(json.dumps(blob, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return slug


# ---------------------------------------------------------------------------
# From what a writer wrote to tokens
# ---------------------------------------------------------------------------

def _numbers(inner: str) -> list[int]:
    out: list[int] = []
    for part in re.split(r"\s*,\s*", inner):
        ends = re.split(r"\s*[\-–]\s*", part)
        if len(ends) == 2 and ends[0].isdigit() and ends[1].isdigit() and int(ends[0]) <= int(ends[1]):
            out.extend(range(int(ends[0]), int(ends[1]) + 1))
        else:
            out.extend(int(e) for e in ends if e.isdigit())
    return out


def tokens_for_numbers(text: str, slug_by_number: dict[int, str]) -> str:
    """Numbered citations ("[3]", "[1, 4]") as tokens.  A number the list does
    not have becomes a citation of no source (``unknown-<n>``), which a
    presented report prints as pending and the citation check reports."""
    def sub(m: re.Match) -> str:
        return "".join(token(slug_by_number.get(n) or f"{_UNKNOWN}{n}")
                       for n in dict.fromkeys(_numbers(m.group(1))))
    return _NUMERIC_BRACKET.sub(sub, text) if isinstance(text, str) else text


def tokens_for_pool(text: str, slug_by_token: dict[str, str]) -> str:
    """A knowledge-base writer's tokens ("[P3]", "[P1, P3]") as tokens.  One
    that names no offered paper is dropped, as it always was (the citation
    check reports it from the writer's own record)."""
    def sub(m: re.Match) -> str:
        slugs = [slug_by_token[t] for t in _POOL_TOKEN.findall(m.group(0)) if t in slug_by_token]
        return "".join(token(s) for s in dict.fromkeys(slugs))
    if not isinstance(text, str):
        return text
    out = _POOL_BRACKET.sub(sub, text)
    return re.sub(r" {2,}", " ", out).replace(" .", ".").strip() if out != text else text


# ---------------------------------------------------------------------------
# The entry as a reference list prints it
# ---------------------------------------------------------------------------

_MAX_AUTHORS = 6


def format_entry(source: dict) -> str:
    """One source as its entry in a reference list (without its number).
    A source recorded as one line prints that line and its address; otherwise
    authors, title, where it appeared, year, volume and pages, and its DOI or
    address — each part only when the record has it."""
    url = (source.get("url") or "").strip()
    if source.get("text") and not source.get("title"):
        text = str(source["text"]).strip()
        return f"{text} {url}".strip() if url and url not in text else text
    parts: list[str] = []
    authors = [a for a in source.get("authors") or [] if a]
    if authors:
        shown = ", ".join(authors[:_MAX_AUTHORS]) + (", et al" if len(authors) > _MAX_AUTHORS else "")
        parts.append(shown.rstrip(".") + ".")
    if source.get("title"):
        parts.append(str(source["title"]).strip().rstrip(".") + ".")
    if source.get("container"):
        parts.append(str(source["container"]).strip().rstrip(".") + ".")
    where = str(source.get("year") or "")
    if source.get("volume"):
        where += f"; {source['volume']}"
        if source.get("issue"):
            where += f"({source['issue']})"
        if source.get("pages"):
            where += f":{source['pages']}"
    if where:
        parts.append(where + ".")
    if source.get("accessed"):
        parts.append(f"[Accessed: {source['accessed']}].")
    doi = normalize_doi(source.get("doi"))
    if doi:
        parts.append(f"https://doi.org/{doi}")
    elif url:
        parts.append(url)
    return " ".join(parts)


# What an entry of each kind must have for the citation check to call it
# complete.  A paper with a DOI is located by it; volume and pages are printed
# when recorded and are not required.
REQUIRED = {
    "paper": ("authors", "title", "container", "year"),
    "book": ("authors", "title", "year"),
    "report": ("title", "year"),
    "dataset": ("title", "year"),
    "software": ("title",),
}


def missing_fields(source: dict) -> list[str]:
    """The parts a source's entry lacks.  A source recorded as one line
    (``text``) is complete when it has that line and, for a website, its
    address."""
    kind = source.get("kind") or "other"
    if source.get("text") and not source.get("title"):
        return ["address"] if kind == "website" and not source.get("url") else []
    missing = [f for f in REQUIRED.get(kind, ("title",)) if source.get(f) in (None, "", [])]
    if kind in ("paper", "website", "dataset") and not (source.get("doi") or source.get("url")):
        missing.append("DOI or address")
    return missing


# ---------------------------------------------------------------------------
# Boilerplate citations in the Materials and Methods
# ---------------------------------------------------------------------------

def cite_boilerplate(subsection: str, paragraphs: list[str], library: dict | None = None) -> list[str]:
    """A Methods subsection's paragraphs with the library's entries cited
    where the library says (``cited_at``: at the first mention of some words
    in a subsection), as the published reports cite the statistical procedures
    ("the procedures of Williams [18, 19] and Dunnett [20]").

    A rule, not a writer: the same text gives the same citations, a subsection
    that does not use the words cites nothing, and a paragraph already cited
    is left as it is (so it can run again over stored text)."""
    library = load_library() if library is None else library
    # The words to look for (alternatives, the first that occurs wins) -> the
    # keys cited after them.
    wanted: dict[tuple[str, ...], list[str]] = {}
    for key, entry in library.items():
        for place in entry.get("cited_at") or []:
            after = place.get("after")
            if place.get("methods") == subsection and after:
                words = tuple(after) if isinstance(after, (list, tuple)) else (str(after),)
                wanted.setdefault(words, []).append(key)
    if not wanted or not paragraphs:
        return paragraphs
    out = list(paragraphs)
    for alternatives, keys in wanted.items():
        keys = [k for k in keys if not any(token(k) in p for p in out if isinstance(p, str))]
        if not keys:
            continue
        for words in alternatives:
            pattern = re.compile(r"\b" + re.escape(words) + r"\b")
            where = next(((i, m) for i, p in enumerate(out) if isinstance(p, str)
                          and (m := pattern.search(p))), None)
            if where:
                i, found = where
                out[i] = (out[i][:found.end()] + " " + "".join(token(k) for k in keys)
                          + out[i][found.end():])
                break
    return out
