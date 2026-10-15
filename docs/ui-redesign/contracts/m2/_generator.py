"""M2 contract fixtures, proposed FilesView shape, built from a real session's files and validation report.
Read-only on the session. Usage: fixture2.py <session dir> <out.json> <study id> <phase>"""
import json, os, sys, hashlib, re, datetime
from collections import Counter, OrderedDict

sess, out, sid, phase = sys.argv[1:5]
has_report = os.path.exists(f"{sess}/validation_report.json")
vr = json.load(open(f"{sess}/validation_report.json")) if has_report else {"fingerprints": {}, "issues": [], "coverage_matrix": {}, "run_at": None}
fps = vr["fingerprints"]; tname = {k: v["filename"] for k, v in fps.items()}
APICAL = ["Body Weight", "Clinical Chemistry", "Hematology", "Hormones", "Organ Weight", "Tissue Concentration", "Clinical"]
DT_SAY = {"tox_study": "the study's own measurements", "inferred": "gap-filled values prepared for BMD modelling",
          "gene_expression": "gene-expression data"}
PL_SAY = {"Clinical": "Clinical observations"}
DT_LABEL = {"tox_study": "The study's own measurements", "inferred": "Gap-filled for BMD modelling", "gene_expression": "Gene expression"}
DT_LONG = {"tox_study": "Each animal's values as measured, gaps included. The NTP statistics are computed from these.",
           "inferred": "Values prepared for BMDExpress: gaps filled, dose groups with no survivors dropped. Used for benchmark doses, never for the NTP statistics.",
           "gene_expression": "Transcriptomic data: expression tables, or a BMDExpress project holding the gene analysis."}
def h(s): return hashlib.sha256(s.encode()).hexdigest()[:10]
def iso(ts): return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def chash(p): return "sha256:" + hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]
def allowed(): return {"allowed": True, "code": None, "say": None}

# ---- rows: the files as the person brought them in -------------------------
source_of = {}                       # table name -> brought-in name
for f in sorted(os.listdir(f"{sess}/files")):
    if f.endswith(".sidecar.json"):
        s = json.load(open(f"{sess}/files/{f}"))
        source_of[f[:-len(".sidecar.json")] + ".txt"] = s.get("source")
def row_of(table): return source_of.get(table) or table
fp_by_table = {v["filename"]: v for v in fps.values()}

rows = OrderedDict()
listing = sorted(os.listdir(f"{sess}/files"))
for f in listing:
    if f.endswith(".sidecar.json") or f.endswith(".units.json"): continue
    r = row_of(f)
    if r not in rows: rows[r] = []
    rows[r].append(f)
originals = set(os.listdir(f"{sess}/_originals")) if os.path.isdir(f"{sess}/_originals") else set()

def kind_of(name):
    e = os.path.splitext(name)[1].lower()
    return {".xlsx": "workbook", ".bm2": "bm2"}.get(e, "table")

def tokens(exps):
    t = set()
    for e in exps or []:
        m = re.match(r"^(Kidney|Liver|Heart|Lung|Ovary|Thyroid)_(.+)_(Male|Female)(_No0)?$", e)
        if m: t.add(m.group(2))
    return sorted(t)

