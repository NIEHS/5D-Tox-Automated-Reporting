"""
pipeline.bmd_review — an unreliable estimate of potency (UREP) is a reviewer's
decision; the screen only proposes it.

The NIEHS reports define UREP as "a label based on review by a subject matter
expert and rejection of BMD modeling results" (NIEHS-07 … 10), and no single
ratio reproduces those decisions: experts rejected BMDs 10-fold below the NOEL
(NIEHS-07 globulin, NIEHS-08 cholesterol) and accepted one 25-fold below it
(NIEHS-08 female alkaline phosphatase).  So:

  screen          every apical BMD, whatever its source (.bm2, ToxicR fill,
                  BMDS 2.7), more than ANOMALY_RATIO_THRESHOLD below its NOEL
                  (else its LOEL) is FLAGGED, with its fold range
                  (NOEL/BMD to LOEL/BMD, as the reports print it);
  apply_reviews   a flagged BMD a reviewer rejected becomes UREP on its row,
                  so every surface (Tables 2–7, the narratives, the BMD
                  summary) agrees; one a reviewer accepted stays a number; one
                  with no decision is PENDING and closes the publish gate
                  (workflow.engine.publish_readiness).

A decision holds for the BMD it was made on: a reprocess that changes the
value makes the flag pending again (``current``).  Decisions are recorded in
``bmd_reviews.json`` with the reason (a person's, required by the safeguards)
and the earlier decisions kept in its history; the last screen's flags are in
``bmd_flags.json``, written by Process.
"""

from __future__ import annotations

import hashlib
import json
import math

from common.clock import now_iso
from narrative.narrative_helpers import ANOMALY_RATIO_THRESHOLD

REVIEWS_FILE = "bmd_reviews.json"
FLAGS_FILE = "bmd_flags.json"

UNRELIABLE = "unreliable"
RELIABLE = "reliable"
DECISIONS = (UNRELIABLE, RELIABLE)


def flag_key(sex: str, platform: str, label: str) -> str:
    """One endpoint's identity: ``Male|Clinical Chemistry|Cholesterol``."""
    return f"{sex}|{platform}|{label}"


def _num(value) -> float | None:
    try:
        f = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f > 0 else None


def screen(platform_tables: dict[str, dict[str, list]],
           threshold: float = ANOMALY_RATIO_THRESHOLD) -> list[dict]:
    """The flagged BMDs: a numeric BMD more than ``threshold`` times below its
    NOEL (else its LOEL).  Each flag: key, sex, platform, label, bmd, bmdl,
    noel, loel, and the fold range (NOEL/BMD, LOEL/BMD)."""
    flags = []
    for platform, sex_rows in sorted(platform_tables.items()):
        for sex, rows in sex_rows.items():
            for row in rows:
                bmd = _num(row.bmd_str)
                if bmd is None:
                    continue
                noel, loel = _num(row.noel), _num(row.loel)
                reference = noel or loel
                if reference is None or bmd >= reference / threshold:
                    continue
                flags.append({
                    "key": flag_key(sex, platform, row.label),
                    "sex": sex, "platform": platform, "label": row.label,
                    "bmd": row.bmd_str, "bmdl": row.bmdl_str,
                    "noel": row.noel, "loel": row.loel,
                    "fold": [round(noel / bmd) if noel else None,
                             round(loel / bmd) if loel else None],
                })
    return flags


def current(flag: dict, reviews: dict) -> dict | None:
    """The reviewer's decision on ``flag``, if it was made on this BMD."""
    decision = (reviews.get("decisions") or {}).get(flag["key"])
    if decision and decision.get("bmd") == flag["bmd"] and decision.get("decision") in DECISIONS:
        return decision
    return None


def apply_reviews(platform_tables: dict[str, dict[str, list]], reviews: dict | None,
                  threshold: float = ANOMALY_RATIO_THRESHOLD) -> list[dict]:
    """Screen the rows and apply the current decisions to them.  A rejected
    BMD becomes UREP on its row (BMD, BMDL and status), the reviewed values and
    fold range kept on ``row._urep``; an undecided one is marked
    ``row._bmd_review_pending``.  Returns the flags, each with
    ``decision`` (unreliable | reliable | None: pending) and ``reason``."""
    reviews = reviews or {}
    flags = screen(platform_tables, threshold)
    rows = {flag_key(sex, platform, row.label): row
            for platform, sex_rows in platform_tables.items()
            for sex, rs in sex_rows.items() for row in rs}
    for row in rows.values():
        row._bmd_review_pending = False
    for flag in flags:
        decision = current(flag, reviews)
        flag["decision"] = decision["decision"] if decision else None
        flag["reason"] = decision.get("reason") if decision else None
        row = rows[flag["key"]]
        if flag["decision"] == UNRELIABLE:
            row._urep = {"bmd": row.bmd_str, "bmdl": row.bmdl_str, "fold": flag["fold"],
                         "reason": flag["reason"]}
            row.bmd_str = row.bmdl_str = row.bmd_status = "UREP"
        elif flag["decision"] is None:
            row._bmd_review_pending = True
    return flags


def pending(flags: list[dict]) -> list[dict]:
    """The flags no reviewer has decided (on the current BMD)."""
    return [f for f in flags if not f.get("decision")]


def reviews_hash(reviews: dict | None) -> str:
    """A fingerprint of the decisions, for the cache keys of what they change."""
    decisions = (reviews or {}).get("decisions") or {}
    blob = json.dumps({k: [d.get("decision"), d.get("bmd")] for k, d in sorted(decisions.items())},
                      sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def with_reviews(key: str, reviews: dict | None) -> str:
    """``key`` extended with the decisions' fingerprint; unchanged when there
    are none, so a study no one has reviewed keeps its caches."""
    return f"{key}:{reviews_hash(reviews)}" if (reviews or {}).get("decisions") else key


def record_reviews(store, dtxsid: str, decisions: dict[str, dict], flags: list[dict]) -> dict:
    """Record ``{key: {decision, reason}}`` for flags of the last screen, each
    tied to the BMD it was made on; a replaced decision goes to the history.
    Written as given: that each key is flagged, each decision known and each
    reason given is the safeguards' (safeguards.bmd_review)."""
    by_key = {f["key"]: f for f in flags}
    reviews = store.read_json(dtxsid, REVIEWS_FILE) or {}
    held = reviews.setdefault("decisions", {})
    history = reviews.setdefault("history", [])
    at = now_iso()
    for key, given in decisions.items():
        if key in held:
            history.append({"key": key, **held[key]})
        held[key] = {"decision": given["decision"], "reason": given["reason"].strip(),
                     "bmd": by_key[key]["bmd"], "fold": by_key[key]["fold"], "at": at}
    store.write_json(dtxsid, REVIEWS_FILE, reviews)
    return reviews


def unsettled(flags: list[dict], reviews: dict | None) -> list[dict]:
    """What keeps the report from publishing, one entry per flag: ``pending``
    (no decision on the current BMD) or ``not_applied`` (a decision recorded
    since the last Process, which has not yet changed the report)."""
    out = []
    for f in flags:
        decision = current(f, reviews or {})
        if decision is None:
            out.append({"key": f["key"], "reason": "bmd_review_pending"})
        elif decision["decision"] != f.get("decision"):
            out.append({"key": f["key"], "reason": "bmd_review_not_applied"})
    return out
