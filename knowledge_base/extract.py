"""
LLM extraction from papers: abstracts, or full text when it was fetched.

What to extract is the crawl query's (knowledge_base.crawl_queries, ``extract``):
the analyst the model is told it is (``system``) and the fields, each with what
it holds (``describe``, ``describe_fulltext``), its type (list, text, number)
and how its values are normalised (``normalize``).  Nothing here knows the
topic.  The consensus counts one list field per paper (``consensus``).

The model runs locally (Ollama) or through the approved gateway (Claude,
styling_export.llm_endpoints — the egress guard), several workers at once.
"""

import copy
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

import requests

from styling_export.llm_endpoints import AnthropicEndpoint, assert_local_ollama, resolve_anthropic_api_key


# ---------------------------------------------------------------------------
# Ollama client
# ---------------------------------------------------------------------------

@dataclass
class OllamaEndpoint:
    name: str
    url: str            # e.g. "http://localhost:11434"
    model: str          # e.g. "qwen2.5:14b"
    timeout: int = 120  # seconds
    weight: int = 1     # relative speed weight for work distribution

    def generate(self, prompt: str, system: str = "",
                 temperature: float = 0.1) -> str:
        """Send a prompt to Ollama and return the response text."""
        assert_local_ollama(self.url, self.model)
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": 2048,
            },
        }
        if system:
            payload["system"] = system

        try:
            r = requests.post(
                f"{self.url}/api/generate",
                json=payload,
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json().get("response", "")
        except requests.RequestException as e:
            print(f"  [{self.name} error: {e}]")
            return ""

    def is_available(self) -> bool:
        """Check if this endpoint is reachable."""
        try:
            r = requests.get(f"{self.url}/api/tags", timeout=5)
            return r.status_code == 200
        except requests.RequestException:
            return False


# ---------------------------------------------------------------------------
# Default endpoints
# ---------------------------------------------------------------------------

LOCAL_OLLAMA = OllamaEndpoint(
    name="local-3080ti",
    url="http://localhost:11434",
    model="qwen2.5:14b",
    weight=2,  # ~2x faster than the AMD
)

REMOTE_OLLAMA = OllamaEndpoint(
    name="remote-6900xt",
    url="http://localhost:11435",  # via SSH tunnel
    model="qwen2.5:14b",
    weight=1,
)


# ---------------------------------------------------------------------------
# Claude endpoint (via NIEHS litellm proxy) — used when Ollama is unavailable
# ---------------------------------------------------------------------------

# Bulk extraction is a high-volume, structured-JSON task, so pin the fast/cheap
# tier rather than inheriting ANTHROPIC_MODEL (opus). Canonical id; the proxy
# name (claude-haiku-4.5) is produced by resolve_model_name() in llm_endpoints.
CLAUDE_EXTRACTION_MODEL = "claude-haiku-4-5"


@dataclass
class ClaudeExtractionEndpoint(AnthropicEndpoint):
    """AnthropicEndpoint adapted to the ParallelExtractionEngine's duck-typed
    interface: adds `url` (display only) and `weight` (round-robin share), and
    wraps generate() to match OllamaEndpoint's graceful-failure contract.
    """

    url: str = "litellm-proxy"
    weight: int = 1

    def generate(self, prompt: str, system: str = "",
                 temperature: float | None = None) -> str:
        # The engine's worker loop has no per-paper error handling — it relies on
        # generate() returning "" on failure (as OllamaEndpoint does). An uncaught
        # exception would propagate through future.result() and abort the whole
        # run, so swallow errors here and back off on transient proxy throttling.
        for attempt in range(4):
            try:
                return super().generate(prompt, system=system, temperature=temperature)
            except Exception as e:
                msg = str(e).lower()
                transient = any(t in msg for t in
                                ("429", "overloaded", "rate", "timeout",
                                 "connection", "529"))
                if not transient or attempt == 3:
                    print(f"  [{self.name} error: {e}]")
                    return ""
                time.sleep(2 ** attempt)  # 1s, 2s, 4s
        return ""

    def is_available(self) -> bool:
        return bool(resolve_anthropic_api_key())


def build_claude_endpoints(n_workers: int = 6,
                           model: str = CLAUDE_EXTRACTION_MODEL) -> list:
    """Build N identical Claude endpoints.

    The engine runs one thread per endpoint (a GPU serializes, so Ollama used 2).
    The litellm proxy accepts concurrent requests, so N identical Claude endpoints
    give N concurrent extraction workers via the existing round-robin.
    """
    return [
        ClaudeExtractionEndpoint(
            name=f"claude-{i + 1}",
            model=model,
            max_tokens=2048,
            temperature=0.1,
        )
        for i in range(n_workers)
    ]


# ---------------------------------------------------------------------------
# Prompts, from the query's fields
# ---------------------------------------------------------------------------

_EMPTY = {"list": [], "text": "", "number": 0.0}


def _field_schema(fields: list[dict], fulltext: bool) -> str:
    lines = []
    for f in fields:
        if f.get("fulltext_only") and not fulltext:
            continue
        describe = (f.get("describe_fulltext") if fulltext else None) or f["describe"]
        kind = f.get("type", "list")
        value = (json.dumps([describe]) if kind == "list" else
                 describe if kind == "number" else json.dumps(describe))
        lines.append(f'  "{f["name"]}": {value}')
    return "{\n" + ",\n".join(lines) + "\n}"


def prompts(spec: dict) -> tuple[str, str, str]:
    """(system, abstract prompt, full-text prompt) for an extract spec; the
    prompts are format strings over title, year and abstract / text."""
    system = spec.get("system") or (
        "You are a scientific literature analyst.\n"
        "You extract structured information from papers with precision.\n"
        "Always respond in valid JSON. Never add commentary outside the JSON.")
    fields = spec["fields"]
    tail = ("Respond with ONLY a JSON object (no markdown, no explanation) with these fields:\n")
    abstract = ("Analyze this scientific paper abstract and extract structured information.\n\n"
                "Title: {title}\nYear: {year}\nAbstract: {abstract}\n\n" + tail
                + _field_schema(fields, False).replace("{", "{{").replace("}", "}}"))
    fulltext = ("Analyze this scientific paper and extract structured information.\n\n"
                "Title: {title}\nYear: {year}\n\nFull text (may be truncated):\n{text}\n\n"
                + tail + _field_schema(fields, True).replace("{", "{{").replace("}", "}}"))
    return system, abstract, fulltext


def _record(paper: dict, spec: dict) -> dict:
    """An empty extraction record for a paper: its identity, every field empty."""
    rec = {"paper_id": paper["paper_id"], "title": paper.get("title", ""),
           "year": paper.get("year")}
    for f in spec["fields"]:
        rec[f["name"]] = copy.copy(_EMPTY[f.get("type", "list")])
    rec.update(raw_response="", endpoint_used="", text_source="")
    return rec


def _fill(rec: dict, data: dict, spec: dict, fulltext: bool) -> None:
    """Copy a model's answer into a record, field by field, by type."""
    for f in spec["fields"]:
        name, kind = f["name"], f.get("type", "list")
        if f.get("fulltext_only") and not fulltext:
            continue
        value = data.get(name)
        if kind == "list":
            rec[name] = [str(v) for v in value if v] if isinstance(value, list) else []
            if (f.get("normalize") or {}).get("case") == "upper":
                rec[name] = [v.upper() for v in rec[name]]
        elif kind == "number":
            try:
                rec[name] = float(value)
            except (TypeError, ValueError):
                rec[name] = 0.0
        else:
            rec[name] = "" if value is None else str(value)


def _merge(records: list[dict], spec: dict) -> dict:
    """Merge a paper's chunk records: list fields unioned in order; text and
    numbers from the first chunk, except a number field's maximum."""
    if len(records) == 1:
        return records[0]
    merged = dict(records[0])
    for f in spec["fields"]:
        name, kind = f["name"], f.get("type", "list")
        if kind == "list":
            seen: dict[str, None] = {}
            for r in records:
                for v in r.get(name) or []:
                    seen[v] = None
            merged[name] = list(seen)
        elif kind == "number":
            merged[name] = max(r.get(name) or 0.0 for r in records)
    return merged


# ---------------------------------------------------------------------------
# Text chunking for long full texts
# ---------------------------------------------------------------------------

def _chunk_text_for_extraction(text: str, max_chunk_chars: int = 30_000,
                               overlap: int = 2_000) -> list[str]:
    """
    Tile long text into sequential overlapping windows covering the WHOLE text.

    If text <= max_chunk_chars: return as a single chunk. Otherwise walk the
    entire text in windows of max_chunk_chars that share `overlap` chars with
    their neighbour, so no content is dropped and boundary context is preserved.
    Downstream, extract_one() runs each window and _merge_extractions() unions
    the results, so an arbitrary window count is fine.
    """
    if len(text) <= max_chunk_chars:
        return [text]

    chunks: list[str] = []
    step = max_chunk_chars - overlap
    start = 0
    n = len(text)
    while start < n:
        end = start + max_chunk_chars
        chunks.append(text[start:end])
        if end >= n:
            break
        start += step
    return chunks


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------

def parse_json_response(text: str) -> dict | None:
    """Try to extract JSON from LLM response, handling common issues."""
    text = text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
    return None


# ---------------------------------------------------------------------------
# Single-paper extraction (stateless, used by workers)
# ---------------------------------------------------------------------------

def extract_one(paper: dict, endpoint, spec: dict,
                full_text: str | None = None, text_source: str = "") -> tuple[dict, bool | None]:
    """Extract a paper's fields (``spec``: the query's extract section) with one
    endpoint: from its full text, chunked, when there is one; else from its
    abstract.  Returns (the extraction record, answered): answered is None when
    the paper has nothing to extract from (no full text, no abstract), False
    when the model did not answer every part with a JSON object of the fields
    (no reply, or one that is not such an object) — the record then holds
    only what it did answer, and is not kept (knowledge_base.run_crawl)."""
    system, abstract_prompt, fulltext_prompt = prompts(spec)
    chunk = spec.get("chunk") or {}
    title, year = paper.get("title", ""), paper.get("year")
    rec = _record(paper, spec)

    if full_text and len(full_text.strip()) > 200:
        rec["text_source"] = text_source or "fulltext"
        chunks, answered = [], True
        for part in _chunk_text_for_extraction(full_text, chunk.get("max_chars", 30_000),
                                               chunk.get("overlap", 2_000)):
            response = endpoint.generate(
                fulltext_prompt.format(title=title, year=year or "unknown", text=part),
                system=system)
            data = parse_json_response(response) if response else None
            if not isinstance(data, dict):
                answered = False
                continue
            part_rec = _record(paper, spec)
            part_rec.update(raw_response=response, endpoint_used=endpoint.name,
                            text_source=rec["text_source"])
            _fill(part_rec, data, spec, fulltext=True)
            chunks.append(part_rec)
        return (_merge(chunks, spec) if chunks else rec), answered

    rec["text_source"] = "abstract"
    abstract = paper.get("abstract")
    if not abstract or len(abstract.strip()) < 50:
        return rec, None
    response = endpoint.generate(
        abstract_prompt.format(title=title, year=year or "unknown", abstract=abstract),
        system=system)
    data = parse_json_response(response) if response else None
    if not isinstance(data, dict):
        return rec, False
    rec.update(raw_response=response, endpoint_used=endpoint.name)
    _fill(rec, data, spec, fulltext=False)
    return rec, True


# ---------------------------------------------------------------------------
# Parallel extraction engine
# ---------------------------------------------------------------------------

class ParallelExtractionEngine:
    """
    Distributes paper extraction across endpoints (local Ollama GPUs, or N
    concurrent gateway workers).  Each endpoint gets its own thread; papers are
    assigned by weighted round-robin.  ``spec`` is the query's extract section.
    """

    def __init__(self, spec: dict, endpoints: list | None = None):
        self.spec = spec
        if endpoints is None:
            endpoints = [LOCAL_OLLAMA, REMOTE_OLLAMA]

        # Only keep endpoints that are reachable
        self.endpoints = []
        for ep in endpoints:
            if ep.is_available():
                print(f"  [OK] {ep.name} ({ep.model} @ {ep.url})")
                self.endpoints.append(ep)
            else:
                print(f"  [DOWN] {ep.name} ({ep.url}) — skipping")

        if not self.endpoints:
            raise RuntimeError("No extraction endpoint available")

        self.print_lock = Lock()
        self.stats = {"processed": 0, "failed": 0, "skipped_no_abstract": 0}
        self.stats_lock = Lock()

    def _worker(self, paper: dict, endpoint, index: int, total: int,
                full_text: str | None = None, text_source: str = "") -> dict:
        """Process one paper on one endpoint."""
        rec, answered = extract_one(paper, endpoint, self.spec,
                                    full_text=full_text, text_source=text_source)
        with self.print_lock:
            status = {True: "", False: " [FAILED]", None: " [no abstract]"}[answered]
            print(f"[{index}/{total}] [{endpoint.name}] [{rec['text_source']}] "
                  f"{(paper.get('title') or '')[:60]}...{status}")
        with self.stats_lock:
            self.stats[{True: "processed", False: "failed",
                        None: "skipped_no_abstract"}[answered]] += 1
        return rec

    def process_papers(self, papers: list[dict],
                       fulltext_results: dict | None = None) -> list[dict]:
        """Extract every paper, in parallel across the endpoints; records come
        back in the papers' order.  ``fulltext_results``: paper_id ->
        fulltext.FullTextResult."""
        fulltext_results = fulltext_results or {}
        total = len(papers)
        weighted_seq: list = []
        for ep in self.endpoints:
            weighted_seq.extend([ep] * ep.weight)
        queues: dict[str, list[tuple[dict, int]]] = {ep.name: [] for ep in self.endpoints}
        for i, paper in enumerate(papers):
            queues[weighted_seq[i % len(weighted_seq)].name].append((paper, i + 1))

        results: dict[str, dict] = {}

        def run_queue(endpoint, queue):
            for paper, idx in queue:
                ft = fulltext_results.get(paper["paper_id"])
                results[paper["paper_id"]] = self._worker(
                    paper, endpoint, idx, total,
                    full_text=ft.text if ft else None, text_source=ft.source if ft else "")

        start_time = time.time()
        with ThreadPoolExecutor(max_workers=len(self.endpoints)) as pool:
            for f in [pool.submit(run_queue, ep, queues[ep.name]) for ep in self.endpoints]:
                f.result()
        print(f"\nExtracted {total} papers in {time.time() - start_time:.0f}s: {self.stats}")
        return [results[p["paper_id"]] for p in papers if p["paper_id"] in results]


# ---------------------------------------------------------------------------
# Normalisation (each field's ``normalize`` rules)
# ---------------------------------------------------------------------------

def normalizer(field_spec: dict | None):
    """A function normalising one value of a field by its ``normalize`` rules:
    trim; ``case`` (upper | lower); "" when it contains a ``drop_containing``
    phrase; its ``aliases`` entry; trailing ``strip`` characters removed; its
    alias again.  A field with no rules: trimmed only."""
    rules = (field_spec or {}).get("normalize") or {}
    case = rules.get("case")
    drop = [d.upper() if case == "upper" else d.lower() if case == "lower" else d
            for d in rules.get("drop_containing") or []]
    aliases = rules.get("aliases") or {}
    if case == "lower":
        aliases = {k.lower(): v for k, v in aliases.items()}
    strip = rules.get("strip") or ""

    def normalize(value) -> str:
        v = str(value).strip()
        if case == "upper":
            v = v.upper()
        elif case == "lower":
            v = v.lower()
        if any(d in v for d in drop):
            return ""
        if v in aliases:
            return aliases[v]
        v = v.rstrip(strip) if strip else v
        return aliases.get(v, v)

    return normalize


def field_spec(spec: dict, name: str) -> dict | None:
    return next((f for f in spec.get("fields") or [] if f["name"] == name), None)


# ---------------------------------------------------------------------------
# Consensus: how many papers name each value of a field
# ---------------------------------------------------------------------------

def merge_extractions(paths: list[Path]) -> list[dict]:
    """Every crawl's extraction records, one per paper (the first crawl's wins)."""
    seen: set[str] = set()
    merged: list[dict] = []
    for path in paths:
        try:
            records = json.loads(Path(path).read_text())
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"  [skip] {path}: {e}")
            continue
        for rec in records:
            pid = rec.get("paper_id", "")
            if pid and pid not in seen:
                seen.add(pid)
                merged.append(rec)
    return merged


