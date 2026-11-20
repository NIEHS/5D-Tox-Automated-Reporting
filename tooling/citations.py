#!/usr/bin/env python3
"""tooling/citations.py — the citation check and the sources, from the command
line (ADR-0038).

    python -m tooling.citations check DTXSID6020430            # check, record, print
    python -m tooling.citations check DTXSID6020430 --no-network --no-save
    python -m tooling.citations status DTXSID6020430
    python -m tooling.citations add DTXSID6020430_rat --by "A. Person" \\
        --kind paper --authors "Smith J; Lee K" --title "..." --container "Toxicol Sci" \\
        --year 2019 --doi 10.1093/toxsci/kfz001
    python -m tooling.citations kb-dois baseline-2026-05       # the whole knowledge base

``check`` reads the report as it is presented and records the result in its
session (``citations_check.json``); the publish gate waits for a check that
holds and passed.  It exits 1 when the check found errors.

``add`` records a source a person adds to a study (``sources.json``) and
prints the token text cites it by.

``kb-dois`` asks the DOI system about every DOI of a knowledge base and keeps
the answers (OUTPUT_DIR/_source_lookups.json).  The check of a study reads
those answers and never asks about the papers one study cites.
"""

from __future__ import annotations

import argparse
import sys


def _check(args) -> int:
    from rendering.citations_validate import validate

    record = validate(args.dtxsid, view=args.view, network=not args.no_network,
                      checked_by=args.by, save=not args.no_save)
    c = record["counts"]
    print(f"{args.dtxsid}: {'PASSED' if record['passed'] else 'FAILED'} — "
          f"{c['citations']} citations of {c['cited_sources']} sources; "
          f"{c['listed']} listed; {c['recorded_sources']} recorded; "
          f"{c['errors']} errors, {c['warnings']} warnings, {c['notes']} notes")
    for f in record["findings"]:
        print(f"  {f['severity'].upper():7} {f['code']}: {f['message']}")
        for sentence in f.get("sentences") or []:
            print(f"            > {sentence}")
    if args.list:
        for r in record["references"]:
            state = r.get("doi_state") or r.get("address_state") or ""
            print(f"  [{r['number']}] ({r['origin']}; cited {r['cited']}x; {state}) {r['entry']}")
    print("  Not judged by this check:")
    for line in record["not_judged"]:
        print(f"    - {line}")
    if not args.no_save:
        print(f"  recorded in the session as citations_check.json ({record['checked_at']})")
    return 0 if record["passed"] else 1


def _status(args) -> int:
    from rendering.citations_validate import PASSED, status

    found = status(args.dtxsid)
    print(f"{args.dtxsid}: {found['state']}"
          + (f" (checked {found['checked_at']}"
             f"{' by ' + found['checked_by'] if found.get('checked_by') else ''})"
             if found.get("checked_at") else ""))
    return 0 if found["state"] == PASSED else 1


def _add(args) -> int:
    from common.clock import now_iso
    from common.dtxsid import validate_dtxsid
    from common.paths import SESSIONS_DIR
    from narrative.sources import add_session_source, missing_fields, token

    session_dir = SESSIONS_DIR / validate_dtxsid(args.dtxsid)
    if not session_dir.is_dir():
        print(f"no study {args.dtxsid}", file=sys.stderr)
        return 2
    record = {"kind": args.kind, "title": args.title, "container": args.container,
              "year": args.year, "volume": args.volume, "issue": args.issue,
              "pages": args.pages, "doi": args.doi, "url": args.url, "accessed": args.accessed,
              "authors": [a.strip() for a in (args.authors or "").split(";") if a.strip()]}
    record = {k: v for k, v in record.items() if v not in (None, "", [])}
    missing = missing_fields(record)
    if missing:
        print(f"not added: the entry lacks {', '.join(missing)}", file=sys.stderr)
        return 2
    slug = add_session_source(session_dir, record, added_by=args.by, added_at=now_iso())
    print(f"recorded as {slug}; text cites it as {token(slug)}")
    return 0


def _kb_dois(args) -> int:
    from knowledge_base.bibliography import dois_of
    from narrative import source_lookup as sl

    dois = dois_of(args.name)
    print(f"{args.name}: {len(dois)} DOIs", flush=True)
    states = sl.check_dois(dois, workers=args.workers,
                           progress=lambda i, n: print(f"  {i}/{n}", flush=True))
    by_state: dict[str, list[str]] = {}
    for doi, state in states.items():
        by_state.setdefault(state, []).append(doi)
    for state in (sl.REGISTERED, sl.NOT_REGISTERED, sl.NOT_CHECKED):
        found = by_state.get(state, [])
        print(f"  {state}: {len(found)}")
        if state != sl.REGISTERED:
            for doi in found[:50]:
                print(f"      {doi}")
    return 0 if not by_state.get(sl.NOT_REGISTERED) else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="check a report's citations and record the result")
    check.add_argument("dtxsid")
    check.add_argument("--view", default=None)
    check.add_argument("--by", default=None, help="who makes the check")
    check.add_argument("--no-network", action="store_true",
                       help="ask nothing of the DOI system or the addresses")
    check.add_argument("--no-save", action="store_true", help="print only; record nothing")
    check.add_argument("--list", action="store_true", help="print the reference list as derived")
    check.set_defaults(run=_check)

    status = sub.add_parser("status", help="where a report's citation check stands")
    status.add_argument("dtxsid")
    status.set_defaults(run=_status)

    add = sub.add_parser("add", help="record a source a person adds to a study")
    add.add_argument("dtxsid")
    add.add_argument("--by", required=True, help="who adds it")
    add.add_argument("--kind", required=True)
    for name in ("authors", "title", "container", "year", "volume", "issue", "pages",
                 "doi", "url", "accessed"):
        add.add_argument(f"--{name}")
    add.set_defaults(run=_add)

    kb = sub.add_parser("kb-dois", help="ask the DOI system about a whole knowledge base")
    kb.add_argument("name")
    kb.add_argument("--workers", type=int, default=8)
    kb.set_defaults(run=_kb_dois)

    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except Exception as e:  # noqa: BLE001 — a report that cannot be read is said, not traced
        from workflow.errors import StepError
        if not isinstance(e, (StepError, ValueError, FileNotFoundError)):
            raise
        print(f"{getattr(args, 'dtxsid', None) or getattr(args, 'name', '')}: not done — {e}",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
