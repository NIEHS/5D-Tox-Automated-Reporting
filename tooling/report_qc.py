"""tooling/report_qc.py — quality control of generated reports, read from the
rendered deliverables themselves (output/<DTXSID>/<DTXSID>.{html,xml,docx,pdf}).

Each check reads what a reader would read — the rendered HTML text and tables,
the BITS XML — plus the session's integrated project for the facts the report
should state.  Findings carry a severity:

  error  wrong in the report (a fact contradicting the data or the published
         report, broken markup, an invalid submission file);
  warn   probably wrong, or missing content a reader would notice;
  info   expected gaps, recorded so the totals stay honest.

Checks:
  files        every deliverable present and non-empty
  markers      [Placeholder: …], [… pending], broken [[xref:…]] markers
  junk         NaN / None / null / undefined / template residue in the text
  sections     the report's sections present and not empty
  design       route, vehicle, species and dose-unit wording against the design
  sexes        the other sex named in a single-sex study
  platform     the transcriptomics platform and BMDExpress version the text
               names against the project's chip and analysis records
  tables       empty tables; captions without the test article
  duplicates   paragraphs repeated verbatim
  bmd_summary  BMDL <= BMD, NOEL < LOEL; and, where the published report is
               downloaded, its BMD/LOEL/NOEL summary compared row by row
  bits         the BITS book against the BITS 2.0 DTD and the PMC StyleChecker,
               the book and every file of its chunked Bookshelf bundle
  structure    the BITS book's outline (parts, part types, labels, section
               titles, object placement) against the published Bookshelf book
               of the same study, where that bundle is downloaded (ADR-0028)

Usage:
    python -m tooling.report_qc [DTXSID ...] [--out output/QC]
Default: every report on the Bookshelf shelf.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BOOKSHELF = REPO_ROOT / "assets" / "cebs" / "_bookshelf"

# DTXSID → the published report whose data it was built from.
PUBLISHED = {
    "DTXSID1021952": "RR-8", "DTXSID1025300": "NIEHS-02", "DTXSID6024701": "NIEHS-03",
    "DTXSID3025465": "NIEHS-04", "DTXSID4028880": "NIEHS-05", "DTXSID4021391": "NIEHS-06",
    "DTXSID00190950": "NIEHS-07", "DTXSID2029905": "NIEHS-08", "DTXSID1022477": "NIEHS-09",
    "DTXSID50469320": "NIEHS-10", "DTXSID6020430": "NIEHS-12", "DTXSID1020431": "NIEHS-13",
}
# Published reports whose apical BMDs came from the engine we run (BMDExpress 3
# / ToxicR model averaging); the others used modified BMDS 2.7, so their BMD
# values are compared for information only.
SAME_BMD_ENGINE = {"NIEHS-12", "NIEHS-13"}


@dataclass
class Finding:
    check: str
    severity: str
    message: str
    evidence: list[str] = field(default_factory=list)


@dataclass
class ReportQC:
    dtxsid: str
    name: str
    published: str | None
    findings: list[Finding] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def add(self, check, severity, message, evidence=()):
        self.findings.append(Finding(check, severity, message, [str(e)[:300] for e in evidence][:8]))


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

def _soup(path: Path):
    from bs4 import BeautifulSoup
    return BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")


def _visible_text(soup) -> str:
    for tag in soup(["style", "script"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" "))


# Sections whose text is not about this study: the fixed NIEHS boilerplate
# (Peer Review quotes RR-8's "(Gavage Studies)" title) and the literature
# references (titles name mice, microarrays, …).
_NOT_STUDY_TEXT = {"References", "Peer Review", "Foreword", "Table of Contents", "Tables"}


def _study_text(soup, also_skip: frozenset = frozenset()) -> str:
    """The visible text of the report minus the sections that do not describe
    this study (_NOT_STUDY_TEXT, plus ``also_skip``)."""
    skip = _NOT_STUDY_TEXT | set(also_skip)
    parts, keep = [], True
    body = soup.body or soup
    for el in body.descendants:
        if getattr(el, "name", None) == "h2":
            keep = el.get_text(" ", strip=True) not in skip
        elif isinstance(el, str) and keep and el.parent.name not in ("style", "script"):
            parts.append(el)
    return re.sub(r"\s+", " ", " ".join(parts))


def _context(text: str, match: re.Match, width: int = 70) -> str:
    return "…" + text[max(0, match.start() - width): match.end() + width].strip() + "…"


def _integrated(dtxsid: str) -> dict:
    p = REPO_ROOT / "sessions" / dtxsid / "integrated.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _design(integrated: dict, unit: str | None) -> dict:
    from pipeline.study_design import study_design_facts
    return study_design_facts(integrated, unit)


def _members(dtxsid: str) -> list[str]:
    """A report over several studies' member sessions (studies.json), else []."""
    p = REPO_ROOT / "sessions" / dtxsid / "studies.json"
    return list(json.loads(p.read_text()).values()) if p.exists() else []


