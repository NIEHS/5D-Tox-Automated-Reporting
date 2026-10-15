"""Build M1's mock world (fixtures/m1/studies.json + detail.<id>.json) from
contract.md §4 (extracted to fixtures/m1/*.json) and the real state fixtures.

The contract's list is abridged (five chemicals) and two of its rows were real
on 2026-10-14 while the kit's state fixtures put those ids in other phases
(scratch copies). So that the list, the study page and the state agree for
every mocked id, this script:
  - keeps every contract row, aligning `stands` to the state fixture's phase
    (contract §3 wording) where a state fixture exists;
  - adds rows (CONSTRUCTED) for the other state fixtures and for the report's
    mouse study and its published content;
  - writes a detail for every row (banner wording from spec §3 S3).
"""
import copy, json, sys
from pathlib import Path

M1 = Path(sys.argv[1])          # ui/src/api/mocks/fixtures/m1
REAL = Path(sys.argv[2])        # ui/src/api/mocks/fixtures/real
load = lambda p: json.loads(p.read_text())["body"]

lst = load(M1 / "studies.json") if (M1 / "studies.contract.json").exists() is False else load(M1 / "studies.contract.json")
(M1 / "studies.contract.json").write_text((M1 / "studies.json").read_text()) if not (M1 / "studies.contract.json").exists() else None
lst = load(M1 / "studies.contract.json")
states = {p.name[len("state."):-len(".json")]: load(p) for p in REAL.glob("state.*.json")}

FMT_2026 = {"definition": "eras/niehs-2026", "source": "default", "era": "eras/niehs-2026",
            "title": "NIEHS Report, as published in 2026 (NIEHS-12, 13): the format for new studies",
            "title_short": "NIEHS Report, 2026", "changes": 0,
            "say": "No published report is on file for this chemical, so the study uses the format for new studies: the NIEHS Report as published in 2026."}
ERA = {"eras/niehs-2023": ("NIEHS Report, as published in March 2023 (NIEHS-07 … 10)", "NIEHS Report, March 2023", "March 2023"),
       "eras/niehs-2022": ("NIEHS Report, as published in October 2022 (NIEHS-02 … 06), one file", "NIEHS Report, October 2022", "October 2022")}

def stands(phase, processed):
    W = {"EMPTY": ("No files yet", "Bring in the study's files", "M2"),
         "UPLOADED": ("Files brought in, not yet validated", "Validate the files", "M2"),
         "VALIDATION_ERRORS": ("The files have problems to fix", "Fix the problems the validation found", "M2"),
         "VALIDATED": ("Files validated, not yet integrated", "Integrate the data", "M3"),
         "INTEGRATED": ("Data integrated", None, None), "APPROVED": ("Data reviewed", None, None)}
    say, nsay, fix = W[phase]
    if nsay is None:
        nsay, fix = ("Review the report's sections", "D1") if processed else ("Process the data", "P1")
    return {"phase": phase, "say": say, "next": {"say": nsay, "fix": fix}}

NOT_ON_SHELF = {"on_shelf": False, "url": None, "say": "Not yet: the study has no report (it has not been processed)"}
def shelf(id, processed):
    return {"on_shelf": True, "url": f"/Bookshelf/{id}", "say": "On the Bookshelf (draft)"} if processed else dict(NOT_ON_SHELF)

def study_row(id, st, report, date, nbk, era, last_changed):
    title, short, when = ERA[era]
    return {"id": id, "kind": "study", "chemical_dtxsid": id, "chemical_dtxsid_from": "id",
            "identity": {"name": st["identity"]["name"], "casrn": st["identity"]["casrn"], "short_name": st["identity"]["short_name"],
                         "source": {"kind": "unknown", "service": None, "confirmed_at": None}},
            "stands": stands(st["phase"], st["processed"]), "processed": st["processed"], "last_changed": last_changed,
            "format": {"definition": f"studies/{id}/document", "source": "study", "era": era, "title": title, "title_short": short,
                       "changes": 0, "say": f"This chemical has a published report, {report} ({when}). The study is written in that book's format: the NIEHS Report as published in {when}, unaltered."},
            "published": {"report": report, "date": date, "nbk": nbk}, "bookshelf": shelf(id, st["processed"]),
            "relations": {"parent": None, "members": [], "companion": None, "twin": None, "others": []},
            "actions": {"open": {"allowed": True}, "delete": {"allowed": True, "code": None, "say": None}}, "notes": []}

