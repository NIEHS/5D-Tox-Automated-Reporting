"""
tooling/published_clone.py — build each app-generated published report's
companion: the published book's content as a session of its own
(rendering.published_clone, ADR-0029 §13).

For every published report whose Bookshelf bundle is local
(assets/cebs/_bookshelf/<REPORT>/TOC.nxml) and whose generated report session
exists (tooling.build_published_reports.STUDIES; NIEHS-12/13 the report
session, one book for both studies), writes ``sessions/<DTXSID>_published/``:

  published_clone.json    the report, its generated twin, the bundle and its
                          content hash, the format, when built
  document.yaml           the book's structure as node entries — validated as a
                          full tree build before it is written
                          (document_config.save_session_document_yaml)
  published_content.json  each node's content, and the book-level facts
  identity.json           the twin's chemical name and CASRN

A companion is rebuilt only when its bundle or the clone format changed
(--force rebuilds anyway); the generated twin is never touched.

--check renders each companion's BITS and compares it with the published book
(rendering.bits_compare, as the QC loop does): the share of words that match,
every block that is not the same (by class), and every table or figure whose
number the tree gave differently from the book.

    python -m tooling.published_clone [--report NIEHS-10 …] [--force] [--check]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


def bundle_hash(bundle: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(bundle.iterdir()):
        if p.suffix.lower() in (".nxml", ".jpg", ".jpeg", ".png", ".gif", ".tif"):
            h.update(p.name.encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def companion_id(twin: str) -> str:
    return f"{twin}_published"


def reports() -> list[tuple[str, str]]:
    """[(report, generated twin session)] whose bundle and twin both exist."""
    import common.paths
    from tooling.build_published_reports import BOOKSHELF, STUDIES
    out = []
    for report, row in STUDIES.items():
        twin = row[0]
        if (BOOKSHELF / report / "TOC.nxml").is_file() and (common.paths.SESSIONS_DIR / twin).is_dir():
            out.append((report, twin))
    return out


def build(report: str, twin: str, *, force: bool = False) -> tuple[str, bool]:
    """Build (or keep) the companion of ``twin``; (companion id, rebuilt?)."""
    import common.paths
    from document_model.document_config import save_session_document_yaml
    from rendering.bits_compare import load_book
    from rendering.published_clone import CLONE_FILE, CONTENT_FILE, FORMAT, clone_book
    from tooling.build_published_reports import BOOKSHELF

    bundle = BOOKSHELF / report
    cid = companion_id(twin)
    session = common.paths.SESSIONS_DIR / cid
    digest = bundle_hash(bundle)
    stamp_path = session / CLONE_FILE
    if not force and stamp_path.is_file():
        stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
        if stamp.get("bundle_hash") == digest and stamp.get("format") == FORMAT:
            return cid, False
    book, images = load_book(bundle)
    clone = clone_book(book, images)
    session.mkdir(parents=True, exist_ok=True)
    save_session_document_yaml(cid, yaml.safe_dump({"document": clone["document"]},
                                                   sort_keys=False, allow_unicode=True))
    (session / CONTENT_FILE).write_text(
        json.dumps({"content": clone["content"], "front": clone["front"],
                    "labels": clone["labels"]}, ensure_ascii=False), encoding="utf-8")
    identity = json.loads((common.paths.SESSIONS_DIR / twin / "identity.json")
                          .read_text(encoding="utf-8")) \
        if (common.paths.SESSIONS_DIR / twin / "identity.json").is_file() else {}
    (session / "identity.json").write_text(json.dumps(
        {"dtxsid": cid, "name": identity.get("name") or clone["front"]["title"],
         "casrn": identity.get("casrn") or ""}, indent=2), encoding="utf-8")
    stamp_path.write_text(json.dumps(
        {"report": report, "twin": twin, "bundle": str(bundle), "bundle_hash": digest,
         "format": FORMAT, "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
        indent=2) + "\n", encoding="utf-8")
    return cid, True


def check(report: str, cid: str) -> dict:
    """How the companion's BITS reads against the published book."""
    from collections import Counter

    from document_model.view_config import build_view_tree
    from rendering.bits_compare import compare, load_book
    from rendering.preview_surface import render_preview
    from rendering.published_clone import CONTENT_FILE
    from tooling.build_published_reports import BOOKSHELF
    import common.paths

    ours = render_preview(cid, surface="bits")
    pub_book, pub_images = load_book(BOOKSHELF / report)
    our_book, our_images = load_book(ours)
    cmp = compare(pub_book, our_book, left_images=pub_images, right_images=our_images)
    off = Counter()
    for sp in cmp.sections:
        for bp in sp.blocks:
            if bp.status not in ("same", "typo"):
                off[(bp.status, bp.kind)] += 1
    labels = json.loads((common.paths.SESSIONS_DIR / cid / CONTENT_FILE)
                        .read_text(encoding="utf-8")).get("labels") or []
    from document_model.document_tree import find_node
    tree = build_view_tree(cid, "default")
    numbered = []
    for kind, nid, published in labels:
        node = find_node(nid, tree)
        if node is None:
            continue
        n = (node.table_label or node.table_number) if kind == "table" else (
            node.figure_label or node.figure_number)
        ours_label = f"{'Table' if kind == 'table' else 'Figure'} {n}" if n else ""
        if published and " ".join(ours_label.split()) != " ".join(published.split()):
            numbered.append((published, ours_label or "(none)"))
    return {"sim": cmp.sim, "off": off, "numbered": numbered}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--report", action="append", help="build only these reports (repeatable)")
    ap.add_argument("--force", action="store_true", help="rebuild even when up to date")
    ap.add_argument("--check", action="store_true",
                    help="compare each companion's BITS with the published book")
    a = ap.parse_args(argv)
    from tooling.generate_report import _bootstrap_env
    _bootstrap_env()
    todo = [(r, t) for r, t in reports() if not a.report or r in a.report]
    if not todo:
        print("no published report with a local bundle and a generated session", file=sys.stderr)
        return 1
    failed = 0
    for report, twin in todo:
        cid, rebuilt = build(report, twin, force=a.force)
        line = f"{report:9} {cid:28} {'built' if rebuilt else 'up to date'}"
        if a.check:
            res = check(report, cid)
            off = ", ".join(f"{n} {s} {k}" for (s, k), n in sorted(res["off"].items())) or "none"
            line += f"   {res['sim']:.1%} of words match; not the same: {off}"
            if res["numbered"]:
                failed += 1
                line += "\n          numbered differently: " + "; ".join(
                    f"{p} → {o}" for p, o in res["numbered"])
        print(line, flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
