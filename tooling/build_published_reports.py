"""tooling/build_published_reports.py — generate a report for every downloaded
published NIEHS study package (assets/cebs/<report>), into sessions/<DTXSID>/
and output/<DTXSID>/, so each one is on the Bookshelf shelf.

Each study goes through the normal headless path:

  1. tooling.cebs_to_pool converts the package's Individual Animal workbooks
     (and, for NIEHS-12, the Bookshelf bundle's concentration workbook) into
     pool inputs;
  2. the package's genomic BMDExpress project joins them — for NIEHS-07 … 10,
     whose project is shared by four chemicals, only this chemical's
     experiments (bmdx_pipe.subset_bm2);
  3. tooling.generate_report builds the session and renders it.

Every build starts from a fresh session: an existing sessions/<DTXSID> is
moved to output/_session_backups/<DTXSID>-pre-<time>-rebuild first (importing
the inputs again into a session that already pivoted them duplicates every
apical experiment).  A Background written earlier (on the host) is kept.

The design facts, strain designation and method profile below are stated from
the published report itself (its title and Materials and Methods), not
inferred: every study is five days of Sprague Dawley rats — and, in NIEHS-12
and 13, of B6D2F1/Crl mice; RR-8 and NIEHS-02 … 10 by gavage in corn oil,
NIEHS-12 and 13 by whole-body inhalation.
RR-8 and NIEHS-02 … 06 name their one genomic experiment by chemical and unit
("EDHP mg_kg") and record no tissue or sex for it anywhere in the package;
their reports state male rat liver, which is stated here as the experiment's
metadata (GENOMIC_STATED).  Their apical workbooks record doses in mmol/kg;
the converter maps them to the genomic project's mg/kg levels.
NIEHS-12 and 13 report a rat study and a mouse study (ADR-0029 §9): each study
is built as its own session (<DTXSID>_rat, <DTXSID>_mouse, MEMBERS) from its
study-number prefix, its genomic project and its design — with the genomic
experiments' tissue and species from the package (cebs_to_pool
--metadata-out) — and the report session lists them (generate_report
--studies) and renders from them.  No method profile describes the 2018 analyses
(RR-8, NIEHS-02 … 06); they use ntp-5day-2021, the nearest era, whose
deviations the run log lists.

Usage:
    python -m tooling.build_published_reports [REPORT ...] [--jobs N]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CEBS = REPO_ROOT / "assets" / "cebs"
BACKUPS = REPO_ROOT / "output" / "_session_backups"
# The published book's Bookshelf package: the book (its XML and figures) and the
# files deposited with it.  The deposit is the package less the book's own files.
BOOKSHELF = CEBS / "_bookshelf"
BOOK_OWN_FILES = ("*.nxml", "*.jpg", "*.png", "*.gif", "*.tif", "TOC.pdf", "license.txt",
                  "SOURCE.txt")

ORAL = {"species": "rat", "strain": "Sprague-Dawley", "articleRoute": "oral",
        "administrationMeans": "gavage", "articleVehicle": "corn oil", "studyDuration": "5d"}
INHALED = {"species": "rat", "strain": "Sprague-Dawley", "articleRoute": "inhaled",
           "studyDuration": "5d"}
HSD = "(Hsd:Sprague Dawley® SD®)"
HSD_EARLY = "(Hsd: Sprague Dawley SD)"   # RR-8 and NIEHS-02 print it this way
INHALED_MICE = {"species": "mouse", "strain": "B6D2F1", "articleRoute": "inhaled",
                "studyDuration": "5d"}
CRL = "/Crl"                             # "B6D2F1/Crl Mice"

# report: (DTXSID, name, CASRN, short name, genomic project, experiment token,
#          dose unit, design, designation, method profile, extra converter args)
STUDIES = {
    "RR-8": ("DTXSID1021952", "Triphenyl Phosphate", "115-86-6", "TPHP",
             "C11042_BMDExpressProjectFile.bm2", None, "mg/kg", ORAL, HSD_EARLY,
             "ntp-5day-2021", []),
    "NIEHS-02": ("DTXSID1025300", "2-Ethylhexyl Diphenyl Phosphate", "1241-94-7", "EHDP",
                 "BMDExpress_Project_File_(bm2_format).bm2", None, "mg/kg", ORAL, HSD_EARLY,
                 "ntp-5day-2021", []),
    "NIEHS-03": ("DTXSID6024701", "tert-Butylphenyl Diphenyl Phosphate", "56803-37-3", "BPDP",
                 "BMDExpress_Project_File_(bm2_format).bm2", None, "mg/kg", ORAL, HSD,
                 "ntp-5day-2021", []),
    "NIEHS-04": ("DTXSID3025465", "Isodecyl Diphenyl Phosphate", "29761-21-5", "IDDP",
                 "BMDExpress_Project_File_(bm2_format).bm2", None, "mg/kg", ORAL, HSD,
                 "ntp-5day-2021", []),
    "NIEHS-05": ("DTXSID4028880", "Isopropylated Phenyl Phosphate", "68937-41-7", "IPP",
                 "BMDExpress_Project_File_(bm2_format).bm2", None, "mg/kg", ORAL, HSD,
                 "ntp-5day-2021", []),
    "NIEHS-06": ("DTXSID4021391", "Tricresyl Phosphate", "1330-78-5", "TCP",
                 "BMDExpress_Project_File_(bm2_format).bm2", None, "mg/kg", ORAL, HSD,
                 "ntp-5day-2021", []),
    "NIEHS-07": ("DTXSID00190950", "6:1 Fluorotelomer Alcohol", "375-82-6", "6:1 FTOH",
                 "C20027-01_EPA_PFAS_Kidney_Overflow_plate_removed_S1500_Plus_Analysis_Traditional.bm2",
                 "_6-1 FTOH_", "mg/kg", ORAL, HSD, "ntp-5day-2021", []),
    "NIEHS-08": ("DTXSID2029905", "1,1,2,2-Tetrahydroperfluoro-1-dodecanol", "865-86-1",
                 "10:2 FTOH",
                 "C04051-01_EPA_PFAS_Kidney_Overflow_plate_removed_S1500_Plus_Analysis_Traditional.bm2",
                 "_10-2 FTOH_", "mg/kg", ORAL, HSD, "ntp-5day-2021", []),
    "NIEHS-09": ("DTXSID1022477", "2,3-Benzofluorene", "243-17-4", "2,3-BF",
                 "C20042-01_BMDExpress_Project_File_bm2_format.bm2", "_2,3-Benzofluorene_",
                 "mg/kg", ORAL, HSD, "ntp-5day-2021", []),
    "NIEHS-10": ("DTXSID50469320", "Perfluorohexanesulfonamide", "41997-13-1", "PFHxSAm",
                 "C20022-01_EPA_PFAS_Kidney_Overflow_plate_removed_S1500_Plus_Analysis_Traditional.bm2",
                 "_PFHxSAm_", "mg/kg", ORAL, HSD, "ntp-5day-2021", []),
    "NIEHS-12": ("DTXSID6020430", "1,2-Dichlorobenzene", "95-50-1", "1,2-DCB",
                 None, None, "ppm", None, None, "ntp-5day-2025",
                 ["--bundle", str(CEBS / "_bookshelf" / "NIEHS-12")]),
    "NIEHS-13": ("DTXSID1020431", "1,4-Dichlorobenzene", "106-46-7", "1,4-DCB",
                 None, None, "ppm", None, None, "ntp-5day-2025",
                 ["--bundle", str(CEBS / "_bookshelf" / "NIEHS-13")]),
}

# A report over several studies: report → [(study key, study-number prefix,
# genomic project, design, strain designation)], in the book's order.  The
# report's own row above holds what the studies share.
MEMBERS = {
    "NIEHS-12": [("rat", "108020006", "108020006_2D_Genomic_Rats.bm2", INHALED, HSD),
                 ("mouse", "108020007", "108020007_2D_Genomic_Mice.bm2", INHALED_MICE, CRL)],
    "NIEHS-13": [("rat", "108020004", "108020004_4D_Genomic_Rats.bm2", INHALED, HSD),
                 ("mouse", "108020005", "108020005_4D_Genomic_Mice.bm2", INHALED_MICE, CRL)],
}


# The genomic experiment's metadata the published report states and the
# package does not record ("… the liver taken for gene expression studies").
_MALE_LIVER = {"organ": "liver", "sex": "male"}
GENOMIC_STATED = {r: _MALE_LIVER for r in ("RR-8", "NIEHS-02", "NIEHS-03", "NIEHS-04",
                                           "NIEHS-05", "NIEHS-06")}


def _project_json(report: str) -> Path | None:
    """The package's genomic BMDExpress project as JSON (assets/cebs/<r>/_bm2json)."""
    found = sorted((CEBS / report / "_bm2json").glob("*.json"))
    return found[0] if found else None