def _sexes(dtxsid: str) -> set[str]:
    sexes = set()
    for p in glob.glob(str(REPO_ROOT / "sessions" / dtxsid / "files" / "*.sidecar.json")):
        try:
            sex = json.load(open(p)).get("sex")
        except (OSError, ValueError):
            continue
        if sex:
            sexes.add(str(sex).lower())
    return sexes


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_files(qc: ReportQC, out: Path) -> None:
    for suffix in (".html", ".docx", ".xml", ".pdf"):
        p = out / f"{qc.dtxsid}{suffix}"
        if not p.exists() or p.stat().st_size == 0:
            qc.add("files", "error", f"{p.name} missing or empty")
    qc.stats["files"] = {p.name: p.stat().st_size for p in sorted(out.glob(f"{qc.dtxsid}.*"))}


def check_markers(qc: ReportQC, text: str) -> None:
    placeholders = re.findall(r"\[Placeholder: ([^\]]*)\]", text)
    pending = re.findall(r"\[[^\[\]]{0,80}pending[^\[\]]{0,40}\]", text, re.I)
    broken = re.findall(r"\[\[xref:[^\]]*\]\]", text)
    if placeholders:
        qc.add("markers", "info", f"{len(placeholders)} Methods placeholder(s) for facts no file "
               "records (expected; --strict blocks)", placeholders)
    # About This Report (authors) and Background (external sources, host-only)
    # are known human/host inputs; any other pending section is a gap.
    expected = [p for p in pending if "About This Report" in p or "Background" in p]
    other = [p for p in pending if p not in expected]
    if expected:
        qc.add("markers", "info", f"{len(expected)} pending section(s) awaiting known inputs "
               "(authors in front matter; Background on the host)", sorted(set(expected)))
    if other:
        qc.add("markers", "warn", f"{len(other)} pending marker(s)", sorted(set(other)))
    if broken:
        qc.add("markers", "error", f"{len(broken)} unresolved cross-reference(s)", broken)


_JUNK = [
    (r"\bNaN\b", "NaN"), (r"\bnan\b", "nan"), (r"\bNone\b(?! of\b)", "None"),
    (r"(?<!synthetic )(?<!the )\bnull\b(?! (?:data|hypothes|distribution|model|set|result))", "null"),
    (r"\bundefined\b", "undefined"), (r"\$\{[^}]*\}", "${…}"), (r"\{[a-z_]{3,}\}", "{field}"),
    (r"\bTODO\b", "TODO"), (r"\binf\b", "inf"),
]


def check_junk(qc: ReportQC, text: str) -> None:
    for pat, label in _JUNK:
        hits = [_context(text, m) for m in re.finditer(pat, text)]
        if hits:
            qc.add("junk", "error", f"'{label}' appears {len(hits)} time(s) in the text", hits)


_SECTIONS = ["Abstract", "Background", "Materials and Methods", "Results", "Summary", "References"]


def check_sections(qc: ReportQC, soup) -> None:
    heads = {h.get_text(" ", strip=True): h for h in soup.find_all(["h2", "h3"])}
    for name in _SECTIONS:
        h = heads.get(name)
        if h is None:
            qc.add("sections", "error", f"section '{name}' missing")
            continue
        body = []
        for sib in h.find_all_next():
            if sib.name in ("h2",) and sib is not h:
                break
            if sib.name in ("p", "td", "li"):
                body.append(sib.get_text(" ", strip=True))
        words = len(" ".join(body).split())
        if words < 30:
            sev = "info" if name == "Background" else "warn"
            qc.add("sections", sev, f"section '{name}' has {words} word(s)"
                   + (" — Background needs --background on the host" if name == "Background" else ""))


def check_design(qc: ReportQC, text: str, design: dict, unit: str) -> None:
    from pipeline.study_design import is_air_concentration
    inhaled = design.get("route") == "inhaled"
    rules = []
    if inhaled:
        rules += [(r"\bgavage\b", "gavage in an inhalation study", "error"),
                  (r"\bcorn oil\b", "corn oil in an inhalation study", "error")]
    elif design.get("route") == "gavage":
        rules += [(r"\binhal\w*", "inhalation wording in a gavage study", "warn"),
                  (r"\bchamber control\b", "chamber control in a gavage study", "error")]
    if design.get("species") == "rat":
        rules += [(r"\b(mice|mouse)\b", "mice named in a rat study", "warn")]
    if is_air_concentration(unit):
        rules += [(r"mg/kg(?!/day)", "mg/kg in a ppm study", "error")]
    else:
        rules += [(r"\bppm\b", "ppm in an mg/kg study", "error")]
    for pat, what, sev in rules:
        hits = [_context(text, m) for m in re.finditer(pat, text, re.I)
                if not _HUMAN_EXPOSURE.search(_sentence(text, m))]
        if hits:
            qc.add("design", sev, f"{what}: {len(hits)} occurrence(s)", hits)


# A sentence about how PEOPLE meet the chemical ("humans are exposed through
# inhalation …") or a regulatory value (inhalation RfC) is not this study's design.
_HUMAN_EXPOSURE = re.compile(r"\b(humans?|people|occupational\w*|workers?|population|consumers?|reference concentration|RfC|unit risk)\b", re.I)


