"""Generate <id>/MANIFEST.md from pages.json + _characterization.json + key findings (findings.json)."""
import json, os, sys, urllib.parse
P = json.load(open("pages.json")); FIND = json.load(open("findings.json"))
def kb(n): return f"{n/1024:.0f} KB" if n < 1 << 20 else f"{n/(1<<20):.1f} MB"
def one_line(r):
    if not r: return "**not downloaded** (CEBS unreachable)"
    k = r.get("kind"); s = ""
    if r.get("declared_ext"): s += f"⚠ named {r['declared_ext']} but is {r['actual_type']}. "
    if "error" in r: return s + f"unreadable: {r['error'][:80]}"
    if k == "text":
        t = r["text"]; notes = [n for n in t["notes"] if not n.startswith(("Chip File", "Provider"))][:3]
        s += f"{'; '.join(notes)[:160]} — table {t['n_tab_rows']}×{t['n_cols']}"
    elif k == "pdf": s += f"{r['pdf']['pages']} pp; " + " / ".join(x for x in r["pdf"]["first_lines"][:6] if x.strip())[:150]
    elif k == "docx": s += f"{r['docx']['n_tables']} tables, {r['docx']['n_images']} images; " + (r["docx"]["first_paras"][:1] or [""])[0][:130]
    elif k == "xlsx": s += "sheets: " + ", ".join(f"{x['name']} ({x['dims']})" for x in r["xlsx"]["sheets"][:6])
    elif k in ("bm2", "bmdexpress_json") and "bmdx" in r:
        b = r["bmdx"]; e = b["experiments"]
        s += f"BMDExpress project '{b['project']}': {len(e)} experiments, {len(b.get('bMDResult') or [])} BMD results, {len(b.get('categoryAnalysisResults') or [])} category analyses"
    elif k == "zip":
        m = r["members"]; s += f"{len(m)} files: " + ", ".join(os.path.basename(x['name']) for x in m[:4])[:140] + (" …" if len(m) > 4 else "")
    elif k == "csv": s += (r["csv"]["head"][:1] or [""])[0][:140]
    else: s += k or ""
    return s.replace("|", "/").replace("\n", " ")
for rid in sys.argv[1:]:
    v = P[rid]; R = {}
    if os.path.exists(f"{rid}/_characterization.json"):
        R = {r["path"]: r for r in json.load(open(f"{rid}/_characterization.json"))}
    f = FIND.get(rid, {})
    have = sum(1 for x in v["files"] if os.path.exists(f"{rid}/{urllib.parse.unquote(x['href'].rsplit('/',1)[1])}"))
    out = [f"# {rid}: {v['title'].split(':',1)[-1].strip()}", "",
           f"Source: https://cebs.niehs.nih.gov/cebs/data/publication/{rid} (DOI {v['doi']})" + (f"; GEO {', '.join(v['geo'])}" if v['geo'] else ""),
           f"Downloaded 2026-10-01: {have} of {len(v['files'])} listed files" + ("" if have == len(v["files"]) else " — **incomplete: CEBS became unreachable mid-download; see ../missing.tsv**"), ""]
    if f:
        out += ["## Key facts", ""] + [f"- {x}" for x in f.get("facts", [])] + [""]
        if f.get("issues"): out += ["## Package issues", ""] + [f"- {x}" for x in f["issues"]] + [""]
    sec = None
    for x in v["files"]:
        if x["section"] != sec:
            sec = x["section"]; out += ["", f"## {sec}", "", "| item | file | size | contents |", "|---|---|---|---|"]
        name = urllib.parse.unquote(x["href"].rsplit("/", 1)[1]); r = R.get(name)
        out.append(f"| {x['label']} | `{name}` | {kb(r['size']) if r else '—'} | {one_line(r)} |")
    open(f"{rid}/MANIFEST.md", "w").write("\n".join(out) + "\n")
    print(rid, "MANIFEST.md", len(out), "lines")