chem = {c["dtxsid"]: c for c in lst["chemicals"]}
# 1. align contract rows to the state fixtures
for c in lst["chemicals"]:
    for r in c["sessions"]:
        st = states.get(r["id"])
        if st and st["phase"] and r["kind"] in ("study", "member", "other"):
            r["stands"] = stands(st["phase"], st["processed"])
            r["processed"] = st["processed"]
            if not st["processed"] and r["bookshelf"]["on_shelf"] and r["kind"] != "member":
                r["bookshelf"] = dict(NOT_ON_SHELF)
# 2. the report's mouse study and its published content (CONSTRUCTED from the rat's and PFHxSAm's rows)
dcb = chem["DTXSID1020431"]
rat = next(r for r in dcb["sessions"] if r["id"] == "DTXSID1020431_rat")
mouse = copy.deepcopy(rat)
mouse.update(id="DTXSID1020431_mouse", last_changed="2026-10-12T11:47:02Z")
mouse["relations"]["others"] = ["DTXSID1020431_rat"]
mouse["actions"]["delete"]["say"] = "This is the mouse study of the report DTXSID1020431. Deleting it would break that report."
pf_comp = next(r for r in chem["DTXSID50469320"]["sessions"] if r["kind"] == "companion")
comp = copy.deepcopy(pf_comp)
comp.update(id="DTXSID1020431_published", last_changed="2026-10-11T16:20:00Z")
comp["identity"].update(name="1,4-Dichlorobenzene", casrn="106-46-7")
comp["format"]["say"] = "This session holds NIEHS-13's own content and structure, built from the published book."
comp["published"] = {"report": "NIEHS-13", "date": "2026-04", "nbk": "NBK621744"}
comp["bookshelf"]["url"] = "/Bookshelf/DTXSID1020431_published"
comp["relations"]["twin"] = "DTXSID1020431"
dcb["sessions"] = [dcb["sessions"][0], rat, mouse, comp]
# 3. rows for the other state fixtures (CONSTRUCTED)
extra = [("DTXSID1022477", "NIEHS-09", "2023-03", "NBK589973", "eras/niehs-2023", "2026-10-14T09:12:00Z"),
         ("DTXSID2029905", "NIEHS-08", "2023-03", "NBK589991", "eras/niehs-2023", "2026-10-14T09:40:00Z"),
         ("DTXSID4028880", "NIEHS-05", "2022-10", "NBK585459", "eras/niehs-2022", "2026-10-14T09:30:00Z"),
         ("DTXSID6024701", "NIEHS-03", "2022-10", "NBK585458", "eras/niehs-2022", "2026-10-14T09:50:00Z")]
for id, rep, date, nbk, era, lc in extra:
    st = states[id]
    row = study_row(id, st, rep, date, nbk, era, lc)
    lst["chemicals"].append({"dtxsid": id, "name": st["identity"]["name"], "casrn": st["identity"]["casrn"],
                             "primary": id, "can_create": False, "sessions": [row]})
# a study with no identity on file (the kit's EMPTY fixture), and a chemical with only a tool's session
blank = {"id": "DTXSID9000001", "kind": "study", "chemical_dtxsid": "DTXSID9000001", "chemical_dtxsid_from": "id",
         "identity": {"name": None, "casrn": None, "short_name": None, "source": {"kind": "unknown", "service": None, "confirmed_at": None}},
         "stands": stands("EMPTY", False), "processed": False, "last_changed": "2026-10-14T08:00:00Z", "format": dict(FMT_2026),
         "published": None, "bookshelf": dict(NOT_ON_SHELF),
         "relations": {"parent": None, "members": [], "companion": None, "twin": None, "others": []},
         "actions": {"open": {"allowed": True}, "delete": {"allowed": True, "code": None, "say": None}},
         "notes": [{"level": "warn", "code": "identity_missing", "say": "No chemical identity is on file for this study."}]}
lst["chemicals"].append({"dtxsid": "DTXSID9000001", "name": None, "casrn": None, "primary": "DTXSID9000001", "can_create": False, "sessions": [blank]})
tool = copy.deepcopy(blank)
# CONSTRUCTED: a tool's session of PFOA (DTXSID8031865, as PubChem lists it for CID 9554), with no identity on file
tool.update(id="DTXSID8031865_scratch", kind="other", chemical_dtxsid="DTXSID8031865", chemical_dtxsid_from="id_prefix",
            last_changed="2026-10-01T10:00:00Z",
            notes=[{"level": "warn", "code": "not_a_chemical_id", "say": "Made by a tool; its id is not a chemical's DTXSID."},
                   {"level": "warn", "code": "identity_missing", "say": "No chemical identity is on file for this session."}])