def _sentence(text: str, m: re.Match) -> str:
    start = max(text.rfind(". ", 0, m.start()), 0)
    end = text.find(". ", m.end())
    return text[start:end if end >= 0 else len(text)]


def check_sexes(qc: ReportQC, text: str, sexes: set[str]) -> None:
    if len(sexes) != 1:
        return
    other = "female" if sexes == {"male"} else "male"
    # "male gonad development" and the like are GO term names, not animals.
    hits = [_context(text, m) for m in re.finditer(rf"\b{other}s?\b(?! gonad| reproductive)", text, re.I)]
    # The fixed Peer Review boilerplate names RR-8's "Male Sprague Dawley" rats.
    hits = [h for h in hits if "Triphenyl Phosphate (CAS No. 115-86-6)" not in h]
    if hits:
        qc.add("sexes", "warn", f"{other} named {len(hits)} time(s) in a {next(iter(sexes))}-only study",
               hits)


def check_platform(qc: ReportQC, text: str, integrated: dict) -> None:
    chips, versions = set(), set()
    for e in integrated.get("doseResponseExperiments") or []:
        chip = e.get("chip") or {}
        if isinstance(chip, dict):
            chips.add(" ".join(str(chip.get(k) or "") for k in ("name", "chipId", "provider")))
        for note in ((e.get("analysisInfo") or {}).get("notes") or []):
            m = re.search(r"BMDExpress\s*(?:Version)?[: ]*\s*(\d+\.\d+)", str(note), re.I)
            if m:
                versions.add(m.group(1))
    for r in integrated.get("bMDResult") or []:
        for note in ((r.get("analysisInfo") or {}).get("notes") or []):
            m = re.search(r"BMDExpress\s*(?:Version)?[: ]*\s*(\d+\.\d+)", str(note), re.I)
            if m:
                versions.add(m.group(1))
    chip_text = " ".join(chips).lower()
    affy = any(k in chip_text for k in ("affy", "gpl1355", "rat230", "rg_u34", "hg-u133"))
    tempo = any(k in chip_text for k in ("s1500", "tempo", "biospyder"))
    qc.stats["chips"] = sorted(c.strip() for c in chips if c.strip())
    qc.stats["bmdexpress_versions"] = sorted(versions)
    if affy and re.search(r"TempO-Seq|S1500", text):
        hits = [_context(text, m) for m in re.finditer(r"TempO-Seq|S1500", text)]
        qc.add("platform", "error", "text names TempO-Seq/S1500 for an Affymetrix microarray study",
               hits)
    if tempo and re.search(r"Affymetrix|microarray", text, re.I):
        hits = [_context(text, m) for m in re.finditer(r"Affymetrix|microarray", text, re.I)]
        qc.add("platform", "error", "text names a microarray for a TempO-Seq study", hits)
    majors = {v.split(".")[0] for v in versions}
    for m in re.finditer(r"BMDExpress\s+(\d)(?:\.\d+)?", text):
        # Appendix D states the engine THIS tool fits apical endpoints with
        # (BMDExpress 3 / ToxicR) — true whatever the study's project used.
        if text[max(0, m.start() - 40):m.start()].endswith("Apical endpoints were modeled in "):
            continue
        if majors and m.group(1) not in majors:
            qc.add("platform", "error",
                   f"text names BMDExpress {m.group(1)}; the project records {sorted(versions)}",
                   [_context(text, m)])
            break


def check_tables(qc: ReportQC, soup, name: str, short: str) -> None:
    tables = soup.find_all("table")
    qc.stats["tables"] = len(tables)
    names = {n.lower() for n in (name, short) if n}
    for t in tables:
        cap = t.find("caption")
        caption = cap.get_text(" ", strip=True) if cap else ""
        rows = [tr for tr in t.find_all("tr") if tr.find("td")]
        if not rows:
            qc.add("tables", "warn", f"table with no data rows: {caption[:100] or '(no caption)'}")
        if caption.startswith("Table") and ("Administered" in caption or "Exposed" in caption) \
                and not any(n in caption.lower() for n in names):
            qc.add("tables", "warn", f"caption does not name the test article: {caption[:120]}")


def check_duplicates(qc: ReportQC, soup) -> None:
    paras = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    counts = Counter(p for p in paras if len(p) > 120)
    dup = [p for p, n in counts.items() if n > 1]
    if dup:
        qc.add("duplicates", "warn", f"{len(dup)} paragraph(s) appear more than once", dup)


def _num(s: str) -> float | None:
    try:
        return float(str(s).replace(",", "").strip())
    except ValueError:
        return None


def _norm_endpoint(s: str) -> str:
    """Order- and form-insensitive endpoint key: "Liver Weight Absolute" ==
    "Absolute Liver Weight"; "Reticulocytes" == "Reticulocyte count"."""
    s = re.sub(r"<[^>]+>", "", s or "").lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\b(count|concentration|level)\b", " ", s)
    words = [re.sub(r"(?<=[a-z]{3})s$", "", w) for w in s.split()]
    return " ".join(sorted(words))


_GROUPS = ("Male", "Female", "Rats", "Mice")      # sexes; a composed report's studies


