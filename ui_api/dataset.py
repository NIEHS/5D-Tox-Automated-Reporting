"""
ui_api.dataset — a study's combined data: what it was built from, the act that
builds it, and every results table followed back to its files (the demo path's
"Combined data" page, docs/ui-redesign/modules/demo/spec.md §4 S1).

  study_dataset     before the files are combined: the files as the file check
                    recorded them and, per assay, the chain workbook →
                    converted table → BMDExpress project.  After: the dataset's
                    experiments, the file each assay's data was taken from,
                    whether the study's own benchmark dose analysis is in it,
                    and the animal accounting's summary.
  start_integrate   the act: combine the files, then account for the animals,
                    as one long act (ui_api.long_acts), in the order of
                    tooling/generate_report.py.
  result_tables     the report's results tables (the ``bm2_<slug>`` sections).
  table_sources     one table, row by row: endpoint → experiment → the file
                    the data was taken from → the workbook it was converted
                    from; and where its benchmark doses come from (the record
                    of ADR-0036).

The reads have no side effects (the read model's store), and take the dataset
only through the schema-checking loader (CONTEXT.md invariant 1: never the
study's raw files).  **Nothing is guessed.**  Every link of a chain is a
record read as written: the file check's coverage matrix, a converted table's
sidecar, the dataset's ``_meta.source_files``, an exact name.  Where a record
is missing the chain is returned as far as it goes, with ``stops`` saying
which link is not recorded.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Iterator

from ui_api.read_model import ReadOnlyDiskPoolStore
from ui_api.studies import StudyRefusal

logger = logging.getLogger(__name__)

RESULT_PREFIX = "bm2_"


# ---------------------------------------------------------------------------
# Small readers
# ---------------------------------------------------------------------------

def _session(dtxsid: str) -> Path:
    """The study's folder; refused when the id is malformed, there is no such
    study, or it is a report over several studies (its data is its studies')."""
    from common.dtxsid import validate_dtxsid
    from pipeline.session_store import session_path
    from ui_api.studies import members

    validate_dtxsid(dtxsid)
    session = session_path(dtxsid)
    if not session.is_dir():
        raise StudyRefusal("study_not_found", f"no session {dtxsid}", 404, {"id": dtxsid})
    listed = members(dtxsid)
    if listed:
        raise StudyRefusal(
            "report_has_no_data", f"{dtxsid} is a report over several studies "
            f"({', '.join(listed.values())}); its data is in those studies", 409,
            {"id": dtxsid, "members": list(listed.values())})
    return session


def _read(path: Path):
    """A session JSON document: None when absent, UnreadableSessionFile when
    damaged (never silently empty)."""
    from common.session_files import read_json_file
    return read_json_file(path)


def _fingerprints(session: Path) -> dict[str, dict]:
    """What the file check recorded of each file, by file name."""
    raw = _read(session / "_fingerprints.json")
    return {name: fp for name, fp in raw.items() if isinstance(fp, dict)} \
        if isinstance(raw, dict) else {}


def _converted_from(session: Path, filename: str, fp: dict) -> dict | None:
    """The workbook a converted table was made from, and which record says so:
    the table's sidecar (``files/<name>.sidecar.json``, key ``source``), else
    the file check's own note (``derived_from``).  None: not recorded."""
    sidecar = _read(session / "files" / f"{Path(filename).stem}.sidecar.json")
    if isinstance(sidecar, dict) and isinstance(sidecar.get("source"), str) and sidecar["source"]:
        return {"filename": sidecar["source"], "recorded_in": "sidecar"}
    if isinstance(fp.get("derived_from"), str) and fp["derived_from"]:
        return {"filename": fp["derived_from"], "recorded_in": "file_check"}
    return None


def _file_row(session: Path, filename: str, fp: dict) -> dict:
    return {
        "filename": filename,
        "file_type": fp.get("file_type"),
        "assay": fp.get("platform"),
        "data_type": fp.get("data_type"),
        "sexes": list(fp.get("sexes") or []),
        "animals": len(fp.get("animal_ids") or []),
        "dose_groups": list(fp.get("dose_groups") or []),
        "dose_unit": fp.get("dose_unit"),
        "converted_from": _converted_from(session, filename, fp),
    }


def _assays(session: Path, fps: dict[str, dict], source_files: dict | None) -> list[dict]:
    """Per assay, the chain the file check recorded (validation_report.json's
    coverage matrix): the workbook, the converted table(s), the BMDExpress
    project; and, once the files are combined, the file the dataset says the
    assay's data was taken from (``_meta.source_files``)."""
    report = _read(session / "validation_report.json")
    matrix = report.get("coverage_matrix") if isinstance(report, dict) else None
    if not isinstance(matrix, dict):
        return []
    name_of = {fp.get("file_id"): name for name, fp in fps.items()}

    def named(file_id) -> str | None:
        return name_of.get(file_id) if isinstance(file_id, str) else None

    out = []
    for key, slots in matrix.items():
        if not isinstance(slots, dict):
            continue
        tables = [n for n in (named(i) for i in slots.get("txt_csv") or []) if n]
        workbook, bm2 = named(slots.get("xlsx")), named(slots.get("bm2"))
        # The assay's name and kind of data, as the check recorded them on
        # the group's files (the first file that has them).
        group = [fps[n] for n in (workbook, *tables, bm2) if n]
        entry = {
            "key": key,
            "assay": next((fp["platform"] for fp in group if fp.get("platform")), None),
            "data_type": next((fp["data_type"] for fp in group if fp.get("data_type")), None),
            "workbook": workbook,
            "tables": [{"filename": n, "converted_from": _converted_from(session, n, fps[n])}
                       for n in tables],
            "bm2": bm2,
        }
        if source_files is not None:
            taken = source_files.get(key)
            entry["taken_from"] = ({"filename": taken.get("filename"), "kind": taken.get("tier")}
                                   if isinstance(taken, dict) and taken.get("filename") else None)
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# The dataset, read once per file (it is tens of megabytes)
# ---------------------------------------------------------------------------

_DIGEST_MEMO: dict[tuple, dict] = {}
_DIGEST_LOCK = threading.Lock()
_DIGEST_MEMO_MAX = 16


def _source_key(description: dict) -> str | None:
    """The key the dataset files an experiment's source under
    (``_meta.source_files``): ``<assay>|<kind of data>``, or the kind of data
    alone for gene expression."""
    data_type, platform = description.get("dataType"), description.get("platform")
    if data_type == "gene_expression":
        return "gene_expression"
    return f"{platform}|{data_type}" if platform and data_type else None


def _endpoint_names(experiment: dict) -> list[str]:
    names = []
    for response in experiment.get("probeResponses") or []:
        probe = response.get("probe") if isinstance(response, dict) else None
        if isinstance(probe, dict) and probe.get("id") is not None:
            names.append(str(probe["id"]))
    return names


def _digest(dtxsid: str, session: Path) -> dict | None:
    """What the pages need of the combined dataset: its experiments, the file
    each was taken from, and the study's own benchmark dose analyses.  None
    when the files are not combined.  Read through the schema-checking loader
    and kept per file identity (path, time, size), so a new integration is
    read afresh."""
    path = session / "integrated.json"
    if not path.is_file():
        return None
    st = path.stat()
    key = (str(path), st.st_mtime_ns, st.st_size)
    with _DIGEST_LOCK:
        if key in _DIGEST_MEMO:
            return _DIGEST_MEMO[key]

    integrated = ReadOnlyDiskPoolStore().get_integrated(dtxsid)
    if not isinstance(integrated, dict):
        return None
    meta = integrated.get("_meta") if isinstance(integrated.get("_meta"), dict) else {}
    source_files = meta.get("source_files") if isinstance(meta.get("source_files"), dict) else {}

    # The study's own benchmark dose analyses (bMDResult), by the experiment
    # each one names (a reference number, or the experiment itself).
    analysed_refs, analysed_names = set(), set()
    results = integrated.get("bMDResult") or []
    for result in results:
        of = result.get("doseResponseExperiment") if isinstance(result, dict) else None
        if isinstance(of, dict):
            analysed_names.add(of.get("name"))
        elif of is not None:
            analysed_refs.add(of)

    experiments = []
    for exp in integrated.get("doseResponseExperiments") or []:
        desc = exp.get("experimentDescription") or {}
        taken = source_files.get(_source_key(desc) or "")
        experiments.append({
            "name": exp.get("name"),
            "assay": desc.get("platform"),
            "data_type": desc.get("dataType"),
            "sex": desc.get("sex"),
            "organ": desc.get("organ") or None,
            "endpoints": len(exp.get("probeResponses") or []),
            # The apical endpoints by name (not the thousands of gene probes).
            "endpoint_names": (_endpoint_names(exp)
                               if desc.get("dataType") != "gene_expression" else None),
            # One treatment per animal (or per sample, for gene expression).
            "animals": len(exp.get("treatments") or []),
            "taken_from": ({"filename": taken.get("filename"), "kind": taken.get("tier")}
                           if isinstance(taken, dict) and taken.get("filename") else None),
            "own_benchmark_doses": (exp.get("@ref") in analysed_refs
                                    or exp.get("name") in analysed_names),
        })
    digest = {
        "integrated_at": meta.get("integrated_at"),
        "source_files": source_files,
        "experiments": experiments,
        "own_bmd_analyses": len(results),
    }
    with _DIGEST_LOCK:
        if len(_DIGEST_MEMO) >= _DIGEST_MEMO_MAX:
            _DIGEST_MEMO.clear()
        _DIGEST_MEMO[key] = digest
    return digest


def _accounting(session: Path) -> dict | None:
    """The animal accounting's summary (animal_report.json), as it records
    it; None when the animals have not been accounted for."""
    report = _read(session / "animal_report.json")
    if not isinstance(report, dict):
        return None
    return {
        "study_number": report.get("study_number"),
        "total_animals": report.get("total_animals"),
        "core_count": report.get("core_count"),
        "biosampling_count": report.get("biosampling_count"),
        "dose_groups": report.get("dose_groups") or [],
        # {dose: {sex: animals}}
        "dose_design": report.get("dose_design") or {},
        # {assay: {"xlsx": n, "txt_csv": n, "bm2": n}}: ids seen per kind of file
        "assay_coverage": report.get("domain_coverage") or {},
        "problems": list(report.get("consistency_issues") or []),
    }


# ---------------------------------------------------------------------------
# GET …/dataset
# ---------------------------------------------------------------------------

def study_dataset(dtxsid: str) -> dict:
    """The study's files and the dataset combined from them (see the module
    docstring).  ``integrated`` says which of the two the study has; the
    fields of the other are None."""
    session = _session(dtxsid)
    fps = _fingerprints(session)
    digest = _digest(dtxsid, session)
    out: dict = {
        "id": dtxsid,
        "files_checked": (session / "validation_report.json").is_file(),
        "files": [_file_row(session, name, fp) for name, fp in fps.items()],
        "assays": _assays(session, fps, digest["source_files"] if digest else None),
        "integrated": digest is not None,
        "integrated_at": None,
        "experiments": None,
        "own_bmd_analysis": None,
        "accounting": None,
    }
    if digest is None:
        return out
    experiments = [{k: v for k, v in exp.items() if k != "endpoint_names"}
                   for exp in digest["experiments"]]
    out.update(
        integrated_at=digest["integrated_at"],
        experiments=experiments,
        own_bmd_analysis={
            "analyses": digest["own_bmd_analyses"],
            "experiments": [e["name"] for e in experiments if e["own_benchmark_doses"]],
        },
        accounting=_accounting(session),
    )
    return out


# ---------------------------------------------------------------------------
# The results tables, followed back
# ---------------------------------------------------------------------------

def _result_sections(dtxsid: str, session: Path) -> list[tuple[str, dict]]:
    """The report's results sections with a file (``bm2_<slug>.json``), in the
    report's own order (the read model's sections: the document tree's)."""
    from ui_api.read_model import study_state

    out = []
    for section in study_state(dtxsid).get("sections") or []:
        key = section.get("key") or ""
        if not key.startswith(RESULT_PREFIX) or not section.get("has_file"):
            continue
        data = _read(session / f"{key}.json")
        if isinstance(data, dict):
            out.append((key, data))
    return out


def _has_bmd_columns(tables: dict) -> bool:
    return any("bmd" in row for rows in tables.values() if isinstance(rows, list)
               for row in rows if isinstance(row, dict))


def result_tables(dtxsid: str) -> dict:
    """The results tables of the study's report, one per results section and
    sex, for choosing one to follow back.  Empty until Process has run."""
    session = _session(dtxsid)
    tables = []
    for key, data in _result_sections(dtxsid, session):
        by_sex = data.get("tables_json") if isinstance(data.get("tables_json"), dict) else {}
        tables.append({
            "key": key,
            "title": data.get("title"),
            "assay": data.get("platform"),
            "caption": data.get("caption"),
            "sexes": list(by_sex),
            "rows": sum(len(rows) for rows in by_sex.values() if isinstance(rows, list)),
            "has_benchmark_doses": _has_bmd_columns(by_sex),
        })
    return {"id": dtxsid, "tables": tables}


def _bmd_setting(record: dict | None, assay: str, sex: str) -> dict | None:
    """The setting of the apical BMD method's record (tables.apical_bmds.
    apical_bmd_method, ADR-0036) that covers the assay and sex; None when the
    record does not cover them."""
    for setting in (record or {}).get("settings") or []:
        sexes = (setting.get("platforms") or {}).get(assay)
        if sexes is None:
            continue
        if not sexes or sex.title() in sexes:
            return {k: setting.get(k) for k in
                    ("source", "bmr", "constant_variance", "models", "analysis") if k in setting}
    return None


def table_sources(dtxsid: str, key: str) -> dict:
    """One results table followed back, per sex: its rows, the experiment(s)
    of its assay and sex in the dataset, the file their data was taken from,
    the workbook that file was converted from, and where its benchmark doses
    come from.  ``stops`` names the first link that is not recorded, or is
    None when the chain reaches a workbook (or a BMDExpress project, which is
    a source file itself)."""
    from pipeline.session_db import _latest_cache

    session = _session(dtxsid)
    data = _read(session / f"{key}.json") if key.startswith(RESULT_PREFIX) else None
    if not isinstance(data, dict):
        raise StudyRefusal("table_not_found", f"{dtxsid} has no results table {key}", 404,
                           {"id": dtxsid, "key": key})
    assay = data.get("platform")
    by_sex = data.get("tables_json") if isinstance(data.get("tables_json"), dict) else {}
    digest = _digest(dtxsid, session)
    fps = _fingerprints(session)

    # The record of how the apical benchmark doses were computed, as the last
    # Process built it (in the Methods context).
    methods = _latest_cache(session, "methods")
    context = methods.get("context") if isinstance(methods, dict) else None
    record = context.get("apical_bmd_method") if isinstance(context, dict) else None
    has_bmds = _has_bmd_columns(by_sex)

    sexes = []
    for sex, rows in by_sex.items():
        experiments = [e for e in (digest["experiments"] if digest else [])
                       if e["assay"] == assay and str(e["sex"] or "").lower() == str(sex).lower()]
        endpoint_names = {n for e in experiments for n in e.get("endpoint_names") or []}
        files = []
        for exp in experiments:
            taken = exp["taken_from"]
            if taken and taken["filename"] not in [f["filename"] for f in files]:
                fp = fps.get(taken["filename"])
                files.append({
                    **taken,
                    "file_type": fp.get("file_type") if fp else None,
                    "converted_from": (_converted_from(session, taken["filename"], fp)
                                       if fp else None),
                })

        if digest is None:
            stops = "dataset"
        elif not experiments:
            stops = "experiment"
        elif not files:
            stops = "file"
        elif any(f["file_type"] is None
                 or (f["file_type"] in ("txt", "csv") and not f["converted_from"])
                 for f in files):
            stops = "workbook"
        else:
            stops = None

        sexes.append({
            "sex": sex,
            "experiments": [{k: e[k] for k in ("name", "organ", "endpoints", "animals",
                                               "endpoint_names")}
                            for e in experiments],
            "files": files,
            "stops": stops,
            "benchmark_dose": (_bmd_setting(record, assay, sex) if has_bmds and assay else None),
            "rows": [{
                "label": row.get("label"),
                "heading": bool(row.get("is_heading")),
                "count_row": bool(row.get("is_n_row")),
                # An endpoint of exactly this name is in the experiment(s);
                # false: the link from the row to its endpoints is not recorded.
                "endpoint_in_dataset": (row.get("label") in endpoint_names
                                        if not row.get("is_heading") and not row.get("is_n_row")
                                        else None),
                "bmd": row.get("bmd"),
                "bmdl": row.get("bmdl"),
            } for row in rows if isinstance(row, dict)] if isinstance(rows, list) else [],
        })

    return {
        "id": dtxsid,
        "key": key,
        "title": data.get("title"),
        "assay": assay,
        "caption": data.get("caption"),
        "has_benchmark_doses": has_bmds,
        # False: the last Process left no record of the benchmark dose method.
        "benchmark_dose_recorded": isinstance(record, dict),
        "sexes": sexes,
    }


# ---------------------------------------------------------------------------
# POST …/integrate
# ---------------------------------------------------------------------------

def start_integrate(dtxsid: str) -> Iterator[str]:
    """Combine the study's files into one dataset, then account for its
    animals: one act, told as it goes (ui_api.long_acts).  Refused, before
    anything is run or answered: on the finished side of a demo pair, when
    the act is not legal in the study's phase (the safeguards), and while
    another long act runs on the study.

    The identity given to the integration is the study's own, as recorded
    (identity.json): the step writes back the identity it is given, so
    nothing else may be passed."""
    from safeguards import guarded
    from safeguards.acts import require
    from ui_api import long_acts
    from ui_api.demo import require_not_reference
    from workflow.phases import Action
    from workflow.store import DiskPoolStore

    session = _session(dtxsid)
    require_not_reference(dtxsid)
    store = DiskPoolStore()
    require(dtxsid, Action.INTEGRATE, store)
    identity = _read(session / "identity.json")
    identity = identity if isinstance(identity, dict) else None

    def work(report) -> dict:
        with long_acts.timed_step(report, "integrate", "Combining the files into one dataset"):
            combined = guarded.integrate_step(dtxsid, identity, store)
        with long_acts.timed_step(report, "accounting", "Accounting for every animal"):
            animals = guarded.generate_animal_report_step(dtxsid, store)
        return {
            "experiments": combined.get("experiment_count"),
            "own_bmd_analyses": combined.get("bmd_result_count"),
            "data_approval_withdrawn": bool(combined.get("approval_withdrawn")),
            "accounting_problems": len(animals.get("consistency_issues") or []),
        }

    return long_acts.start(dtxsid, "combining the files into one dataset", work,
                           path=f"/api/v2/studies/{dtxsid}/integrate")