def _fresh_session(dtxsid: str) -> None:
    session = REPO_ROOT / "sessions" / dtxsid
    if session.exists():
        BACKUPS.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%dT%H%M%S")
        backup = BACKUPS / f"{dtxsid}-pre-{stamp}-rebuild"
        shutil.move(str(session), str(backup))
        # The Background is about the chemical, not this data, and is written
        # on the host (--background): keep it across the rebuild.
        if (backup / "background.json").exists():
            session.mkdir(parents=True)
            shutil.copy2(backup / "background.json", session / "background.json")


def _member_project_json(report: str, bm2: str) -> Path | None:
    """A member study's genomic project as JSON: the converted copy
    (_bm2json) or the package's own."""
    stem = Path(bm2).stem
    for path in (CEBS / report / "_bm2json" / f"{stem}.json", CEBS / report / f"{stem}.json"):
        if path.exists():
            return path
    return None


def build(report: str) -> tuple[str, int, str]:
    if report in MEMBERS:
        return build_composed(report)
    (dtxsid, name, casrn, short, bm2, token, unit, design, designation,
     profile, convert_args) = STUDIES[report]
    out = REPO_ROOT / "output" / dtxsid
    out.mkdir(parents=True, exist_ok=True)
    log = out / "build.log"
    _fresh_session(dtxsid)
    work = Path(tempfile.mkdtemp(prefix=f"cebs_{report}_"))
    inputs = work / "inputs"
    py = sys.executable
    with open(log, "w") as fh:
        def run(cmd):
            fh.write("$ " + " ".join(cmd) + "\n"); fh.flush()
            return subprocess.run(cmd, cwd=REPO_ROOT, stdout=fh, stderr=subprocess.STDOUT).returncode

        project_json = _project_json(report)
        dose_args = ["--mg-per-kg-from", str(project_json)] if project_json else []
        rc = run([py, "-m", "tooling.cebs_to_pool", "--package", str(CEBS / report),
                  "--out", str(inputs), *dose_args, *convert_args])
        if rc:
            return report, rc, "convert failed"
        project = CEBS / report / bm2
        if token:
            from bmdx_pipe import subset_bm2
            subset = inputs / f"{dtxsid}_genomic.bm2"
            subset_bm2(str(project), str(subset), token)
            fh.write(f"subset {project.name} to experiments containing {token!r}\n")
        else:
            subset = inputs / project.name
            subset.write_bytes(project.read_bytes())
        (work / "design.json").write_text(json.dumps(design))
        (work / "front_matter.json").write_text(json.dumps({"strain_designation": designation}))
        stated = []
        if report in GENOMIC_STATED and project_json:
            names = [e["name"] for e in json.load(open(project_json)).get("doseResponseExperiments") or []]
            (work / "experiment_metadata.json").write_text(
                json.dumps({n: GENOMIC_STATED[report] for n in names}))
            stated = ["--experiment-metadata", str(work / "experiment_metadata.json")]
        files = sorted(str(p) for p in inputs.iterdir())
        rc = run([py, "-m", "tooling.generate_report", dtxsid, "--files", *files,
                  "--name", name, "--casrn", casrn, "--compound-name", short,
                  "--dose-unit", unit, "--design", str(work / "design.json"),
                  "--front-matter", str(work / "front_matter.json"),
                  "--method-profile", profile, *stated, "--reintegrate",
                  # The data deposit: the Bookshelf package's files, less the
                  # book's own (its XML, figures, TOC.pdf, NCBI's license/source).
                  "--deposit", str(BOOKSHELF / report),
                  "--deposit-exclude", *BOOK_OWN_FILES,
                  "--surfaces", "docx,html,jats,bits,pdf", "--out", str(out)])
    return report, rc, str(log)


