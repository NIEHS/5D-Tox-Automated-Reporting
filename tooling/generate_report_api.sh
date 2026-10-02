#!/usr/bin/env bash
# tooling/generate_report_api.sh — generate a report end-to-end over the HTTP API.
#
# The curl twin of tooling/generate_report.py: it drives a RUNNING rlm-bmdx server
# (./run-server.sh) through the same calls the browser UI makes, in the same order:
#
#   upload → validate → confirm metadata → integrate → animal report
#     → process → materialize result sections → [background] → download
#
# Requires: curl, jq. Every step is one curl call; read the script top to bottom
# as a worked example of the API (docs/headless-report-generation.md explains each).
#
# Usage:
#   tooling/generate_report_api.sh -i DTXSID50469320 -n "Perfluorohexanesulfonamide" -c 41997-13-1 \
#       -u mg/kg [-k PFHxSAm] [-b] [-o output/DTXSID50469320] [-s docx,jats,pdf] FILE...
#
#   -i  session id (DTXSID…)              -n  test-article name     -c  CASRN
#   -u  dose unit (default mg/kg)          -k  short compound name for captions
#   -b  also generate the Background section (LLM + ATSDR/IRIS/PubChem lookups)
#   -s  deliverables: comma list of docx,html,jats,bookshelf,pdf (default docx,html)
#   -o  output dir (default output/<id>)
#   FILE…  input files to upload; omit to use the files already in the session
#
# Env: BASE (default http://localhost:9000); RLM_USER when the server sets
#      ALLOWED_USERS (appended as ?user=…).
set -euo pipefail

BASE="${BASE:-http://localhost:9000}"
ID="" NAME="" CASRN="" UNIT="" SHORT="" BG=false SURFACES="docx,html" OUT=""
while getopts "i:n:c:u:k:bs:o:h" opt; do
  case $opt in
    i) ID=$OPTARG ;; n) NAME=$OPTARG ;; c) CASRN=$OPTARG ;; u) UNIT=$OPTARG ;;
    k) SHORT=$OPTARG ;; b) BG=true ;; s) SURFACES=$OPTARG ;; o) OUT=$OPTARG ;;
    h|*) sed -n '2,26p' "$0"; exit 1 ;;
  esac
done
shift $((OPTIND - 1))
[[ -n "$ID" ]] || { echo "-i <DTXSID> is required" >&2; exit 1; }
OUT="${OUT:-output/$ID}"
mkdir -p "$OUT"
if [[ -z "$UNIT" ]]; then
  UNIT="mg/kg"; echo "NOTE: dose unit defaulted to 'mg/kg' — pass -u to state it"
fi

# Append ?user= for the ALLOWED_USERS gate (& when the path already has a query).
q() {
  if [[ -z "${RLM_USER:-}" ]]; then echo "$1"
  elif [[ "$1" == *\?* ]]; then echo "$1&user=$RLM_USER"
  else echo "$1?user=$RLM_USER"; fi
}