def _our_bmd_summary(soup) -> list[dict]:
    for t in soup.find_all("table"):
        cap = t.find("caption")
        if cap and "LOEL" in cap.get_text() and "Summary" in cap.get_text():
            rows = []
            for tr in t.find_all("tr"):
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                if len(cells) >= 7 and cells[0].split()[-1:] and cells[0].split()[-1] in _GROUPS:
                    rows.append(dict(zip(("sex", "endpoint", "bmd", "bmdl", "loel", "noel",
                                          "direction"), cells[:7])))
            return rows
    return []


def _published_bmd_summary(report: str, study_sexes: set[str],
                           by_study: bool = False) -> list[dict]:
    """The published report's BMD/LOEL/NOEL summary rows for its RAT study —
    or, ``by_study`` (a report over several studies), every study's, under the
    study's title ("Rats" / "Mice") — columns mapped by header (layouts differ
    by era: RR-8 leads with a table number and puts NOEL first)."""
    one_sex = next(iter(study_sexes)).title() if len(study_sexes) == 1 else None
    for p in sorted(glob.glob(str(BOOKSHELF / report / "breakdown" / "tables" / "*.json"))):
        t = json.load(open(p))
        if not ("LOEL" in (t.get("title") or "") and "Summary" in (t.get("title") or "")):
            continue
        header = [re.sub(r"<[^>]+>", "", h) for h in (t.get("header") or [[]])[0]]
        col = {}
        for i, h in enumerate(header):
            hl = h.lower()
            if hl.startswith("endpoint"):
                col["endpoint"] = i
            elif hl.startswith("bmdl"):
                col["bmdl"] = i
            elif hl.startswith("bmd"):
                col["bmd"] = i
            elif hl.startswith("loel"):
                col["loel"] = i
            elif hl.startswith("noel"):
                col["noel"] = i
            elif hl.startswith("direction"):
                col["direction"] = i
        rows, sex, species = [], one_sex, "rats"
        for r in t.get("rows") or []:
            cells = [re.sub(r"<[^>]+>", "", c).strip() for c in r]
            if not any(cells[1:]):
                head = cells[0].lower().rstrip("s")
                if head in ("male", "female"):
                    sex = head.title()
                elif head in ("rat", "mice", "mouse"):
                    species = "rats" if head == "rat" else "mice"
                continue
            if (species != "rats" and not by_study) or "endpoint" not in col:
                continue
            group = species.title() if by_study else sex
            rows.append({"sex": group, **{k: (cells[i] if i < len(cells) else "") for k, i in col.items()}})
        return rows
    return []


def check_bmd_summary(qc: ReportQC, soup, sexes: set[str], by_study: bool = False) -> None:
    ours = _our_bmd_summary(soup)
    qc.stats["bmd_summary_rows"] = len(ours)
    for r in ours:
        bmd, bmdl, loel, noel = (_num(r[k]) for k in ("bmd", "bmdl", "loel", "noel"))
        if bmd is not None and bmdl is not None and bmdl > bmd:
            qc.add("bmd_summary", "error", f"BMDL > BMD: {r['sex']} {r['endpoint']} ({bmdl} > {bmd})")
        if loel is not None and noel is not None and noel >= loel:
            qc.add("bmd_summary", "error", f"NOEL >= LOEL: {r['sex']} {r['endpoint']} ({noel} >= {loel})")
    if not qc.published:
        return
    pub = _published_bmd_summary(qc.published, sexes, by_study)
    if not pub:
        qc.add("bmd_summary", "info", f"no published BMD summary table found for {qc.published}")
        return
    key = lambda r: ((r["sex"] or "").lower(), _norm_endpoint(r["endpoint"]))  # noqa: E731
    ours_by, pub_by = {key(r): r for r in ours}, {key(r): r for r in pub}
    missing = [f"{r['sex']} {r['endpoint']}" for k, r in pub_by.items() if k not in ours_by]
    extra = [f"{r['sex']} {r['endpoint']}" for k, r in ours_by.items() if k not in pub_by]
    loel_diff, bmd_diff = [], []
    for k, p in pub_by.items():
        o = ours_by.get(k)
        if not o:
            continue
        for f in ("loel", "noel"):
            # Published G0/G1 tables print dose levels as integers (61 for 61.2)
            # and may carry a footnote letter ("441a").
            pv, ov = _first_num(p[f]), _first_num(o[f])
            if (pv is None) != (ov is None) or (pv is not None and abs(pv - ov) > max(0.5, 0.005 * pv)):
                loel_diff.append(f"{p['sex']} {p['endpoint']} {f.upper()}: published {p[f] or '—'}, ours {o[f] or '—'}")
        pb, ob = _num(p["bmd"]), _num(o["bmd"])
        if pb is not None and ob is not None and abs(pb - ob) > 0.02 * pb:
            bmd_diff.append(f"{p['sex']} {p['endpoint']} BMD: published {p['bmd']}, ours {o['bmd']}")
        elif (pb is None) != (ob is None):
            bmd_diff.append(f"{p['sex']} {p['endpoint']} BMD: published {p['bmd']}, ours {o['bmd']}")
    qc.stats["bmd_summary_vs_published"] = {
        "published_rows": len(pub), "our_rows": len(ours), "matched": len(pub_by.keys() & ours_by.keys()),
        "loel_noel_differences": len(loel_diff), "bmd_differences": len(bmd_diff)}
    if missing:
        qc.add("bmd_summary", "warn", f"{len(missing)} published summary endpoint(s) not in ours", missing)
    if extra:
        qc.add("bmd_summary", "warn", f"{len(extra)} endpoint(s) in ours not in the published summary",
               extra)
    if loel_diff:
        qc.add("bmd_summary", "error", f"{len(loel_diff)} LOEL/NOEL value(s) differ from the published",
               loel_diff)
    if bmd_diff:
        same = qc.published in SAME_BMD_ENGINE
        qc.add("bmd_summary", "error" if same else "info",
               f"{len(bmd_diff)} BMD(s) differ from the published"
               + ("" if same else " (published with modified BMDS 2.7; we run ToxicR model averaging)"),
               bmd_diff)