def build_composed(report: str) -> tuple[str, int, str]:
    """A report over several studies: each member study through the pipeline
    in its own session, then the report session listing them, rendered."""
    (dtxsid, name, casrn, short, _, _, unit, _, _, profile, convert_args) = STUDIES[report]
    out = REPO_ROOT / "output" / dtxsid
    out.mkdir(parents=True, exist_ok=True)
    log = out / "build.log"
    py = sys.executable
    members = []
    with open(log, "w") as fh:
        def run(cmd):
            fh.write("$ " + " ".join(cmd) + "\n"); fh.flush()
            return subprocess.run(cmd, cwd=REPO_ROOT, stdout=fh, stderr=subprocess.STDOUT).returncode

        for key, prefix, bm2, design, designation in MEMBERS[report]:
            member = f"{dtxsid}_{key}"
            _fresh_session(member)
            work = Path(tempfile.mkdtemp(prefix=f"cebs_{report}_{key}_"))
            inputs = work / "inputs"
            project_json = _member_project_json(report, bm2)
            meta_args = (["--mg-per-kg-from", str(project_json),
                          "--genomic-bm2-json", str(project_json),
                          "--metadata-out", str(work / "experiment_metadata.json")]
                         if project_json else [])
            rc = run([py, "-m", "tooling.cebs_to_pool", "--package", str(CEBS / report),
                      "--prefix", prefix, "--out", str(inputs), *meta_args, *convert_args])
            if rc:
                return report, rc, f"convert {key} failed"
            project = CEBS / report / bm2
            (inputs / project.name).write_bytes(project.read_bytes())
            (work / "design.json").write_text(json.dumps(design))
            (work / "front_matter.json").write_text(json.dumps({"strain_designation": designation}))
            stated = (["--experiment-metadata", str(work / "experiment_metadata.json")]
                      if (work / "experiment_metadata.json").exists() else [])
            files = sorted(str(p) for p in inputs.iterdir())
            rc = run([py, "-m", "tooling.generate_report", member, "--files", *files,
                      "--name", name, "--casrn", casrn, "--compound-name", short,
                      "--dose-unit", unit, "--design", str(work / "design.json"),
                      "--front-matter", str(work / "front_matter.json"),
                      "--method-profile", profile, *stated, "--reintegrate",
                      "--stop-after", "process"])
            if rc:
                return report, rc, f"study {key} failed ({log})"
            members.append(f"{key}={member}")

        _fresh_session(dtxsid)
        rc = run([py, "-m", "tooling.generate_report", dtxsid, "--studies", *members,
                  "--name", name, "--casrn", casrn,
                  "--deposit", str(BOOKSHELF / report), "--deposit-exclude", *BOOK_OWN_FILES,
                  "--surfaces", "docx,html,jats,bits,pdf", "--out", str(out)])
    return report, rc, str(log)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("reports", nargs="*", help=f"default: all of {list(STUDIES)}")
    ap.add_argument("--jobs", type=int, default=1)
    a = ap.parse_args(argv)
    reports = a.reports or list(STUDIES)
    unknown = [r for r in reports if r not in STUDIES]
    if unknown:
        raise SystemExit(f"unknown report(s) {unknown}")
    os.chdir(REPO_ROOT)
    sys.path.insert(0, str(REPO_ROOT))
    failed = 0
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        for report, rc, where in pool.map(build, reports):
            print(f"{report:9} {STUDIES[report][0]:16} {'ok' if rc == 0 else f'FAILED rc={rc}'}  {where}",
                  flush=True)
            failed += rc != 0
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
