"""
pipeline/bmds27/runner.py — the executable step of NTP's BMDS package.

NTP's package runs a model by writing its BMDS input (the "dfile"), running
the BMDS 2.7 executable on it, and parsing the output file. Off Windows, its
own `monkeypatch.py` replaces only that step (it posted dfiles to a Windows
server). This module is the same seam: a session subclass whose `execute()`
hands each model's dfile to an executor and stores the result exactly as
NTP's code does. Everything else — models, dfiles, parsing, the rules, the
recommendation, high-dose dropping — is NTP's code, untouched.

Executors:
  WineExecutor    runs the real executables under Wine.
  ReplayExecutor  returns recorded outputs for recorded dfiles (the CEBS
                  Parameter workbooks) — conformance tests and certification.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Protocol

from pipeline.bmds27.ntp_bmds import settings as ntp_settings
from pipeline.bmds27.ntp_bmds.models.base import RunStatus
from pipeline.bmds27.ntp_bmds.models.continuous import Exponential
from pipeline.bmds27.ntp_bmds.session import BMDS_v270

TIMEOUT_SECONDS = ntp_settings.BMDS_MODEL_TIMEOUT_SECONDS
PARALLEL = int(os.environ.get("BMDS27_PARALLEL", "8"))
_DFILE = "bmds.(d)"


class Executor(Protocol):
    def run(self, exe: str, dfile: str, out_prefix: str) -> dict:
        """Run one model: {status: RunStatus, output: str|None, stdout, stderr}."""


def _out_prefix(model) -> str:
    # The exponential executable names its output after the sub-model run
    # (M2bmds.out …); NTP's Exponential.get_outfile / BatchDfileRunner rule.
    return model.output_prefix if isinstance(model, Exponential) else ""


class WineExecutor:
    """Run BMDS 2.7 executables under Wine, as NTP ran them on Windows."""

    def __init__(self, bin_dir: Path, wine: str | None = None):
        self.bin_dir = Path(bin_dir)
        self.wine = wine or shutil.which("wine")
        if not self.wine:
            raise FileNotFoundError("wine is not installed")

    @staticmethod
    def _env() -> dict:
        return {**os.environ, "WINEDEBUG": os.environ.get("WINEDEBUG", "-all"),
                "WINEDLLOVERRIDES": os.environ.get("WINEDLLOVERRIDES", "mscoree,mshtml=")}

    def run(self, exe: str, dfile: str, out_prefix: str) -> dict:
        with tempfile.TemporaryDirectory(prefix="bmds27-") as tmp:
            # Windows text mode wrote the dfile with CRLF line ends.
            with open(Path(tmp) / _DFILE, "w", newline="\r\n") as f:
                f.write(dfile)
            try:
                proc = subprocess.run(
                    [self.wine, str(self.bin_dir / f"{exe}.exe"), _DFILE],
                    cwd=tmp, env=self._env(), capture_output=True, timeout=TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                return {"status": RunStatus.FAILURE, "output": None, "stdout": "", "stderr": ""}
            outfile = Path(tmp) / f"{out_prefix}{Path(_DFILE).stem}.out"
            output = outfile.read_text(errors="replace") if outfile.is_file() else None
            return {"status": RunStatus.SUCCESS, "output": output,
                    "stdout": proc.stdout.decode(errors="replace").strip(),
                    "stderr": proc.stderr.decode(errors="replace").strip()}


class ReplayExecutor:
    """Recorded runs: dfile text → {outfile, stdout, stderr}. A dfile that was
    never recorded is a miss (counted), and the model is left as not run."""

    def __init__(self, recorded: dict[str, dict]):
        self.recorded = recorded
        self.hits = 0
        self.misses: list[str] = []

    def run(self, exe: str, dfile: str, out_prefix: str) -> dict:
        rec = self.recorded.get(dfile)
        if rec is None:
            self.misses.append(dfile)
            return {"status": RunStatus.DID_NOT_RUN}
        self.hits += 1
        if rec.get("execution_halted"):
            return {"status": RunStatus.FAILURE}
        return {"status": RunStatus.SUCCESS, "output": rec.get("outfile"),
                "stdout": rec.get("stdout") or "", "stderr": rec.get("stderr") or ""}


def _set_results(model, results: dict) -> None:
    # NTP monkeypatch.py's _set_results.
    status = results["status"]
    if status == RunStatus.SUCCESS:
        model._set_job_outputs(RunStatus.SUCCESS, output=results["output"],
                               stdout=results["stdout"], stderr=results["stderr"])
    elif status == RunStatus.FAILURE:
        model._set_job_outputs(RunStatus.FAILURE)
    else:
        model._set_job_outputs(RunStatus.DID_NOT_RUN)


def _execute(self) -> None:
    # NTP monkeypatch.py's execute_session, with the executor in place of the
    # remote Windows server.
    start = datetime.now()
    runnable = []
    for model in self.models:
        model.execution_start = start
        if model.can_be_executed:
            runnable.append(model)
        else:
            model._set_job_outputs(RunStatus.DID_NOT_RUN)
    if not runnable:
        return
    jobs = [(m.exe, m.as_dfile(), _out_prefix(m)) for m in runnable]
    with ThreadPoolExecutor(max_workers=max(1, min(PARALLEL, len(jobs)))) as pool:
        results = list(pool.map(lambda j: self.executor.run(*j), jobs))
    for model, res in zip(runnable, results):
        _set_results(model, res)


def session_class(executor: Executor) -> type:
    """NTP's BMDS 2.7 session with `executor` as its executable step. The
    executor is a class attribute so NTP's clone() (a deepcopy) shares it."""
    return type("BMDS270Session", (BMDS_v270,), {"executor": executor, "execute": _execute})