_GO_ID = re.compile(r"GO:\d{7}")
_TOP_GO = re.compile(r"Top \d+ (?:(.+?) )?Gene Ontology", re.I)


def _first_num(s: str) -> float | None:
    m = re.search(r"\d+(?:\.\d+)?", (s or "").replace(",", ""))   # "1,033"
    return float(m.group()) if m else None


def _decimals(s: str) -> int:
    m = re.search(r"\d+(?:\.(\d+))?", s or "")
    return len(m.group(1) or "") if m else 0


def _go_rows(title: str, header: list[str], rows: list[list[str]], one_sex: str | None) -> tuple:
    """(organ, {(sex): [row dicts]}) for one Top-N GO table; rat rows only."""
    m = _TOP_GO.search(title)
    organ = (m.group(1) or "").strip().lower() if m else ""
    header = [re.sub(r"<[^>]+>", "", h) for h in header]
    bmd_col = next((i for i, h in enumerate(header) if h.startswith("BMD")), None)
    gene_col = next((i for i, h in enumerate(header) if h.startswith("Active Genes")), None)
    by_sex, sex, species = {}, one_sex, "rats"
    for r in rows:
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in r]
        if not any(cells[1:]):
            head = cells[0].lower().rstrip("s")
            if head in ("male", "female"):
                sex = head.title()
            elif head in ("rat", "mice", "mouse"):
                species = "rats" if head == "rat" else "mice"
            continue
        go = _GO_ID.search(cells[0])
        if species != "rats" or not go:
            continue
        by_sex.setdefault(sex, []).append({
            "go": go.group(), "name": cells[0],
            "bmd": cells[bmd_col] if bmd_col is not None and bmd_col < len(cells) else "",
            "genes": cells[gene_col] if gene_col is not None and gene_col < len(cells) else ""})
    return organ, by_sex


def _our_go_tables(soup, one_sex) -> dict:
    out = {}
    for t in soup.find_all("table"):
        cap = t.find("caption")
        title = cap.get_text(" ", strip=True) if cap else ""
        if not _TOP_GO.search(title):
            continue
        trs = t.find_all("tr")
        header = [c.get_text(" ", strip=True) for c in trs[0].find_all(["td", "th"])] if trs else []
        rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])] for tr in trs[1:]]
        organ, by_sex = _go_rows(title, header, rows, one_sex)
        out[organ] = by_sex
    return out


def _published_go_tables(report: str, one_sex) -> dict:
    out = {}
    for p in sorted(glob.glob(str(BOOKSHELF / report / "breakdown" / "tables" / "*.json"))):
        t = json.load(open(p))
        if not _TOP_GO.search(re.sub(r"<[^>]+>", "", t.get("title") or "")):
            continue
        organ, by_sex = _go_rows(re.sub(r"<[^>]+>", "", t["title"]), (t.get("header") or [[]])[0],
                                 t.get("rows") or [], one_sex)
        if by_sex:
            out[organ] = by_sex
    return out