# POST JSON; fail loudly on a non-2xx with the server's {"error": …} body.
post() {  # post PATH [JSON]
  local body=${2:-'{}'} resp code
  resp=$(curl -sS -w '\n%{http_code}' -X POST -H 'Content-Type: application/json' \
         --data "$body" "$BASE$(q "$1")")
  code=${resp##*$'\n'}; resp=${resp%$'\n'*}
  if (( code >= 400 )); then echo "POST $1 → HTTP $code: $resp" >&2; exit 1; fi
  printf '%s' "$resp"
}

step() { echo "▶ $*"; }

# --- 1. Upload ------------------------------------------------------------
# .bm2 → /api/upload-bm2; everything else (.txt/.csv/.xlsx/.sidecar.json) →
# /api/upload-csv. Long-format NTP CSVs are converted to the wide pivot on upload.
if (( $# > 0 )); then
  step "upload $# file(s)"
  for f in "$@"; do
    case "$f" in *.bm2|*.BM2) ep=/api/upload-bm2 ;; *) ep=/api/upload-csv ;; esac
    curl -sSf -F "files=@\"$f\"" "$BASE$(q "$ep?dtxsid=$ID")" \
      | jq -r '.files[] | "  + \(.filename)"'
  done
fi

# --- 2. Validate ----------------------------------------------------------
step "validate"
post "/api/pool/validate/$ID" > "$OUT/validation_report.json"
jq -r '"  \(.file_count) files, \(.issues|length) issue(s)",
       (.issues[] | "    [\(.severity)] \(.issue_type // ""): \(.message // "")")' \
   "$OUT/validation_report.json"
if jq -e '[.issues[] | select(.severity == "error")] | length > 0' \
     "$OUT/validation_report.json" >/dev/null; then
  echo "validation found errors — see $OUT/validation_report.json" >&2; exit 1
fi

# --- 3. Confirm metadata --------------------------------------------------
# Review the detected (platform, data_type) per file. To override one, send
# {"metadata": {"<file_id>": {"platform": "…", "data_type": "…"}}} instead of {}.
step "confirm metadata"
curl -sSf "$BASE$(q "/api/wizard/$ID/fingerprints")" \
  | jq -r '.fingerprints[] | "    \(.filename)\t\(.platform)\t\(.data_type)"'
post "/api/pool/confirm-metadata/$ID" '{"metadata": {}}' >/dev/null

# --- 4. Integrate (Java) --------------------------------------------------
step "integrate"
identity=$(jq -nc --arg n "$NAME" --arg c "$CASRN" --arg d "$ID" \
  '{identity: {name: $n, casrn: $c, dtxsid: $d}}')
post "/api/pool/integrate/$ID" "$identity" \
  | jq -r '"  \(.experiment_count) experiments, \(.bmd_result_count) BMD results"'

# --- 5. Approve the data = generate the animal report ---------------------
step "animal report"
post "/api/generate-animal-report/$ID" \
  | jq -r '"  \(.total_animals) animals (core \(.core_count) / biosampling \(.biosampling_count))"'

# --- 6. Process (long: stats + BMDS + genomics + narratives) --------------
step "process (minutes when cold)"
params=$(jq -nc --arg k "${SHORT:-$NAME}" --arg u "$UNIT" \
  '{compound_name: $k, dose_unit: $u, bmd_stats: ["median"],
    go_pct: 5, go_min_genes: 20, go_max_genes: 500, go_min_bmd: 3}')
post "/api/process-integrated/$ID" "$params" > "$OUT/process_payload.json"
jq -r '"  \(.sections|length) apical, \(.genomics_sections|length) genomics section(s)"' \
   "$OUT/process_payload.json"

# --- 7. Materialize the apical result sections as section files -----------
step "materialize result sections"
post "/api/pool/materialize-sections/$ID" | jq -r '"  \(.materialized|length) section file(s)"'

# --- 8. Background (optional; LLM, streamed as Server-Sent Events) --------
if $BG; then
  step "background (LLM)"
  bg=$(curl -sSN -X POST -H 'Content-Type: application/json' \
        --data "$(jq -nc --arg n "$NAME" --arg c "$CASRN" --arg d "$ID" \
                  '{identity: {name: $n, casrn: $c, dtxsid: $d}}')" \
        "$BASE$(q /api/generate)" \
      | awk '/^event: /{ev=$2} /^data: /{if (ev=="complete"||ev=="error") {sub(/^data: /,""); print ev" "$0}}')
  case "$bg" in
    complete*)
      post /api/session/save-section "$(jq -c --arg d "$ID" \
        '{dtxsid: $d, section_type: "background",
          data: {paragraphs, references, citation_report, abstract_background}}' <<<"${bg#complete }")" >/dev/null
      echo "  $(jq '.paragraphs|length' <<<"${bg#complete }") paragraph(s) saved" ;;
    *) echo "  WARNING: background generation failed: ${bg#error }" >&2 ;;
  esac
fi

# --- 9. Render + download -------------------------------------------------
# Each materialize renders the deliverable (plus the HTML view) to
# sessions/<id>/preview/default/ and archives the prior set, so download each
# surface right after materializing it. Download is publish-gated (HTTP 409 when a
# reprocess left LLM sections needing re-acceptance).
step "render + download"
IFS=, read -ra want <<<"$SURFACES"
for s in "${want[@]}"; do
  case $s in
    docx|html|jats|bookshelf)
      post "/api/preview/$ID/materialize" "{\"surface\": \"$s\"}" >/dev/null
      ext=$s; [[ $s == jats ]] && ext=xml; [[ $s == bookshelf ]] && ext=bookshelf.html
      curl -sSf -o "$OUT/$ID.$ext" "$BASE$(q "/api/preview/$ID/download?surface=$s")"
      echo "  → $OUT/$ID.$ext" ;;
    pdf)  # the docx deliverable converted by LibreOffice on the server (ungated preview)
      curl -sSf -o "$OUT/$ID.pdf" "$BASE/Bookshelf/$ID/report.pdf"
      echo "  → $OUT/$ID.pdf" ;;
    *) echo "  unknown surface '$s' (latex: use python -m tooling.generate_report)" >&2 ;;
  esac
done
