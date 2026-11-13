"""Distil <id>/_characterization.json into comparable per-report facts -> <id>/_facts.json."""
import json, sys, re, os, collections, datetime
def kv(notes):
    d = {}
    for n in notes or []:
        if ":" in n:
            k, v = n.split(":", 1); d.setdefault(k.strip(), v.strip())
    return d
def ts(s):
    for fmt in ("%m/%d/%Y %H:%M.%S", "%m/%d/%Y"):
        try: return datetime.datetime.strptime(s.strip(), fmt).date().isoformat()
        except Exception: pass
    return None
def dt(s):
    if not s or s == "None": return None
    m = re.search(r"(\d{4})-?(\d{2})-?(\d{2})", s)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None

def analysis_sig(b, src):
    """One row per bMDResult chain, with prefilter + BMD + category settings."""
    pre = {}
    for k in ("oneWayANOVAResults", "williamsTrendResults", "curveFitPrefilterResults", "oriogenResults"):
        for r in b.get(k) or []: pre[r["name"]] = (k, kv(r["notes"]), r["notes"])
    cats = collections.defaultdict(list)
    for c in b.get("categoryAnalysisResults") or []:
        n = kv(c["notes"]); cats[n.get("Work Source")].append((c["name"], n))
    exps = {e["name"]: e for e in b["experiments"]}
    rows = []
    for r in b.get("bMDResult") or []:
        n = kv(r["notes"]); ws = n.get("Work Source"); pk, pn, praw = pre.get(ws, (None, {}, []))
        e = exps.get(n.get("Data Source"), {})
        rows.append(dict(src=src, experiment=n.get("Data Source"), animals=e.get("n_animals"), probes=e.get("n_probes"),
            doses=e.get("doses"), chip=kv(e.get("notes")).get("Chip"),
            exp_version=kv(e.get("notes")).get("BMDExpress2 Version") or kv(e.get("notes")).get("BMDExpress3 Version"),
            exp_date=ts(kv(e.get("notes")).get("Timestamp", "")),
            prefilter=pk, prefilter_name=ws,
            pf_perm=pn.get("Number of Permutations"), pf_p=pn.get("Unadjusted P-Value Cutoff") or pn.get("Adjusted P-Value Cutoff") or pn.get("P-Value Cutoff"),
            pf_mtc=pn.get("Multiple Testing Correction"), pf_fold=pn.get("Used Fold Filter with cuttoff") or ("none" if "nofoldfilter" in (ws or "") else None),
            pf_extra={k: v for k, v in pn.items() if k not in ("Data Source","Work Source","Timestamp (Start Time)","BMDExpress2 Version","BMDExpress3 Version")},
            bmd_version=n.get("BMDExpress2 Version") or n.get("BMDExpress3 Version"), bmd_date=ts(n.get("Timestamp (Start Time)", "")),
            models=n.get("Models fit"), bmr=f"{n.get('BMR Type')} {n.get('BMR Factor')}", best=n.get("Best Model Selection"),
            const_var=n.get("Constant Variance"), restrict_power=n.get("Restrict Power"),
            ma=n.get("Model Averaging") or n.get("Use Model Averaging"),
            bmd_extra={k: v for k, v in n.items() if not k.endswith("version") and k not in ("Data Source","Work Source","Timestamp (Start Time)")},
            categories=[c[0][len(r['name']):] if c[0].startswith(r['name']) else c[0] for c in cats.get(r["name"], [])]))
    return rows

R = json.load(open(sys.argv[1])); root = os.path.dirname(sys.argv[1])
F = dict(report=os.path.basename(root), files=len([r for r in R if "/" not in r["path"]]), kinds=collections.Counter(r["kind"] for r in R),
         dates=collections.defaultdict(list), chains=[], bmdx_sources=[], expression_files=[], apical_bmds=[], flags={})