files = []; issues_by_row = {}
for r, tables in rows.items():
    stored = f"{sess}/files/{tables[0]}"
    src_path = f"{sess}/_originals/{r}" if r in originals else stored
    stem = os.path.splitext(r)[0]
    units_name = stem + ".units.json"
    units_path = next((p for p in (f"{sess}/_originals/{units_name}", f"{sess}/files/{units_name}") if os.path.exists(p)), None)
    fp0 = fp_by_table.get(tables[0])
    plat = fp0["platform"] if fp0 else None; dt = fp0["data_type"] if fp0 else None
    k = kind_of(r)
    companions = []
    if units_path: companions.append({"name": units_name, "role": "units", "say": "its measurement units"})
    for t in tables:
        if t != r:
            companions.append({"name": t, "role": "table", "say": "the table the check made from it, one column per animal, for BMDExpress"})
            companions.append({"name": t[:-4] + ".sidecar.json", "role": "sidecar", "say": "what the table can't hold: each animal's group, day and terminal flag"})
    # units
    if k == "bm2" or dt == "gene_expression": units = None
    elif plat == "Clinical": units = {"state": "not_needed", "values": {}, "say": "Observations are counted; they have no units"}
    elif k == "workbook": units = {"state": "not_read", "values": {}, "say": "[units pending]: the workbook states them in its Key sheet, but they are not read from a workbook yet"}
    elif units_path:
        u = json.load(open(units_path)); units = {"state": "stated", "values": u, "say": f"{len(u)} unit(s), from {units_name}"}
    elif fp0 is None: units = None
    else: units = {"state": "missing", "values": {}, "say": "[units pending]: no units file came with this file"}
    # content of each table
    tab = []
    for t in tables:
        fp = fp_by_table.get(t)
        if not fp: continue
        isbm2 = fp["file_type"] == "bm2"
        tab.append({"name": t, "sexes": fp.get("sexes") or [], "doses": fp.get("dose_groups") or [], "dose_unit": fp.get("dose_unit"),
                    "animals": sum((fp.get("n_animals_by_dose") or {}).values()), "animals_by_dose": fp.get("n_animals_by_dose") or {},
                    "measurements": None if isbm2 else len(fp.get("endpoint_names") or []),
                    "measurement_sample": [] if isbm2 else (fp.get("endpoint_names") or [])[:5],
                    "selection_groups": fp.get("selection_groups") or []})
    bm2 = None
    if k == "bm2" and fp0:
        ex = fp0.get("endpoint_names") or []; tk = tokens(ex)
        bm2 = {"experiments": ex, "species": fp0.get("species"), "test_articles": tk}
    flags = []
    if bm2 and len(bm2["test_articles"]) > 1:
        flags.append({"code": "several_test_articles", "level": "warn",
                      "say": f"This BMDExpress project holds experiments of {len(bm2['test_articles'])} test articles ({', '.join(bm2['test_articles'])}). Only this study's belong in it."})
    if r in originals and dt == "inferred":
        flags.append({"code": "name_says_gap_filled", "level": "warn",
                      "say": "This file has one row per animal, like the study's own measurements, but its name doesn't say so (no _truth or _tox_study), so it was taken as gap-filled data. Check its data type."})
    if fp0 is None:
        status, basis = "not_checked", None
    else:
        status = "unconfirmed"
        basis = "bm2_experiments" if k == "bm2" else ("file_name" if (plat or dt) else "none")
    detected = None if fp0 is None else {"platform": plat, "data_type": dt, "basis": basis,
        "say": {"bm2_experiments": "From the experiment names inside the BMDExpress project", "file_name": "From the file name",
                "none": "Not recognised from its name or its content"}[basis]}
    if fp0 is None: csay = "[not checked yet]"
    elif not (plat or dt): csay = "[not recognised]"
    else: csay = f"{PL_SAY.get(plat, plat) if plat else 'Gene expression'} · {DT_SAY[dt]}"
    pend = []
    if units and units["state"] in ("missing", "not_read"): pend.append({"what": "units", "say": "[units pending]", "fix": "M2"})
    if k == "bm2" and fp0 is not None and not (fp0.get("endpoint_names") or fp0.get("dose_groups")):
        pend.append({"what": "contents", "say": "[contents not read: its doses and animals were not compared with the other files]", "fix": "M2"})
    if fp0 is not None and not (plat or dt): pend.append({"what": "classification", "say": "[what this file is: pending]", "fix": "M2"})
    files.append({"name": r, "kind": k, "type": os.path.splitext(r)[1].lstrip(".").lower(),
                  "size": os.path.getsize(src_path), "added_at": iso(os.path.getmtime(src_path)), "content_hash": chash(src_path),
                  "companions": companions, "units": units, "tables": tab, "bm2": bm2,
                  "study_number": (fp0 or {}).get("study_number"), "checked": fp0 is not None,
                  "classification": {"platform": plat, "data_type": dt, "say": csay, "detected": detected, "stated": None,
                                     "status": status, "flags": flags},
                  "issues": [], "pending": pend,
                  "acts": {"remove": allowed(), "classify": allowed() if fp0 else
                           {"allowed": False, "code": "not_validated", "say": "Run the file check first: it says what each file is."}}})
row_by_name = {f["name"]: f for f in files}

# ---- issues ----------------------------------------------------------------
def plat2(p):
    if not p: return None, None
    a, _, b = p.partition("|"); return a, (b or None)
