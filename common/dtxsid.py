"""
common/dtxsid.py — the one definition of what a session identifier may look like.

Every study session is keyed by a DTXSID (the EPA CompTox chemical
identifier, e.g. DTXSID50469320) and stored under sessions/<DTXSID>/. Because
that id becomes a filesystem path component — and one route deletes the whole
directory tree it names — an unchecked id is a path-traversal hole: "..", or
"../../x" supplied in a URL segment or a JSON body, would walk out of the
sessions root before being read, written, or removed.

`validate_dtxsid` is the single gate. It is deliberately permissive about the
suffix (tests use ids like "DTXSID_TEST"; real ids are DTXSID + digits) and
strict about what matters for safety: the DTXSID prefix, a bounded length,
and a character set that cannot contain a path separator, a dot, whitespace
or a NUL. It returns the value unchanged so it can wrap any path expression
in place: ``SESSIONS_DIR / validate_dtxsid(dtxsid)``.

Callers:
  * pipeline/session_store.session_dir (and every direct
    ``SESSIONS_DIR / dtxsid`` site) — the sink-level defense; covers ids that
    arrive in request bodies as well as URLs.
  * web_routes/dtxsid_param.require_dtxsid — the FastAPI dependency that
    rejects a bad URL segment before the handler runs (400).
"""

import re

# Prefix fixed; suffix 1–64 chars from [A-Za-z0-9_-]. No '.', '/', '\\',
# whitespace or control characters can pass, so no traversal is possible.
DTXSID_RE = re.compile(r"^DTXSID[A-Za-z0-9_-]{1,64}$")


class InvalidDtxsid(ValueError):
    """Raised when a session id fails validation. Subclasses ValueError so
    generic ``except ValueError`` handlers still treat it as bad input; the
    FastAPI app maps it to a 400 (see web_routes/background_server)."""


def is_valid_dtxsid(value) -> bool:
    """True when ``value`` is a str matching DTXSID_RE."""
    return isinstance(value, str) and DTXSID_RE.match(value) is not None


def validate_dtxsid(value) -> str:
    """Return ``value`` unchanged if it is a well-formed session id, else raise
    InvalidDtxsid. The error message never echoes more than a short, repr'd
    prefix of the offending value (it may be attacker-controlled)."""
    if is_valid_dtxsid(value):
        return value
    shown = repr(value)[:80] if value is not None else "None"
    raise InvalidDtxsid(
        f"invalid session id {shown}: expected 'DTXSID' followed by 1-64 "
        f"letters, digits, '_' or '-'"
    )
