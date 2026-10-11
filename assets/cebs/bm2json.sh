#!/bin/bash
# bm2json.sh <in.bm2> <out.json>  — deserialize a BMDExpress .bm2 to JSON via bmdx-pipe's ExportBm2
export JAVA_HOME=/opt/liberica-jdk-21 PATH=/opt/liberica-jdk-21/bin:$PATH BMDX_PROJECT_ROOT=/workspace/BMDExpress-3
cd /workspace/rlm-bmdx && .venv/bin/python -c "
import sys; from bmdx_pipe.apical_report import export_bm2; export_bm2(sys.argv[1], sys.argv[2], 'NONE')" "$1" "$2"
