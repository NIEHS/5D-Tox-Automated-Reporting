"""Compact human-readable digest of <id>/_characterization.json."""
import json, sys, re
def kb(n): return f"{n/1024:.0f}KB" if n < 1<<20 else f"{n/(1<<20):.1f}MB"
def keynotes(notes, keys=("Version","Timestamp","Chip","Provider","Log Trans","Data Source","Work Source",
                          "Models fit","BMR","Best Model","p-Value","P-Value","Fold","Filter","Adjust","Test",
                          "Constant Var","Restrict","Prefilter","Model Averaging","Correction","Number of",
                          "Bootstrap","Method","Cutoff","Remove","Deduplicate","Annotation","GO File","Category")):
    return [n for n in (notes or []) if any(k.lower() in n.lower() for k in keys)][:40]
R = json.load(open(sys.argv[1]))
full = len(sys.argv) > 2
for r in R:
    k = r.get("kind"); line = f"- {r['path']} [{k}, {kb(r['size'])}]"
    if "error" in r: line += f" ERROR {r['error']}"
    print(line)
    if k == "zip":
        ms = r["members"]; print(f"    {len(ms)} members; mtimes {sorted({m['mtime'] for m in ms})[:3]}..{sorted({m['mtime'] for m in ms})[-1:] if ms else ''}")
        for m in ms[:8]: print(f"      {m['name'][:120]} ({kb(m['size'])})")
    elif k == "text":
        t = r["text"]; print(f"    notes: {t['notes'][:14]}"); print(f"    table {t['n_tab_rows']}x{t['n_cols']} hdr={t['header'][:10]}")
        if t.get('row2'): print(f"    row2={t['row2'][:10]}")
    elif k == "docx":
        d = r["docx"]; print(f"    created {d['created']} mod {d['modified']} by {d['author']}/{d['last_modified_by']}; {d['n_paras']}p {d['n_tables']}t {d['n_images']}img")
        print(f"    first: {[x[:150] for x in d['first_paras'][:3]]}")
        for h in d["table_headers"][:2]: print(f"    tbl: {h[:9]}")
    elif k == "xlsx":
        x = r["xlsx"]; print(f"    created {x['created']} mod {x['modified']} by {x['creator']}")
        for s in x["sheets"][:8]: print(f"    sheet {s['name']} {s['dims']}: {s['rows'][:2]}")
    elif k == "pdf":
        p = r["pdf"]; print(f"    {p['pages']}pp created {p['created']} producer {p['producer'][:40]} creator {p['creator'][:40]}")
        print(f"    {p['first_lines'][:7]}")
    elif k == "csv": print(f"    {r['csv']['head'][:3]}")
    elif k in ("bmdexpress_json", "bm2") and "bmdx" in r:
        b = r["bmdx"]; print(f"    project={b['project']}; {len(b['experiments'])} experiments")
        for e in b["experiments"][: (99 if full else 6)]:
            print(f"      EXP {e['name']} animals={e['n_animals']} probes={e['n_probes']} doses={e['doses']} log={e['log']}")
        if b["experiments"]: print(f"      exp notes: {keynotes(b['experiments'][0]['notes'])}")
        for kk in ["oneWayANOVAResults","williamsTrendResults","curveFitPrefilterResults","oriogenResults","bMDResult","categoryAnalysisResults"]:
            rs = b.get(kk) or []
            if not rs: continue
            print(f"      {kk}: {len(rs)}; e.g. {[x['name'] for x in rs[:3]]}")
            print(f"        notes[0]: {keynotes(rs[0]['notes'])}")
    elif k == "gz": print(f"    {r.get('head')}")
