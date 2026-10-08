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
inferred: every study is Sprague Dawley rats for five days; RR-8 and
NIEHS-02 … 10 by gavage in corn oil, NIEHS-12 by whole-body inhalation.
RR-8 and NIEHS-02 … 06 name their one genomic experiment by chemical and unit
("EDHP mg_kg") and record no tissue or sex for it anywhere in the package;
their reports state male rat liver, which is stated here as the experiment's
metadata (GENOMIC_STATED).  Their apical workbooks record doses in mmol/kg;
the converter maps them to the genomic project's mg/kg levels.
NIEHS-12 also has a mouse study; only its rat study is built (one species per
report — gap analysis G8).  No method profile describes the 2018 analyses
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

ORAL = {"species": "rat", "strain": "Sprague-Dawley", "articleRoute": "oral",
        "administrationMeans": "gavage", "articleVehicle": "corn oil", "studyDuration": "5d"}
INHALED = {"species": "rat", "strain": "Sprague-Dawley", "articleRoute": "inhaled",
           "studyDuration": "5d"}
HSD = "(Hsd:Sprague Dawley® SD®)"
HSD_EARLY = "(Hsd: Sprague Dawley SD)"   # RR-8 and NIEHS-02 print it this way

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
                 "108020006_2D_Genomic_Rats.bm2", None, "ppm", INHALED, HSD, "ntp-5day-2025",
                 ["--prefix", "108020006", "--bundle", str(CEBS / "_bookshelf" / "NIEHS-12")]),
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


def build(report: str) -> tuple[str, int, str]:
    (dtxsid, name, casrn, short, bm2, token, unit, design, designation,
     profile, convert_args) = STUDIES[report]
    out = REPO_ROOT / "output" / dtxsid
    out.mkdir(parents=True, exist_ok=True)
    log = out / "build.log"
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
                  "--surfaces", "docx,html,jats,pdf", "--out", str(out)])
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
