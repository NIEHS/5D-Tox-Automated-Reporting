# ntp_bmds — NTP's modified BMDS python package, vendored

**Source.** The `bmds/` package inside the CEBS deposit `C20022-01_bmds.zip`
(NIEHS-10, PFHxSAm), sha256
`ad39aae2b039c2121f507afb8002afc98e03ff835298b9df28968a3c2d9a8f3f`. The same
zip, byte for byte, is deposited with NIEHS-02, 03, 04, 05 (named
`BMDs_code_package.docx`), 06, 07, 08 and 09.

It is the python `bmds` package 0.11.0 (Andy Shapiro, MIT licence,
<https://pypi.org/project/bmds/0.11.0/>) with NTP's modifications. Per the
deposit's ReadME, those are to the BMDS 2.7 recommendation rules: the two
rules that a BMD or BMDL may not be 10 times below the lowest nonzero dose
were removed, a rule that the BMD may not exceed the highest dose was added,
and one message text was corrected. NTP's recorded runs (the Parameter
workbooks) are reproduced by this code: `tests/unit/test_bmds27_oracle.py`.

The executables (`bin/BMDS270/*.exe`, EPA's BMDS 2.7) are not vendored; see
`pipeline/bmds27/binaries.py`.

**Not vendored.** `batch.py` (export helpers; needs `six`), `monkeypatch.py`
(NTP's remote-execution seam — replaced by `pipeline/bmds27/runner.py`),
`__pycache__/`, `bin/`.

**Patches** (everything else is byte-identical to the zip;
`tests/unit/test_bmds27_vendored.py` checks it when the zip is present):

1. `from simple_settings import settings` → the package's own `settings`
   module (`from . import settings` / `from .. import settings`) in
   `datasets.py`, `session.py`, `drunner.py`, `models/base.py`,
   `logic/recommender.py`. The values are the same module NTP's
   `SIMPLE_SETTINGS=bmds.settings` selected.
2. `__init__.py`: no `SIMPLE_SETTINGS` environment variable, and no imports of
   `drunner`, `batch`, `reporter`, `plotting` or `monkeypatch` (the remote
   execution monkeypatch must not apply).
3. `plotting.py`: matplotlib imported inside `create_empty_figure()` instead of
   at import time (plots are never drawn here; matplotlib is not a dependency).
4. `reporter.py`: `"\g<1>°"` → `r"\g<1>°"` (an invalid-escape warning on
   Python 3.12; the same string).
