"""
pipeline/bmds27 — the apical BMD engine of the BMDS-era NIEHS reports: NTP's
modified BMDS 2.7 package (vendored in ntp_bmds/) running EPA's BMDS 2.7
executables under Wine. See docs/adr/0030-bmds-2-7-engine-under-wine.md.

`available()` says whether this machine can run it, and why not: Wine on the
PATH, the NTP package's executables (binaries.py), and a self-certification —
recorded NTP runs (certification.json) re-run and parsed to the same values.
"""

from __future__ import annotations

import functools
import json
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

ENGINE = "bmds_2_7_high_dose_drop"
_CERTIFICATION = Path(__file__).with_name("certification.json")
# Parsed values a re-run must reproduce exactly.
_CERTIFIED_KEYS = ("BMD", "BMDL", "AIC", "p_value1", "p_value2", "p_value3", "p_value4")


def _exe_of(model_name: str) -> tuple[str, str, str]:
    """(executable, output prefix, NTP model_name) of a tabulated model name."""
    if model_name.startswith("Exponential-"):
        return "exponential", model_name.split("-")[1], model_name
    if model_name.startswith("Polynomial"):
        return "poly", "", "Polynomial"
    return {"Linear": ("poly", "", "Linear"), "Power": ("power", "", "Power"),
            "Hill": ("hill", "", "Hill")}[model_name]


def certify(executor) -> list[str]:
    """Re-run the recorded certification runs; the differences ([] = certified)."""
    from pipeline.bmds27.ntp_bmds import constants
    from pipeline.bmds27.ntp_bmds.parser import OutputParser

    problems = []
    for rec in json.loads(_CERTIFICATION.read_text()):
        exe, prefix, name = _exe_of(rec["model_name"])
        res = executor.run(exe, rec["dfile"], prefix)
        if not res.get("output"):
            problems.append(f"{rec['model_name']}: no output ({res.get('stderr') or res.get('status')})")
            continue
        want = OutputParser(rec["outfile"], constants.CONTINUOUS, name).output
        got = OutputParser(res["output"], constants.CONTINUOUS, name).output
        diff = [k for k in _CERTIFIED_KEYS if want.get(k) != got.get(k)]
        if diff:
            problems.append(f"{rec['model_name']}: " + ", ".join(
                f"{k} {got.get(k)} ≠ recorded {want.get(k)}" for k in diff))
    return problems


def _wine_executor():
    """(executor, description) for this machine's BMDS 2.7 under Wine — with
    Microsoft's msvcrt.dll when one is supplied (binaries.msvcrt_path).
    Raises BinariesUnavailable."""
    from pipeline.bmds27.binaries import bin_dir, msvcrt_path, with_msvcrt
    from pipeline.bmds27.runner import WineExecutor

    directory, msvcrt = bin_dir(), msvcrt_path()
    if msvcrt is None:
        return WineExecutor(directory), "Wine's msvcrt"
    return WineExecutor(with_msvcrt(directory, msvcrt), native_msvcrt=True), f"Microsoft's msvcrt ({msvcrt})"


@functools.lru_cache(maxsize=1)
def _status() -> tuple[bool, str]:
    from pipeline.bmds27.binaries import BinariesUnavailable

    if not shutil.which("wine"):
        return False, "Wine is not installed (BMDS 2.7 is 32-bit Windows software)"
    try:
        ex, runtime = _wine_executor()
    except BinariesUnavailable as e:
        return False, str(e)
    if ex.native_msvcrt:
        dfile = json.loads(_CERTIFICATION.read_text())[0]["dfile"]
        loaded = ex.msvcrt_loaded_as(dfile)
        if loaded != "native":
            return False, (f"{runtime} was supplied but Wine loaded msvcrt.dll as {loaded or 'unknown'}, "
                           "not native")
    problems = certify(ex)
    if problems:
        return False, (f"BMDS 2.7 under Wine with {runtime} does not reproduce NTP's recorded "
                       "runs: " + "; ".join(problems))
    logger.info("BMDS 2.7 certified under Wine with %s (%s)", runtime, ex.bin_dir)
    return True, f"certified with {runtime} ({ex.bin_dir})"


def available() -> bool:
    return _status()[0]


def unavailable_reason() -> str | None:
    ok, why = _status()
    return None if ok else why


def known_unavailable_reason() -> tuple[bool, str | None]:
    """(known, reason) without running anything: whether this process has
    already checked the machine (the check runs Wine and the certification
    runs, so a read that must have no side effects may not trigger it), and
    if so, why BMDS 2.7 cannot run here (None when it can)."""
    if _status.cache_info().currsize == 0:
        return False, None
    return True, unavailable_reason()


def executor():
    """The certified Wine executor. Raises RuntimeError when unavailable."""
    ok, why = _status()
    if not ok:
        raise RuntimeError(why)
    return _wine_executor()[0]
