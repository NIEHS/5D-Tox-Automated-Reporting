"""
Run a named crawl from the command line: a saved crawl query into a named
knowledge base (knowledge_base.run_crawl), through the safeguards
(safeguards.guarded.run_crawl).

    python -m tooling.run_crawl <query> --as <crawl name> [--resume] [--confirm-unpublished]

Refused before anything runs when the knowledge base's name cannot take the
run, or the query's searches would send genes of an unpublished study's
results that no crawl has sent before (``--confirm-unpublished`` when they are
there for another reason).  Exits 0 when the knowledge base is finished, 1
when a stage could not run (``--resume`` continues it), 2 when refused.
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run a named crawl query into a named knowledge base.")
    ap.add_argument("query", help="a query in crawl_queries/ (its name, without .yaml)")
    ap.add_argument("--as", dest="name", required=True, help="the knowledge base's name")
    ap.add_argument("--resume", action="store_true",
                    help="continue an unfinished knowledge base of this name")
    ap.add_argument("--confirm-unpublished", action="store_true",
                    help="run although the query names genes of an unpublished study's results")
    a = ap.parse_args(argv)
    # The gateway's CA and the model key, as the server and the report CLI have them.
    from tooling.generate_report import _bootstrap_env
    _bootstrap_env()
    from safeguards.guarded import run_crawl
    from safeguards.refusals import Refused, explain
    try:
        m = run_crawl(a.query, a.name, a.resume, confirm=a.confirm_unpublished)
    except Refused as e:
        err = explain(e)["error"]
        print(f"refused ({err['code']}): {err['say']}", file=sys.stderr)
        return 2
    print(json.dumps({k: m[k] for k in ("name", "complete", "capabilities") if k in m}, indent=2))
    return 0 if m.get("complete") else 1


if __name__ == "__main__":
    sys.exit(main())