tool["format"]["say"] = "This session's id is not a chemical's DTXSID, so it uses the format for new studies."
lst["chemicals"].append({"dtxsid": "DTXSID8031865", "name": None, "casrn": None, "primary": None, "can_create": True, "sessions": [tool]})
# the Bisphenol A row is what S2's create produces (contract §4.1 note): not in the store before
bpa = next(c for c in lst["chemicals"] if c["dtxsid"] == "DTXSID7020182")
lst["chemicals"].remove(bpa)
(M1 / "created.DTXSID7020182.json").write_text(json.dumps({"status": 201, "body": bpa["sessions"][0]}, indent=2, ensure_ascii=False) + "\n")
lst["chemicals"].sort(key=lambda c: max(r["last_changed"] for r in c["sessions"]), reverse=True)
(M1 / "studies.json").write_text(json.dumps({"status": 200, "body": lst}, indent=2, ensure_ascii=False) + "\n")

# 4. details
rows = {r["id"]: r for c in lst["chemicals"] for r in c["sessions"]} | {r["id"]: r for r in lst["unassigned"]}
nb = load(M1 / "detail.contract.DTXSID50469320_nb.json")
check = load(M1 / "creation-check.DTXSID50469320.json")
def pin_of(id):
    p = states.get(id, {}).get("pins", {}).get("definition")
    if not p or not p.get("pinned"):
        return {"mode": None, "pinned_at": None, "pinned_by": None}
    return {"mode": p["mode"], "pinned_at": p["pinned_at"], "pinned_by": p["pinned_by"]}
def banner(r):
    k, id = r["kind"], r["id"]
    if k == "companion":
        rep = r["published"]["report"]
        return {"level": "info", "say": f"This is the published book's own content ({rep}), built by a tool from the published book. It can't be changed or deleted here.",
                "links": [{"say": "Read it on the Bookshelf", "href": f"/Bookshelf/{id}"},
                          {"say": f"The generated study: {r['relations']['twin']}", "href": f"/app/studies/{r['relations']['twin']}"}]}
    if k == "member":
        p = r["relations"]["parent"]; sib = r["relations"]["others"][0]
        sp, osp = ("rat", "mouse") if id.endswith("_rat") else ("mouse", "rat")
        return {"level": "info", "say": f"This is the {sp} study of the report {p} (1,4-Dichlorobenzene, NIEHS-13), which also has a {osp} study. Its data is prepared here; its report is the parent's.",
                "links": [{"say": f"The report {p}", "href": f"/app/studies/{p}"}, {"say": f"The {osp} study {sib}", "href": f"/app/studies/{sib}"}]}
    if k == "report":
        return {"level": "info", "say": "A report over two studies. The data is prepared in each study; this report gathers them.", "links": []}
    if k == "other" and id == "DTXSID50469320_nb":
        return nb["detail"]["banner"]
    if k == "other":
        base = r["chemical_dtxsid"]
        say = (f"This session's id, {id}, is not a chemical's DTXSID: it was made by a tool. Its report uses the 2026 format."
               + (f" A study under {base} would be the chemical's own study." if base else ""))
        return {"level": "warning", "say": say, "links": [{"say": f"Create the study {base}", "href": f"/app/studies/new?dtxsid={base}"}] if base else []}
    return None
for id, r in rows.items():
    d = copy.deepcopy(r)
    brings = check["format"]["brings"] if id == "DTXSID50469320" else []
    if id == "DTXSID50469320_nb":
        fmt = dict(nb["detail"]["format"]); fmt["say"] = r["format"]["say"]
    else:
        fmt = dict(r["format"], brings=brings, pin=pin_of(id), chosen_by="id")
    d["detail"] = {"banner": banner(r), "format": fmt}
    if r["kind"] == "report":
        d["detail"]["members"] = [rows[m["id"]] for m in r["relations"]["members"]]
    (M1 / f"detail.{id}.json").write_text(json.dumps({"status": 200, "body": d}, indent=2, ensure_ascii=False) + "\n")
print(len(rows), "sessions;", len(lst["chemicals"]), "chemicals")