for r in R:
    if "error" in r: F.setdefault("errors", []).append((r["path"], r["error"])); continue
    p = r["path"]; k = r["kind"]
    if k in ("docx",): F["dates"]["docx"] += [dt(r["docx"]["created"]), dt(r["docx"]["modified"])]
    if k == "xlsx": F["dates"]["xlsx"] += [d for d in (dt(r["xlsx"]["created"]), dt(r["xlsx"]["modified"])) if d and d < "2026-09"]
    if k == "pdf": F["dates"]["pdf"] += [dt(r["pdf"]["created"])]
    if k == "zip": F["dates"]["zip_members"] += [m["mtime"] for m in r["members"]]
    if k in ("bmdexpress_json", "bm2") and "bmdx" in r:
        b = r["bmdx"]; F["bmdx_sources"].append(dict(path=p, kind=k, project=b["project"], n_exp=len(b["experiments"])))
        F["chains"] += analysis_sig(b, p)
        for e in b["experiments"]:
            F["dates"]["bmdx"].append(ts(kv(e["notes"]).get("Timestamp", "")))
    if k == "text":
        t = r["text"]; n = kv(t["notes"])
        if n.get("Timestamp"): F["dates"]["bmdx_text"].append(ts(n["Timestamp"]))
        if n.get("Timestamp (Start Time)"): F["dates"]["bmdx_text"].append(ts(n["Timestamp (Start Time)"]))
        if t["header"][:1] and t["header"][0] in ("Something", "Probe Id", "SampleID") or (t.get("row2") or [""])[0] == "Doses":
            F["expression_files"].append(dict(path=p, probes=t["n_tab_rows"]-2, samples=t["n_cols"]-1, chip=n.get("Chip"),
                                              version=n.get("BMDExpress2 Version") or n.get("BMDExpress3 Version"), date=ts(n.get("Timestamp", "") or "")))
    if k == "xlsx":
        cols = [c for s in r["xlsx"]["sheets"] for row in s["rows"][:1] for c in row]
        if "model_version" in cols or "BMDL" in cols: F["apical_bmds"].append(dict(path=p, kind="BMDS parameter workbook", sheets=[s["name"] for s in r["xlsx"]["sheets"]]))
    if k == "docx" and any("BMDS version" in x for x in r["docx"]["first_paras"]):
        F["apical_bmds"].append(dict(path=p, kind="BMDS model-fit report", version=[x for x in r["docx"]["first_paras"] if "BMDS version" in x][0]))
    low = p.lower()
    for flag, pat in dict(cel="\\.cel", microarray="microarr", fastq="fastq", read_counts="read_count|raw_read|counts", pca="principal|pca", efdr="efdr|false_positive|synthetic_null",
                          qc_report="qc", batch_correction="batch", tempo_manifest="manifest", gene_description="gene_description", pipeline_eval="pipeline",
                          inhaled_dose="inhaled", removal="remov").items():
        if re.search(pat, low): F["flags"].setdefault(flag, []).append(p)
for k in list(F["dates"]):
    v = sorted(x for x in F["dates"][k] if x and x > "1990"); F["dates"][k] = [v[0], v[-1], len(v)] if v else None
json.dump(F, open(os.path.join(root, "_facts.json"), "w"), indent=1, default=str)
# compact print
print(f"== {F['report']}  files={F['files']} kinds={dict(F['kinds'])}")
print("  dates:", {k: v for k, v in F["dates"].items() if v})
print("  bmdx sources:", F["bmdx_sources"])
groups = collections.OrderedDict()
for c in F["chains"]:
    sig = (os.path.basename(c['src'])[:45], c['chip'], c['bmd_version'], c['prefilter'], c['pf_perm'], c['pf_p'], c['pf_mtc'], c['pf_fold'], c['models'], c['bmr'], c['best'], c['ma'], tuple(c['categories']))
    groups.setdefault(sig, []).append(c)
for sig, cs in groups.items():
    src, chip, ver, pf, perm, pp, mtc, fold, models, bmr, best, ma, cats = sig
    print(f"  CHAIN x{len(cs)} [{src}] chip={chip} v={ver} dates={sorted({c['bmd_date'] for c in cs})}")
    print(f"     prefilter={pf} perm={perm} p={pp} mtc={mtc} fold={fold} extra={ {k:v for k,v in cs[0]['pf_extra'].items() if k not in ('Number of Permutations','Unadjusted P-Value Cutoff','Multiple Testing Correction','Used Fold Filter with cuttoff')} }")
    print(f"     bmd: models={models} bmr={bmr} best={best} ma={ma} extra={ {k:v for k,v in cs[0]['bmd_extra'].items() if k in ('Constant Variance','Restrict Power','BMDL and BMDU Model Selection','Best Model Selection with Flagged Hill Model','Flag Hill Model with \'k\' Parameter <','Maximum Iterations','Confidence Level','BMD Method','Model Averaging','Bootstrap','Number of Bootstraps','Distribution','Variance')} }")
    print(f"     cats={[x[:75] for x in cats]}")
    print(f"     exps={[(c['experiment'], c['animals'], c['probes']) for c in cs][:20]}")
print("  expression:", [(os.path.basename(e['path'])[:50], e['probes'], e['samples'], e['version'], e['date']) for e in F["expression_files"]])
print("  apical:", F["apical_bmds"])
print("  flags:", {k: len(v) for k, v in F["flags"].items()})