issues = []
for i in vr["issues"]:
    t, sev = i["issue_type"], i["severity"]
    if t == "method_mismatch": continue
    p, dt = plat2(i.get("platform")); d = i.get("details") or {}
    tabs = [tname.get(x, x) for x in i["files_involved"]]
    if t.startswith("value_"):
        cm = vr["coverage_matrix"].get(f"{p}|tox_study") or {}
        tabs += [tname.get(x, x) for x in (cm.get("txt_csv") or [])]
    names = list(OrderedDict.fromkeys(row_of(x) for x in tabs))
    group, todo, feeds, say = "look", None, None, i["message"]
    P = PL_SAY.get(p, p)
    if t == "roster_subset":
        group, feeds = "expected", "M6"
        m = re.match(r"(.+?) \((\w+)\): (\d+)/(\d+) animals — missing (\d+) \((.*)\)", i["message"])
        f, sx, a, b, kk, ex = m.groups()
        say = (f"{kk} of the {b} {sx.lower()} animals in the study's roster are not in {row_of(f)}, for example {ex}. "
               "Animals that died early or were kept for blood sampling are often missing from some measurements; the data review accounts for each one.")
    elif t == "missing_tier" and "no .bm2" in i["message"]:
        group = "expected"; say = f"No BMDExpress project (.bm2) for {P}. Process computes its benchmark doses itself."
    elif t == "missing_tier" and "no xlsx" in i["message"]:
        group = "expected"; say = f"No study workbook (.xlsx) for {P}. Its tables are used as they are."
    elif t == "missing_tier" and p == "gene_expression":
        group = "expected"; say = "No gene-expression tables beside the BMDExpress project. The project already holds the analysis."
    elif t == "unverified_derived_data":
        say = f"{P}: there is no study workbook (.xlsx) to check the tables' values against, so they are used as given, unverified."
        todo = f"If you have the study's Individual Animal workbook for {P}, add it: every value is then checked against it."
    elif t == "dose_mismatch":
        group = "fix"; ea, eb = d.get("expected", []), d.get("actual", [])
        a, b = names[0], names[1]
        oa = [x for x in ea if x not in eb]; ob = [x for x in eb if x not in ea]
        say = (f"{a} and {b} are both {P} data for {(row_by_name[a]['tables'][0]['sexes'] or ['?'])[0].lower()}s, but their doses differ: {a} has "
               f"{', '.join(map(lambda x: format(x, 'g'), oa)) or 'none'} where {b} has {', '.join(map(lambda x: format(x, 'g'), ob)) or 'none'}. "
               "One of them is wrong, or belongs to another study.")
        todo = "Settle the conflict: keep the right file."
    elif t == "redundant_files":
        group = "fix"
        say = f"{names[0]} and {names[1]} hold the same data (same platform, sex, doses, measurements and animals). Both would be combined, so it would count twice."
        todo = "Settle the conflict: keep one."
    elif t == "unassigned_file":
        group = "fix"; say = f"The tool can't tell what {names[0]} is, from its name or its content."
        todo = "Say what it is (its platform and data type) in the files table, or remove it if it isn't study data."
    elif t.startswith("value_"):
        group = "fix"; ex = (d.get("examples") or [{}])[0]
        say = (f"{P}: {d.get('count')} of {d.get('total_compared')} values in the tables differ from the study workbook "
               f"(for example animal {ex.get('animal_id')}, {ex.get('day')}, {ex.get('endpoint')}: workbook {ex.get('xlsx')}, table {ex.get('csv')}). "
               "A table must be an exact copy of the workbook's data.")
        todo = "Remove the table that differs (the workbook alone is enough), or replace it with one made from the workbook."
    elif t == "animal_count_mismatch" and sev == "warning":
        feeds = "M6"; xc, tc = d.get("xlsx_count", 0), d.get("txt_csv_count", 0)
        say = f"{P}: the workbook has {xc} animals and the tables {tc}, so {xc - tc} of the workbook's animals are not in the tables. The data review accounts for each one."
    elif t == "sex_mismatch":
        say = f"{P}: the files don't cover the same sexes. " + i["message"]
    iid = "iss_" + h(t + "|" + (i.get("platform") or "") + "|" + "|".join(sorted(tabs)) + "|" + i["message"])
    issues.append({"id": iid, "type": t, "severity": sev, "group": group, "platform": p, "data_type": dt,
                   "sex": d.get("sex"), "files": names, "tables": tabs, "say": say, "what_to_do": todo,
                   "feeds": feeds, "fix": "M2" if group == "fix" else None, "message": i["message"],
                   "details": {k2: v for k2, v in d.items() if k2 not in ("expected_file", "actual_file")}})
    for n in names:
        if n in row_by_name: row_by_name[n]["issues"].append(iid)