def check_go(qc: ReportQC, soup, sexes: set[str]) -> None:
    """Our Top-10 GO gene-set tables against the published ones, per organ and
    sex: which gene sets, their BMDs, and how genes and BMDs are printed."""
    one_sex = next(iter(sexes)).title() if len(sexes) == 1 else None
    ours = _our_go_tables(soup, one_sex)
    qc.stats["go_tables"] = sorted(ours)
    if not qc.published:
        return
    pub = _published_go_tables(qc.published, one_sex)
    if not pub:
        return
    # A table without an organ in its title is the study's only GO table.
    if "" in pub and len(pub) == 1 and len(ours) == 1:
        pub = {next(iter(ours)): pub[""]}
    compared = matched = 0
    missing_tables, set_diffs, bmd_diffs = [], [], []
    lower_genes = more_decimals = False
    for organ, pub_sexes in pub.items():
        for sex, prows in pub_sexes.items():
            orows = (ours.get(organ) or {}).get(sex)
            if not orows:
                missing_tables.append(f"{organ or '(organ)'} {sex or ''}".strip())
                continue
            by_go = {r["go"]: r for r in orows}
            by_genes = {r["genes"].lower(): r for r in orows if r["genes"]}
            for p in prows:
                compared += 1
                o = by_go.get(p["go"]) or (by_genes.get(p["genes"].lower()) if p["genes"] else None)
                if not o:
                    set_diffs.append(f"{organ} {sex}: published {p['name']} ({p['bmd']}) not in ours")
                    continue
                matched += 1
                pb, ob = _first_num(p["bmd"]), _first_num(o["bmd"])
                tol = max(0.02 * (pb or 0), 0.5 * 10 ** -_decimals(o["bmd"]))
                if pb is not None and ob is not None and abs(pb - ob) > tol + 1e-9:
                    bmd_diffs.append(f"{organ} {sex} {p['go']}: published {p['bmd']}, ours {o['bmd']}")
                if p["genes"] and o["genes"] and p["genes"] != p["genes"].lower() \
                        and o["genes"] == o["genes"].lower():
                    lower_genes = True
                if _decimals(p["bmd"]) > _decimals(o["bmd"]):
                    more_decimals = True
    qc.stats["go_vs_published"] = {"published_rows": compared, "matched": matched,
                                   "bmd_differences": len(bmd_diffs)}
    if missing_tables:
        qc.add("go", "warn", f"{len(missing_tables)} published GO table(s) with no counterpart in ours",
               missing_tables)
    if set_diffs:
        qc.add("go", "warn", f"{len(set_diffs)} of {compared} published top GO gene sets not in ours",
               set_diffs)
    if bmd_diffs:
        qc.add("go", "error", f"{len(bmd_diffs)} GO gene-set BMD(s) differ from the published",
               bmd_diffs)
    if lower_genes:
        qc.add("go", "warn", "active genes printed in lower case (published prints rat gene symbols "
               "capitalized, e.g. Zfp36)")
    if more_decimals:
        qc.add("go", "info", "GO BMDs printed with fewer decimals than the published")


_TOP_GENES = re.compile(r"Top \d+ (?:(.+?) )?Genes Ranked", re.I)


def _gene_rows(title: str, header: list[str], rows: list[list[str]], one_sex: str | None) -> tuple:
    """(organ, {sex: [row dicts]}) for one Top-N genes table; rat rows only."""
    m = _TOP_GENES.search(title)
    organ = (m.group(1) or "").strip().lower() if m else ""
    header = [re.sub(r"<[^>]+>", "", h).strip() for h in header]
    col = {}
    for i, h in enumerate(header):
        if h.startswith("Gene Symbol"):
            col.setdefault("gene", i)
        elif h.startswith("BMD"):
            col.setdefault("bmd", i)
        elif "Fold Change" in h:
            col.setdefault("fc", i)
        elif h.startswith("Direction"):
            col.setdefault("direction", i)
    if "gene" not in col:
        return organ, {}
    by_sex, sex, species = {}, one_sex, "rats"
    for r in rows:
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in r]
        if not any(cells[1:]):
            head = cells[0].lower().rstrip("s")
            if head in ("male", "female"):
                sex = head.title()
            elif head in ("rat", "mice", "mouse"):
                species = "rats" if head == "rat" else "mice"
            continue
        if species != "rats":
            continue
        by_sex.setdefault(sex, []).append({k: (cells[i] if i < len(cells) else "") for k, i in col.items()})
    return organ, by_sex


