"""The vendored NTP BMDS package is the CEBS deposit's code, but for the
patches PROVENANCE.md lists. Needs the (gitignored) CEBS package zip."""

import zipfile
from pathlib import Path

import pytest

from pipeline.bmds27 import binaries

VENDORED = Path(binaries.__file__).with_name("ntp_bmds")
ZIPS = [z for z in binaries.package_zips() if z.suffix == ".zip"]

pytestmark = pytest.mark.skipif(not ZIPS, reason="no CEBS BMDS package zip in assets/cebs")

_SETTINGS = ("from simple_settings import settings", {
    "datasets.py": "from . import settings", "session.py": "from . import settings",
    "drunner.py": "from . import settings", "models/base.py": "from .. import settings",
    "logic/recommender.py": "from .. import settings"})


def _patched(name: str, text: str) -> str:
    if name in _SETTINGS[1]:
        text = text.replace(_SETTINGS[0], _SETTINGS[1][name])
    if name == "__init__.py":
        text = text.replace('import os  # noqa\n\nos.environ.setdefault("SIMPLE_SETTINGS", "bmds.settings")\n\n', "")
        for line in ("from .drunner import *  # noqa\n", "from .batch import SessionBatch  # noqa\n",
                     "from .reporter import Reporter, ReporterStyleGuide  # noqa\n",
                     "from .plotting import *  # noqa\n", "\nfrom .monkeypatch import *  # noqa\n"):
            text = text.replace(line, "")
    if name == "plotting.py":
        text = text.replace('import matplotlib as mpl\n\nmpl.use("Agg")  # prevent matplotlib framework issues\n'
                            'import matplotlib.pyplot as plt  # noqa\n\n', "")
        text = text.replace("def create_empty_figure():\n    plt.style.use",
                            'def create_empty_figure():\n    import matplotlib as mpl\n\n'
                            '    mpl.use("Agg")  # prevent matplotlib framework issues\n'
                            "    import matplotlib.pyplot as plt  # noqa\n\n    plt.style.use")
    if name == "reporter.py":
        text = text.replace('"\\g<1>°"', 'r"\\g<1>°"')
    return text


def test_vendored_files_are_the_deposit_but_for_the_listed_patches():
    with zipfile.ZipFile(ZIPS[0]) as z:
        for path in sorted(VENDORED.rglob("*.py")):
            name = path.relative_to(VENDORED).as_posix()
            original = z.read(f"bmds/{name}").decode("utf-8")
            ours = path.read_bytes().decode("utf-8")
            assert ours == _patched(name, original), name


def test_nothing_vendored_that_the_deposit_lacks():
    with zipfile.ZipFile(ZIPS[0]) as z:
        names = set(z.namelist())
    for path in VENDORED.rglob("*.py"):
        assert f"bmds/{path.relative_to(VENDORED).as_posix()}" in names