# ---- conflicts ---------------------------------------------------------------
conflicts = []
for r in issues:
    if r["type"] not in ("dose_mismatch", "redundant_files") and not (r["type"] == "animal_count_mismatch" and r["severity"] == "error"): continue
    cf = []
    for n in r["files"]:
        fr = row_by_name[n]; tb = fr["tables"][0]
        cf.append({"name": n, "kind": fr["kind"], "data_type": fr["classification"]["data_type"], "sexes": tb["sexes"], "doses": tb["doses"],
                   "animals": tb["animals"], "animals_by_dose": tb["animals_by_dose"], "measurements": tb["measurement_sample"],
                   "added_at": fr["added_at"], "size": fr["size"]})
    diffs = []
    for key, label in (("doses", "Doses"), ("animals_by_dose", "Animals per dose"), ("animals", "Animals"), ("sexes", "Sexes"), ("measurements", "Measurements")):
        vals = {x["name"]: x[key] for x in cf}
        if len({json.dumps(v, sort_keys=True) for v in vals.values()}) > 1: diffs.append({"what": key, "say": label, "by_file": vals})
    sug = None
    raw = next(i for i in vr["issues"] if r["message"] == i["message"])
    kinds = {x["kind"] for x in cf}
    if raw.get("suggested_precedence") and len(kinds) > 1:
        sug = {"name": row_of(tname.get(raw["suggested_precedence"], raw["suggested_precedence"])),
               "why": "The check suggests the file of the more original kind (a workbook before a table, a table before a .bm2), or the first one when both are of one kind. It does not know which is right."}
    conflicts.append({"id": "cfl_" + r["id"][4:], "issue": r["id"], "type": r["type"], "platform": r["platform"], "data_type": r["data_type"],
                      "say": r["say"], "files": cf, "differences": diffs, "suggested": sug, "decision": None,
                      "acts": {"keep": allowed()}})

# ---- coverage ------------------------------------------------------------
cov = []
for key, tiers in vr["coverage_matrix"].items():
    p, dt = plat2(key)
    if key == "gene_expression": p, dt = None, "gene_expression"
    tb = list(OrderedDict.fromkeys(row_of(tname.get(x, x)) for x in (tiers.get("txt_csv") or [])))
    wb = row_of(tname.get(tiers.get("xlsx"), tiers.get("xlsx"))) if tiers.get("xlsx") else None
    bm = row_of(tname.get(tiers.get("bm2"), tiers.get("bm2"))) if tiers.get("bm2") else None
    if dt == "gene_expression":
        level, say = ("ok", "The BMDExpress project holds the gene-expression analysis.") if bm else ("block", "Needs the BMDExpress project (.bm2) with the gene-expression analysis.")
    elif p == "Clinical" and not tb: level, say = "warn", "Only the study workbook; clinical observations are read from their CSV files."
    elif p == "Clinical": level, say = "ok", "Observations are counted and tabulated; they are not modelled."
    elif wb and not tb and dt == "tox_study" and p != "Clinical":
        level, say = "warn", "Only the study workbook. Combining from a workbook alone left out measurement sets without an error in a test; bring in the tables made from it too."
    elif dt == "inferred" and bm: level, say = "ok", "The BMDExpress project's benchmark doses are used."
    elif dt == "inferred": level, say = "ok", "Gap-filled tables, used for BMD modelling."
    else: level, say = "ok", "The study's own measurements: the NTP statistics and Process's benchmark doses are computed from them."
    cov.append({"key": key, "platform": p, "label": PL_SAY.get(p, p) if p else "Gene expression", "data_type": dt,
                "data_type_say": DT_SAY.get(dt), "workbook": wb, "tables": tb, "bm2": bm, "level": level, "say": say})

cnt = Counter(r["group"] for r in issues)
n = len(files); nconf = len(conflicts); nfix = cnt.get("fix", 0)
unconf = sum(1 for f in files if f["classification"]["status"] in ("unconfirmed", "not_checked", "needs_reconfirm"))
check = None if not has_report else {
    "run_at": vr["run_at"][:19] + "Z", "current": True, "why_not_current": None,
    "counts": {"fix": nfix, "look": cnt.get("look", 0), "expected": cnt.get("expected", 0)},
    "not_shown": ({"count": sum(1 for i in vr["issues"] if i["issue_type"] == "method_mismatch"), "fix": "M5",
                  "say": "Checks of the analysis method are shown with the method, in Method and report definition."}
                  if any(i["issue_type"] == "method_mismatch" for i in vr["issues"]) else None)}
