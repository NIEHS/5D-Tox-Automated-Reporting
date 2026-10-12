"""
pipeline/bmds27/binaries.py — EPA's BMDS 2.7 continuous-model executables.

NTP's BMDS package (CEBS `<study>_bmds.zip` / `BMDs_code_package.zip`, the same
zip in every BMDS-era report, NIEHS-02 … NIEHS-10) ships EPA's BMDS 2.7
32-bit Windows executables. They are not committed. They are found at
`BMDS27_BIN` (the deploy image) or extracted from a CEBS package zip in
`assets/cebs/` into the user cache. Every file is checked against the hashes
below: a different binary is unavailable, never run.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

# The NTP package zip (identical in NIEHS-02 … NIEHS-10; NIEHS-05's is named .docx).
PACKAGE_SHA256 = "ad39aae2b039c2121f507afb8002afc98e03ff835298b9df28968a3c2d9a8f3f"
_ZIP_DIR = "bmds/bin/BMDS270/"

# The continuous models' executables and the runtime DLLs they load.
FILES = {
    "poly.exe": "9fbf04245928263b78a90495c85453d8b7b7acbe8a63f04fe50cd55a5678e1f2",
    "power.exe": "d20f023a0d3f71c67a6dcc060bace2cc3c3aeff55d20f787154d8dbf83d5ff2c",
    "hill.exe": "24de61fa0b71ecfb18b5a6b9cf640cd5b0f205e3199de409b972abf6ba5c95f2",
    "exponential.exe": "1ac01c72005fd5f4350e1795674481ddef68fd3bff870cf2994497e33ad97a6d",
    "libgcc_s_dw2-1.dll": "e5993ae764d5f179af3e5b90f4cf9645b0f0b6794616e23242b4b387560f33e2",
    "libgfortran-3.dll": "251a76ea5ebb50b639e3fa4d9f1250893bc4df2d811bfe2ccb8239a8f8993f77",
    "libquadmath-0.dll": "a9b81f1fc73cc3a71b14250526af0a8f5f8076768e03d200020e5a877655d252",
}

REPO_ROOT = Path(__file__).resolve().parents[2]
CEBS_DIR = REPO_ROOT / "assets" / "cebs"


class BinariesUnavailable(RuntimeError):
    """The BMDS 2.7 executables cannot be found or are not the expected ones."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cache_dir() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "rlm-bmdx" / "bmds270"


def verify(directory: Path) -> list[str]:
    """The problems with `directory` as a BMDS 2.7 bin directory ([] = good)."""
    problems = []
    for name, digest in FILES.items():
        p = directory / name
        if not p.is_file():
            problems.append(f"{name} missing")
        elif _sha256(p) != digest:
            problems.append(f"{name} is not the NTP package's binary (sha256 differs)")
    return problems


def package_zips(cebs_dir: Path = CEBS_DIR) -> list[Path]:
    """The CEBS BMDS package zips present (by name; the hash is checked on use)."""
    if not cebs_dir.is_dir():
        return []
    names = ("*_bmds.zip", "BMDs_code_package.zip", "BMDs_code_package.docx")
    return sorted(p for pat in names for p in cebs_dir.glob(f"*/{pat}"))


def extract(zip_path: Path, dest: Path) -> None:
    """Extract the continuous executables and DLLs from an NTP package zip."""
    if _sha256(zip_path) != PACKAGE_SHA256:
        raise BinariesUnavailable(f"{zip_path} is not the NTP BMDS package (sha256 differs)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".bmds270-", dir=dest.parent))
    try:
        with zipfile.ZipFile(zip_path) as z:
            for name in FILES:
                with z.open(_ZIP_DIR + name) as src, open(tmp / name, "wb") as out:
                    shutil.copyfileobj(src, out)
        problems = verify(tmp)
        if problems:
            raise BinariesUnavailable("; ".join(problems))
        if dest.exists():
            shutil.rmtree(dest)
        tmp.rename(dest)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)


def bin_dir() -> Path:
    """The verified BMDS 2.7 bin directory, extracting it on first use.
    Raises BinariesUnavailable with the reason."""
    env = os.environ.get("BMDS27_BIN")
    if env:
        problems = verify(Path(env))
        if problems:
            raise BinariesUnavailable(f"BMDS27_BIN={env}: " + "; ".join(problems))
        return Path(env)
    cached = cache_dir()
    if cached.is_dir() and not verify(cached):
        return cached
    zips = package_zips()
    if not zips:
        raise BinariesUnavailable(
            "no BMDS 2.7 executables: set BMDS27_BIN, or put a CEBS BMDS package zip "
            f"(e.g. NIEHS-10/C20022-01_bmds.zip) under {CEBS_DIR}")
    extract(zips[0], cached)
    return cached