def consensus(extractions: list[dict], extract_spec: dict, cons: dict) -> dict:
    """The consensus of ``cons["field"]`` (e.g. genes) over the papers: each
    normalised value with the papers naming it and the ``by`` values (e.g.
    organs) of those papers; ``strong`` (named by at least cons.strong papers),
    ``moderate`` (at least cons.moderate), the count of single mentions, and
    the top values per ``by`` value."""
    name, by = cons["field"], cons.get("by")
    norm = normalizer(field_spec(extract_spec, name))
    norm_by = normalizer(field_spec(extract_spec, by)) if by else None
    strong_at, moderate_at = cons.get("strong", 3), cons.get("moderate", 2)

    papers_of: dict[str, list[dict]] = {}
    by_of: dict[str, set[str]] = {}
    for rec in extractions:
        bys = {norm_by(b) for b in rec.get(by) or []} - {""} if by else set()
        for raw in rec.get(name) or []:
            value = norm(raw)
            if not value:
                continue
            papers_of.setdefault(value, []).append({
                "paper_id": rec["paper_id"], "title": rec.get("title"),
                "year": rec.get("year"), "confidence": rec.get("confidence", 0)})
            by_of.setdefault(value, set()).update(bys)

    strong, moderate, single = {}, {}, 0
    for value, papers in papers_of.items():
        entry = {"count": len(papers), "by": sorted(by_of.get(value, set())),
                 "years": sorted({p["year"] for p in papers if p.get("year")}),
                 "papers": papers}
        if len(papers) >= strong_at:
            strong[value] = entry
        elif len(papers) >= moderate_at:
            moderate[value] = entry
        else:
            single += 1

    per_by: dict[str, dict[str, int]] = {}
    for value, bys in by_of.items():
        for b in bys:
            per_by.setdefault(b, {})[value] = len(papers_of[value])

    def ranked(d):
        return dict(sorted(d.items(), key=lambda x: x[1]["count"], reverse=True))

    return {
        "field": name, "by": by, "thresholds": {"strong": strong_at, "moderate": moderate_at},
        "strong": ranked(strong), "moderate": ranked(moderate), "single_mentions": single,
        "top_by": {b: dict(sorted(v.items(), key=lambda x: x[1], reverse=True)[:20])
                   for b, v in sorted(per_by.items())},
        "total_unique": len(papers_of), "papers": len(extractions),
    }
