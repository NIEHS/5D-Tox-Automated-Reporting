"""
java_bridge.py — Shared Java classpath and path constants for the bmdx-core bridge.

All Python modules that invoke Java helpers (ExportBm2, ExportGenomics,
ExportCategories, IntegrateProject, RunPrefilter) import their classpath
and directory constants from here.  This eliminates the duplication that
previously existed across apical_report.py, apical_stats.py, and
pool_integrator.py.

The classpath includes:
  - bmdx-core.jar: headless BMDExpress 3 library (data model, CLI, metadata)
  - target/deps/*.jar: Maven-resolved dependencies (Jackson, commons-math3,
    sciome-commons-math for Williams/Dunnett, jdistlib, etc.)
  - java/: directory containing our pre-compiled helper .class files

Environment:
  Set BMDX_PROJECT_ROOT to override the default BMDExpress 3 location.
  Default: ~/Dev/Projects/BMDExpress-3
"""

import os
from pathlib import Path


# ---------------------------------------------------------------------------
# BMDExpress 3 project paths
# ---------------------------------------------------------------------------

# BMDExpress 3 project root — override with BMDX_PROJECT_ROOT env var
# if the project lives somewhere other than the default location.
BMDX_PROJECT = Path(os.environ.get(
    "BMDX_PROJECT_ROOT",
    Path.home() / "Dev" / "Projects" / "BMDExpress-3",
))

# The bmdx-core library JAR — contains all BMDExpress model classes,
# CLI commands (combine, export, query), and utilities.
BMDX_CORE_JAR = BMDX_PROJECT / "target" / "bmdx-core.jar"

# Maven-resolved dependency JARs — downloaded by `mvn dependency:copy-dependencies`
# into target/deps/ on the bmdx-core branch.  Includes Jackson, commons-math3,
# commons-cli, SLF4J, Guava, Easy Rules, sciome-commons-math, etc.
BMDX_DEPS_DIR = BMDX_PROJECT / "target" / "deps"

# Path to the directory containing our pre-compiled Java helper .class files
# (ExportBm2, ExportGenomics, ExportCategories, IntegrateProject, RunPrefilter).
JAVA_HELPER_DIR = Path(__file__).parent / "java"


# ---------------------------------------------------------------------------
# Classpath assembly
# ---------------------------------------------------------------------------

def build_classpath() -> str:
    """
    Assemble the Java classpath from bmdx-core.jar + its Maven-resolved deps.

    Includes sciome-commons-math (Williams/Dunnett), jdistlib, commons-math3,
    and Jackson for JSON I/O.  Also includes the java/ helper directory where
    our pre-compiled .class files live.

    Returns:
        Colon-separated classpath string suitable for java -cp.
    """
    jars = [str(BMDX_CORE_JAR)]

    # Add all dependency JARs from target/deps/
    if BMDX_DEPS_DIR.exists():
        for jar in BMDX_DEPS_DIR.glob("*.jar"):
            jars.append(str(jar))

    # Add our helper .class directory
    jars.append(str(JAVA_HELPER_DIR))

    return ":".join(jars)