def check_top_genes(qc: ReportQC, soup, sexes: set[str]) -> None:
    """Our Top-10 genes tables against the published ones, per organ and sex:
    which genes, their BMDs, fold changes and direction."""
    one_sex = next(iter(sexes)).title() if len(sexes) == 1 else None
    ours = {}
    for t in soup.find_all("table"):
        cap = t.find("caption")
        title = cap.get_text(" ", strip=True) if cap else ""
        if not _TOP_GENES.search(title):
            continue
        trs = t.find_all("tr")
        header = [c.get_text(" ", strip=True) for c in trs[0].find_all(["td", "th"])] if trs else []
        rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])] for tr in trs[1:]]
        organ, by_sex = _gene_rows(title, header, rows, one_sex)
        ours[organ] = by_sex
    if not qc.published:
        return
    pub = {}
    for p in sorted(glob.glob(str(BOOKSHELF / qc.published / "breakdown" / "tables" / "*.json"))):
        t = json.load(open(p))
        title = re.sub(r"<[^>]+>", "", t.get("title") or "")
        if _TOP_GENES.search(title):
            organ, by_sex = _gene_rows(title, (t.get("header") or [[]])[0], t.get("rows") or [], one_sex)
            if by_sex:
                pub[organ] = by_sex
    if not pub:
        return
    if "" in pub and len(pub) == 1 and len(ours) == 1:
        pub = {next(iter(ours)): pub[""]}
    compared = matched = 0
    missing_tables, gene_diffs, bmd_diffs, fc_diffs, dir_diffs = [], [], [], [], []
    for organ, pub_sexes in pub.items():
        for sex, prows in pub_sexes.items():
            orows = (ours.get(organ) or {}).get(sex)
            if not orows:
                missing_tables.append(f"{organ or '(organ)'} {sex or ''}".strip())
                continue
            # A probe mapping to two genes prints "Car3/Ca3" (or one of them).
            by_gene = {g.strip().lower(): r for r in orows for g in r["gene"].split("/")}
            for p in prows:
                compared += 1
                o = next((by_gene[g.strip().lower()] for g in p["gene"].split("/")
                          if g.strip().lower() in by_gene), None)
                where = f"{organ} {sex} {p['gene']}"
                if not o:
                    gene_diffs.append(f"{where} ({p.get('bmd', '')}) not in ours")
                    continue
                matched += 1
                pb, ob = _first_num(p.get("bmd", "")), _first_num(o.get("bmd", ""))
                if pb is not None and ob is not None:
                    if p["bmd"].startswith("<"):
                        bad = ob >= pb
                    else:
                        bad = abs(pb - ob) > max(0.02 * pb, 0.5 * 10 ** -_decimals(o["bmd"])) + 1e-9
                    if bad:
                        bmd_diffs.append(f"{where}: published {p['bmd']}, ours {o['bmd']}")
                pf, of = _first_num(p.get("fc", "")), _first_num(o.get("fc", ""))
                if pf is not None and (of is None or abs(pf - of) > 0.051):
                    fc_diffs.append(f"{where}: published {p['fc']}, ours {o.get('fc', '—')}")
                if p.get("direction") and o.get("direction") and p["direction"].upper() != o["direction"].upper():
                    dir_diffs.append(f"{where}: published {p['direction']}, ours {o['direction']}")
    qc.stats["top_genes_vs_published"] = {"published_rows": compared, "matched": matched,
                                          "bmd_differences": len(bmd_diffs),
                                          "fold_change_differences": len(fc_diffs)}
    if missing_tables:
        qc.add("top_genes", "warn", f"{len(missing_tables)} published top-genes table(s) with no "
               "counterpart in ours", missing_tables)
    if gene_diffs:
        qc.add("top_genes", "warn", f"{len(gene_diffs)} of {compared} published top genes not in ours",
               gene_diffs)
    if bmd_diffs:
        qc.add("top_genes", "error", f"{len(bmd_diffs)} gene BMD(s) differ from the published", bmd_diffs)
    if fc_diffs:
        qc.add("top_genes", "error", f"{len(fc_diffs)} fold change(s) differ from the published", fc_diffs)
    if dir_diffs:
        qc.add("top_genes", "error", f"{len(dir_diffs)} direction(s) differ from the published", dir_diffs)


def check_bits(qc: ReportQC, xml_path: Path) -> None:
    from rendering.bits_bundle import split_book
    from rendering.jats_stylecheck import dtd_validate, stylecheck
    if not xml_path.exists():
        return
    xml = xml_path.read_bytes()
    dtd = dtd_validate(xml, "book")
    if dtd:
        qc.add("bits", "error", f"BITS DTD: {len(dtd)} error(s)", list(dtd))
    sc = stylecheck(xml, "book")
    if sc.errors:
        qc.add("bits", "error", f"StyleChecker: {len(sc.errors)} error(s)", list(sc.errors))
    if getattr(sc, "warnings", None):
        qc.add("bits", "info", f"StyleChecker: {len(sc.warnings)} warning(s)", list(sc.warnings))
    # The chunked bundle (the `bits` surface): every file must pass too.
    bad = []
    for name, content in split_book(xml).items():
        problems = dtd_validate(content, "book") + stylecheck(content, "book").errors
        if problems:
            bad.append(f"{name}: {list(problems[:3])}")
    if bad:
        qc.add("bits", "error", f"bundle: {len(bad)} invalid file(s)", bad)


