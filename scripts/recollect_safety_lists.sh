#!/usr/bin/env bash
# Re-collect the SFDA drug-safety lists end to end, politely, then load and link them.
#
#   bash scripts/recollect_safety_lists.sh            # run id lists-1 (resumes what exists)
#   RUN_ID=lists-2 bash scripts/recollect_safety_lists.sh
#   SKIP_LISTS=1 bash scripts/recollect_safety_lists.sh   # lists already crawled: start at details
#
# Steps: list pages -> detail pages -> linked documents -> PDF text -> OCR of scanned PDFs
# (Windows) -> load into the catalog and link to products -> knowledge chunks -> their vectors
# -> a database snapshot in data/db (commit data/ afterwards so every machine has it).
# Each step is resumable; a list that stays partial keeps a recorded gap (see its manifest).
# Exit code 3 from a crawl means the site blocked us: the script stops and never works around it.
set -u
cd "$(dirname "$0")/.."

RUN_ID="${RUN_ID:-lists-1}"
LISTS="${LISTS:-safety-alert,drugs-circulars,safety-labeling,rmm,drug-shortage,drug-shortage-resolved,dhpc}"
LOG="data/lists/recollect-${RUN_ID}.log"
CLI=(uv run python -X utf8 -m pharmavique.bootstrap.cli)
mkdir -p data/lists

step() {
    echo "$(date '+%F %T') START $*" | tee -a "$LOG"
    "${CLI[@]}" "$@" >>"$LOG" 2>&1
    local code=$?
    echo "$(date '+%F %T') END $1 exit=$code" | tee -a "$LOG"
    if [ "$code" -eq 3 ]; then
        echo "blocked by the site: stopping" | tee -a "$LOG"
        exit 3
    fi
}

if [ "${SKIP_LISTS:-0}" != "1" ]; then
    step sfda-lists --run-id "$RUN_ID" --lists "$LISTS"
fi
step sfda-list-details --run-id "$RUN_ID" --list-run-id "$RUN_ID" --lists "$LISTS"
step sfda-list-files --run-id "$RUN_ID" --list-run-id "$RUN_ID" --lists "$LISTS"
step sfda-list-texts --list-run-id "$RUN_ID" --lists "$LISTS"
step sfda-list-ocr --list-run-id "$RUN_ID" --lists "$LISTS"
step sfda-lists-load --run-id "$RUN_ID" --lists "$LISTS"
step knowledge-build --run-id "$RUN_ID"
step knowledge-embed
bash scripts/db_snapshot.sh >>"$LOG" 2>&1 && echo "$(date '+%F %T') snapshot written to data/db" | tee -a "$LOG"
echo "$(date '+%F %T') ALL DONE" | tee -a "$LOG"