prog = [{"step": "bring_in", "status": "done" if n else "todo", "say": f"{n} file(s) in the study" if n else "No files yet"}]
if not has_report: prog.append({"step": "check", "status": "todo" if n else "waiting", "say": "Not checked yet"})
else: prog.append({"step": "check", "status": "blocked" if nfix else "done",
                   "say": f"Checked {vr['run_at'][:10]}: " + (f"{nfix} problem(s) to fix" if nfix else "nothing blocks")})
prog.append({"step": "confirm", "status": ("waiting" if not has_report else ("todo" if unconf else "done")),
             "say": (f"{unconf} of {n} file(s) not yet confirmed" if has_report else "After the check")})
prog.append({"step": "conflicts", "status": ("todo" if nconf else ("not_needed" if has_report else "waiting")),
             "say": f"{nconf} conflict(s) to settle" if nconf else ("No conflicts" if has_report else "After the check")})
if not n: nxt = {"act": "ADD_FILES", "say": "Bring in the study's files", "fix": "M2"}
elif not has_report: nxt = {"act": "VALIDATE", "say": "Check the files", "fix": "M2"}
elif unconf: nxt = {"act": "CONFIRM_CLASSIFICATION", "say": "Confirm what each file is", "fix": "M2"}
elif nconf: nxt = {"act": "RESOLVE", "say": "Settle the conflicts between files", "fix": "M2"}
elif nfix: nxt = {"act": "VALIDATE", "say": "Fix what the check found, then check again", "fix": "M2"}
else: nxt = {"act": "INTEGRATE", "say": "Combine the files into one dataset", "fix": "M3"}

LEGAL = {"EMPTY": {"ADD_FILES"}, "UPLOADED": {"ADD_FILES", "REMOVE_FILE", "RESET", "VALIDATE"},
         "VALIDATION_ERRORS": {"ADD_FILES", "REMOVE_FILE", "RESET", "VALIDATE", "RESOLVE", "CONFIRM_CLASSIFICATION"}}
LEGAL["VALIDATED"] = LEGAL["VALIDATION_ERRORS"] | {"INTEGRATE"}; LEGAL["INTEGRATED"] = LEGAL["APPROVED"] = LEGAL["VALIDATED"] | {"APPROVE", "PROCESS", "STATE_DATASET_FACTS"}
def act(a, why):
    return allowed() if a in LEGAL[phase] else {"allowed": False, "code": "phase_not_allowed", "say": why}
acts = {"add": act("ADD_FILES", ""), "check": act("VALIDATE", "This study has no files to check yet. Bring in the study's files first."),
        "resolve": act("RESOLVE", "Run the file check first: conflicts are found by the check."),
        "classify": act("CONFIRM_CLASSIFICATION", "Run the file check first: it says what each file is."),
        "remove": act("REMOVE_FILE", "This study has no files to remove."), "reset": act("RESET", "This study has no files to remove.")}
integ = None
if os.path.exists(f"{sess}/integrated.json"):
    integ = {"state": "unrecorded", "made_at": iso(os.path.getmtime(f"{sess}/integrated.json")), "fix": "M3",
             "say": "The files were combined into one dataset on " + iso(os.path.getmtime(f"{sess}/integrated.json"))[:10] + "."}
view = {"id": sid, "phase": phase, "takes_files": {"allowed": True, "code": None, "say": None},
        "files_token": "sha256:" + hashlib.sha256(json.dumps([files, issues], sort_keys=True).encode()).hexdigest()[:16],
        "progress": prog, "next": nxt, "acts": acts, "files": files, "check": check, "issues": issues,
        "conflicts": conflicts, "coverage": cov, "removed": [], "integration": integ,
        "classification_choices": {
            kind: [{"data_type": dt_, "label": DT_LABEL[dt_], "say": DT_LONG[dt_], "platforms": pl}
                   for dt_, pl in opts]
            for kind, opts in (("table", (("tox_study", APICAL), ("inferred", APICAL[:-1]), ("gene_expression", []))),
                               ("workbook", (("tox_study", APICAL),)),
                               ("bm2", (("inferred", APICAL[:-1]), ("gene_expression", []))))},
        "limits": {"max_file_bytes": 536870912, "accepted": [".bm2", ".csv", ".txt", ".xlsx", ".zip", ".units.json"]}}
json.dump(view, open(out, "w"), indent=1, ensure_ascii=False)
print(out, n, "rows", dict(cnt), len(conflicts), "conflicts")