def check_structure(qc: ReportQC, xml_path: Path) -> None:
    """Our BITS outline against the published book's (tooling.bits_structure).
    Only the chunked published books (NIEHS-07 onward) share our part
    structure; the older single-part books (RR-8, NIEHS-02 … 06) are recorded,
    not compared."""
    from rendering.bits_bundle import outline, read_bundle
    from tooling.bits_structure import BOOKSHELF, published_outline, structure_diff
    report = qc.published
    toc = BOOKSHELF / (report or "") / "TOC.nxml"
    if not report or not toc.exists() or not xml_path.exists():
        return
    if read_bundle(toc.parent).tag != "book":
        qc.add("structure", "info",
               f"{report} is a single-part book (the pre-NIEHS-07 layout): not compared")
        return
    diff = structure_diff(published_outline(report), outline(read_bundle(xml_path)))
    if diff:
        qc.add("structure", "warn",
               f"outline differs from the published {report} in {len(diff)} line(s) "
               f"(- published only, + ours only)", diff)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def qc_report(dtxsid: str) -> ReportQC:
    out = REPO_ROOT / "output" / dtxsid
    sess = REPO_ROOT / "sessions" / dtxsid
    identity = json.loads((sess / "identity.json").read_text()) if (sess / "identity.json").exists() else {}
    qc = ReportQC(dtxsid, identity.get("name") or dtxsid, PUBLISHED.get(dtxsid))
    check_files(qc, out)
    html = out / f"{dtxsid}.html"
    if not html.exists():
        return qc
    soup = _soup(html)
    text = _study_text(_soup(html))
    # The Background is about the chemical in general (routes of human
    # exposure, RfC/RfD), not this study's design.
    design_text = _study_text(_soup(html), frozenset({"Background"}))
    integrated = _integrated(dtxsid)
    units = sorted({str(t.get("doseUnit") or "") for e in integrated.get("doseResponseExperiments") or []
                    for t in (e.get("treatments") or []) if isinstance(t, dict)} - {""})
    unit = "ppm" if re.search(r"\bppm\b", text) and not re.search(r"mg/kg", text) else \
        ("ppm" if "ppm" in units else "mg/kg")
    title = soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else ""
    unit = "ppm" if "Inhalation" in title or "Respiratory" in title else unit
    design = _design(integrated, unit)
    sexes = _sexes(dtxsid)
    members = _members(dtxsid)
    if members:
        # A report over several studies: their design together, their sexes.
        from rendering.report_compose import composed_design
        design = composed_design([_design(_integrated(m), unit) for m in members])
        sexes = set().union(*(_sexes(m) for m in members))
    qc.stats.update({"title": title, "unit": unit, "sexes": sorted(sexes),
                     "design": {k: design.get(k) for k in ("species", "strain", "route", "vehicle",
                                                           "duration_days", "fallback")},
                     "words": len(text.split())})
    check_markers(qc, text)
    check_junk(qc, text)
    check_sections(qc, soup)
    check_design(qc, design_text, design, unit)
    check_sexes(qc, design_text, sexes)
    check_platform(qc, text, integrated)
    check_tables(qc, soup, qc.name, _short_name(dtxsid))
    check_duplicates(qc, soup)
    check_bmd_summary(qc, soup, sexes, by_study=bool(members))
    check_go(qc, soup, sexes)
    check_top_genes(qc, soup, sexes)
    check_bits(qc, out / f"{dtxsid}.xml")
    check_structure(qc, out / f"{dtxsid}.xml")
    return qc


def _short_name(dtxsid: str) -> str:
    try:
        from tooling.build_published_reports import STUDIES
        for v in STUDIES.values():
            if v[0] == dtxsid:
                return v[3]
    except Exception:  # noqa: BLE001
        pass
    return ""


def _markdown(results: list[ReportQC]) -> str:
    sev_order = {"error": 0, "warn": 1, "info": 2}
    lines = [f"# Report QC — {date.today().isoformat()}", "",
             "Generated by `tooling/report_qc.py` from the rendered deliverables in `output/<DTXSID>/`.",
             "", "| report | published | title words | tables | errors | warnings | info |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for r in results:
        c = Counter(f.severity for f in r.findings)
        lines.append(f"| {r.name} (`{r.dtxsid}`) | {r.published or '—'} | {r.stats.get('words', 0)} | "
                     f"{r.stats.get('tables', 0)} | {c['error']} | {c['warn']} | {c['info']} |")
    by_check = Counter((f.check, f.severity) for r in results for f in r.findings)
    lines += ["", "## Findings by check", "", "| check | errors | warnings | info |", "|---|---:|---:|---:|"]
    for check in sorted({c for c, _ in by_check}):
        lines.append(f"| {check} | {by_check[(check, 'error')]} | {by_check[(check, 'warn')]} | "
                     f"{by_check[(check, 'info')]} |")
    for r in results:
        lines += ["", f"## {r.name} — `{r.dtxsid}`" + (f" ({r.published})" if r.published else ""), ""]
        s = r.stats
        lines.append(f"- Title: {s.get('title', '')}")
        lines.append(f"- Design: {s.get('design')}; unit {s.get('unit')}; sexes {s.get('sexes')}")
        if s.get("bmd_summary_vs_published"):
            lines.append(f"- BMD summary vs published: {s['bmd_summary_vs_published']}")
        if s.get("go_vs_published"):
            lines.append(f"- GO top-10 vs published: {s['go_vs_published']}")
        if s.get("top_genes_vs_published"):
            lines.append(f"- Top genes vs published: {s['top_genes_vs_published']}")
        if s.get("chips"):
            lines.append(f"- Chip: {s['chips']}; BMDExpress {s.get('bmdexpress_versions')}")
        for f in sorted(r.findings, key=lambda f: (sev_order[f.severity], f.check)):
            lines.append(f"- **{f.severity}** `{f.check}` {f.message}")
            for e in f.evidence:
                lines.append(f"  - {e}")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dtxsids", nargs="*")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "output" / "QC")
    a = ap.parse_args(argv)
    os.chdir(REPO_ROOT)
    sys.path.insert(0, str(REPO_ROOT))
    from web_routes.bookshelf_routes import generated_reports
    ids = a.dtxsids or generated_reports()
    results = [qc_report(d) for d in ids]
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "qc.json").write_text(json.dumps([asdict(r) for r in results], indent=2, default=str))
    (a.out / "qc-report.md").write_text(_markdown(results))
    for r in results:
        c = Counter(f.severity for f in r.findings)
        print(f"{r.dtxsid:16} {r.published or '-':9} errors {c['error']:3}  warn {c['warn']:3}  "
              f"info {c['info']:3}  {r.name}")
    print(f"→ {a.out / 'qc-report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
