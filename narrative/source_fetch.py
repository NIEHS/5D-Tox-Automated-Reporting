"""
narrative/source_fetch.py — read a public document for the Background, and
keep what was read.

The Background's gatherer consults the documents a human author consults:
agency pages, regulations, reports, some of them PDFs.  This module reads one
address and keeps the answer:

  * a plain request first; a site that turns a program away (403/429/503, or
    no answer) is asked again with a real browser window
    (``tooling/browser_document.py``, run as its own process under the image's
    virtual display);
  * what was read is kept in ``OUTPUT_DIR/_background_documents`` with the
    day it was read, and served from there for a month.  A second Background
    of the same chemical asks no site again, and the entry's "Accessed" date
    is the day the document was actually read.

Only public identifiers of a chemical go into an address (its CAS number, its
name, a database's own id).  Nothing of a study's data is ever sent.
"""

from __future__ import annotations

import hashlib
import html as _html
import io
import json
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

_DIR = "_background_documents"
_KEPT_FOR = timedelta(days=30)
_TIMEOUT = 40
_BROWSER_TIMEOUT = 150
_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/120.0 Safari/537.36")
_REFUSED = (401, 403, 406, 429, 503)
_BROWSER_PYTHON = "/opt/playwright/venv/bin/python"
_BROWSER_SCRIPT = Path(__file__).resolve().parent.parent / "tooling" / "browser_document.py"


@dataclass
class Fetched:
    url: str
    content: bytes
    content_type: str
    fetched_at: str            # ISO day, UTC
    via: str                   # "request" | "browser"
    from_cache: bool = False

    @property
    def text(self) -> str:
        m = re.search(r"charset=([\w\-]+)", self.content_type or "", re.I)
        try:
            return self.content.decode(m.group(1) if m else "utf-8", errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")

    @property
    def is_pdf(self) -> bool:
        return self.content[:5] == b"%PDF-"

    @property
    def accessed(self) -> str:
        """The day it was read, as a reference entry prints it."""
        return accessed_words(self.fetched_at)

    @property
    def year(self) -> int:
        return int(self.fetched_at[:4])


def accessed_words(iso_day: str) -> str:
    day = datetime.strptime(iso_day[:10], "%Y-%m-%d")
    return f"{day.strftime('%B')} {day.day}, {day.year}"


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _dir() -> Path:
    from common.paths import OUTPUT_DIR
    return Path(OUTPUT_DIR) / _DIR


def _key(url: str, data) -> str:
    return hashlib.sha1((url + "\n" + json.dumps(data, sort_keys=True)).encode("utf-8")).hexdigest()


def _kept(url: str, data) -> Fetched | None:
    base = _dir() / _key(url, data)
    try:
        meta = json.loads(base.with_suffix(".json").read_text(encoding="utf-8"))
        day = datetime.strptime(meta["fetched_at"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - day > _KEPT_FOR:
            return None
        return Fetched(url, base.with_suffix(".bin").read_bytes(), meta.get("content_type", ""),
                       meta["fetched_at"], meta.get("via", "request"), from_cache=True)
    except (OSError, ValueError, KeyError):
        return None


def _keep(got: Fetched, data) -> None:
    try:
        base = _dir() / _key(got.url, data)
        base.parent.mkdir(parents=True, exist_ok=True)
        base.with_suffix(".bin").write_bytes(got.content)
        base.with_suffix(".json").write_text(json.dumps({
            "url": got.url, "content_type": got.content_type, "fetched_at": got.fetched_at,
            "via": got.via, "bytes": len(got.content)}, indent=1) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("could not keep %s: %s", got.url, exc)


def _by_request(url: str, data, headers) -> tuple[Fetched | None, int]:
    send = {"User-Agent": _AGENT, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9",
            **(headers or {})}
    try:
        if data is None:
            r = requests.get(url, headers=send, timeout=_TIMEOUT)
        else:
            r = requests.post(url, data=data, headers=send, timeout=_TIMEOUT)
    except requests.RequestException as exc:
        logger.info("no answer from %s: %s", url, exc)
        return None, 0
    if r.status_code != 200:
        return None, r.status_code
    return Fetched(url, r.content, r.headers.get("content-type", ""), today(), "request"), 200


def _by_browser(url: str) -> Fetched | None:
    if not (shutil.which("with-display") and Path(_BROWSER_PYTHON).exists()
            and _BROWSER_SCRIPT.exists()):
        return None
    mode = "file" if url.lower().split("?")[0].endswith(".pdf") else "page"
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "document"
        try:
            run = subprocess.run(
                ["with-display", _BROWSER_PYTHON, str(_BROWSER_SCRIPT), url, str(out), mode],
                capture_output=True, text=True, timeout=_BROWSER_TIMEOUT)
            answer = json.loads((run.stdout or "").strip().splitlines()[-1])
        except (subprocess.SubprocessError, OSError, ValueError, IndexError) as exc:
            logger.info("the browser could not read %s: %s", url, exc)
            return None
        if answer.get("status") != 200 or not out.exists():
            logger.info("the browser was answered %s for %s", answer, url)
            return None
        return Fetched(url, out.read_bytes(), answer.get("content_type", ""), today(), "browser")


def fetch(url: str, *, data: dict | None = None, headers: dict | None = None,
          browser: bool = True, fresh: bool = False) -> Fetched | None:
    """The document at ``url`` (a POST when ``data`` is given), or None when it
    could not be read.  ``browser``: ask again with a browser when the plain
    request is refused or unanswered (never for a POST).  ``fresh``: ask the
    site even if a copy is kept."""
    if not fresh:
        kept = _kept(url, data)
        if kept is not None:
            return kept
    got, status = _by_request(url, data, headers)
    if got is None and browser and data is None and (status == 0 or status in _REFUSED):
        got = _by_browser(url)
    if got is not None:
        _keep(got, data)
    return got


# ---------------------------------------------------------------------------
# Reading what was fetched
# ---------------------------------------------------------------------------

def html_text(markup: str) -> str:
    """The readable text of a page, a block to a line."""
    markup = re.sub(r"<(script|style|noscript|svg)\b.*?</\1>", " ", markup, flags=re.S | re.I)
    markup = re.sub(r"<!--.*?-->", " ", markup, flags=re.S)
    markup = re.sub(r"<(?:p|div|br|h[1-6]|li|tr|table|section|dt|dd)\b[^>]*>", "\n", markup,
                    flags=re.I)
    markup = re.sub(r"</(?:td|th)>", " | ", markup, flags=re.I)
    text = _html.unescape(re.sub(r"<[^>]+>", " ", markup)).replace(" ", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return re.sub(r"\n{2,}", "\n", text).strip()


def pdf_text(content: bytes, first_page: int = 1, last_page: int | None = None) -> str:
    """The text of a PDF's pages ``first_page`` … ``last_page`` (1-based)."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        pages = reader.pages[first_page - 1:last_page]
        text = "\n".join((page.extract_text() or "") for page in pages)
    except Exception as exc:  # noqa: BLE001 — a PDF that cannot be read gives no text
        logger.warning("PDF not read: %s", exc)
        return ""
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def between(text: str, start: str, end: str | None = None, limit: int = 6000) -> str:
    """The part of ``text`` from the first ``start`` (a regular expression) to
    the next ``end``, at most ``limit`` characters; "" when ``start`` is absent."""
    m = re.search(start, text, flags=re.I)
    if not m:
        return ""
    rest = text[m.start():]
    if end:
        e = re.search(end, rest[len(m.group(0)):], flags=re.I)
        if e:
            rest = rest[:len(m.group(0)) + e.start()]
    return rest[:limit].strip()
