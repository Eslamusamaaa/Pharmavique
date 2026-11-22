#!/usr/bin/env bash
# The daily refresh on Linux (GitHub Actions, or cron): the same steps and safeguards as
# scripts/daily_refresh.ps1, for the drug registry and the fast SFDA lists. It writes to whatever
# PHARMAVIQUE_DATABASE_URL points at (Neon in production).
#
#   bash scripts/daily_refresh.sh                       # drugs and lists
#   STEPS=lists FAST_LISTS=drug-shortage bash scripts/daily_refresh.sh   # a short trial
#
# Every step is polite (one request at a time per site, robots.txt, stops on a block) and safe to
# repeat. A failing step is logged and the next step still runs; the exit code is 1 if any step
# failed. Logs and a summary: data/refresh/<date>/. What could not be checked is in
# data/refresh/ATTENTION.md. Not part of this script: the pictures (they need a place to be kept) and
# the OCR of scanned PDFs (it uses the Windows OCR, so scanned documents are added without text).
set -uo pipefail
cd "$(dirname "$0")/.."

STEPS="${STEPS:-drugs,lists}"
RECHECK="${RECHECK:-300}"
BASELINE="${BASELINE:-full-20261116}"
FAST_LISTS="${FAST_LISTS:-drug-shortage,drug-shortage-resolved,safety-alert,safety-labeling,drugs-circulars,dhpc,rmm,drug-approvals}"
KNOWLEDGE_LISTS="dhpc safety-alert drugs-circulars rmm safety-labeling"
stamp="$(date -u +%Y%m%d)"
logs="data/refresh/$stamp"
mkdir -p "$logs" "data/sfda"
summary="$logs/summary.md"
printf '# Daily refresh %s\n\n| step | result | time |\n|---|---|---|\n' "$stamp" > "$summary"
failed=0
LAST_CODE=0

has_step() { case ",$STEPS," in *",$1,"*) return 0 ;; *) return 1 ;; esac; }
cli() { uv run --no-sync python -X utf8 -m pharmavique.bootstrap.cli "$@"; }

# step <name> <exit codes that are not failures, comma separated> <cli arguments...>
step() {
  local name="$1" ok="$2"
  shift 2
  local started code minutes
  started="$(date +%s)"
  cli "$@" > "$logs/$name.log" 2>&1
  code=$?
  minutes="$(( ($(date +%s) - started) / 60 ))"
  echo "| $name | exit $code | $minutes min |" >> "$summary"
  case ",$ok," in *",$code,"*) ;; *) failed=$((failed + 1)) ;; esac
  LAST_CODE=$code
}

rows() { [ -f "$1" ] && wc -l < "$1" | tr -d ' ' || echo 0; }

# ---------------------------------------------------------------------------- the drug registry
if has_step drugs; then
  run="update-$stamp"
  update=(sfda-update --recheck "$RECHECK" --run-id "$run")
  baseline_id=""
  if [ -f data/sfda/latest.json ]; then
    baseline_id="$(python3 -c "import json; print(json.load(open('data/sfda/latest.json'))['run_id'])")"
  else
    # a clean checkout has no earlier run: the committed full crawl is the baseline
    baseline_id="$BASELINE"
    update+=(--baseline "$baseline_id")
  fi
  step drugs-update 0 "${update[@]}"
  code=$LAST_CODE
  # Exit 3 after a lost connection is not a block by the site: wait and resume the same run. A block
  # (401, 403, 429) or a robots.txt refusal is never retried.
  attempt=0
  while [ "$code" -eq 3 ] && [ "$attempt" -lt 3 ]; do
    last_log="$logs/drugs-update.log"
    [ "$attempt" -gt 0 ] && last_log="$logs/drugs-update-retry$attempt.log"
    grep -Eq "ERR_NAME_NOT_RESOLVED|ERR_INTERNET_DISCONNECTED|ERR_NETWORK_CHANGED|ERR_CONNECTION_(RESET|REFUSED|TIMED_OUT)|ERR_TIMED_OUT" "$last_log" || break
    attempt=$((attempt + 1))
    sleep 600
    step "drugs-update-retry$attempt" 0 "${update[@]}"
    code=$LAST_CODE
  done
  if [ "$code" -eq 0 ] && [ "$attempt" -gt 0 ]; then failed=$((failed - attempt)); fi  # recovered

  {
    echo "# Needs attention $stamp"; echo
    echo "drugs-update exit code: $code"
    if [ -f "data/sfda/$run/manifest.json" ]; then
      python3 - "data/sfda/$run/manifest.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1], encoding="utf-8"))
print("run status:", m.get("status"))
print("drug detail pages that could not be fetched:", len(m.get("failures") or {}))
print("list gap (drugs the pager promised but no pass returned):", (m.get("list_completeness") or {}).get("gap", "unknown"))
if m.get("failures"):
    print("  those drugs keep their OLD details and old fetched_at; they are retried at the next run")
PY
    fi
    case "$code" in
      0) echo "Everything was read; nothing is outstanding." ;;
      2) echo "PARTIAL: the changes that were read were loaded; the drugs listed above were not checked today." ;;
      *) echo "NOTHING was loaded today: the database still holds the previous data. Resume with --run-id $run." ;;
    esac
  } > "$logs/attention.md"
  cp "$logs/attention.md" data/refresh/ATTENTION.md

  if [ "$code" -eq 0 ] || [ "$code" -eq 2 ]; then
    step drugs-load 0 sfda-load --run-id "$run" --from-records
    # a drug missing from two complete runs in a row is withdrawn (never after a partial run, never
    # more than 50 at once; exit 2 means a safeguard held and nothing was withdrawn)
    if [ "$baseline_id" != "$run" ]; then
      step drugs-withdraw 0,2 sfda-withdraw-absent --run-id "$run" --baseline "$baseline_id"
    fi
    step search-reindex 0 search-reindex
    step alerts-relay 0 outbox-relay --once
    step alerts-email 0,4 notify-emails        # 4: not configured, nothing to send
    step analytics-rebuild 0 analytics-rebuild
    step cache-invalidate 0,4 cache-invalidate # 4: no shared cache in this deployment
  fi
fi

# ---------------------------------------------------------------------------- the fast lists
if has_step lists; then
  run="lists-$stamp"
  step lists-crawl 0,2 sfda-lists --lists "$FAST_LISTS" --run-id "$run"
  if [ "$LAST_CODE" -eq 0 ] || [ "$LAST_CODE" -eq 2 ]; then
    # load only the lists whose new crawl has at least 90% of the baseline's rows, so a half-read
    # list can never shrink what the database holds
    loadable=()
    IFS=',' read -ra wanted <<< "$FAST_LISTS"
    for name in "${wanted[@]}"; do
      base_rows="$(rows "data/lists/$name/lists-1/records.jsonl")"
      new_rows="$(rows "data/lists/$name/$run/records.jsonl")"
      if [ "$new_rows" -gt 0 ] && [ "$new_rows" -ge $(( base_rows * 9 / 10 )) ]; then
        loadable+=("$name")
      else
        echo "| lists-load $name | skipped: $new_rows rows, baseline $base_rows | |" >> "$summary"
      fi
    done
    if [ "${#loadable[@]}" -gt 0 ]; then
      csv="$(IFS=,; echo "${loadable[*]}")"
      step lists-load 0 sfda-lists-load --lists "$csv" --run-id "$run"
      step cache-invalidate-lists 0,4 cache-invalidate
      # The assistant's cited passages: only rows that have no chunks yet get their documents read,
      # and their chunks are ADDED (a plain build would replace full chunks with thin ones).
      knowledge=()
      for name in $KNOWLEDGE_LISTS; do
        case ",$csv," in *",$name,"*) knowledge+=("$name") ;; esac
      done
      if [ "${#knowledge[@]}" -gt 0 ]; then
        kcsv="$(IFS=,; echo "${knowledge[*]}")"
        into="know-$stamp"
        step knowledge-new-rows 0 knowledge-new-rows --run-id "$run" --into "$into" --lists "$kcsv"
        if grep -Eq "total new rows: [1-9][0-9]*" "$logs/knowledge-new-rows.log"; then
          step knowledge-details 0 sfda-list-details --list-run-id "$into" --lists "$kcsv"
          step knowledge-files 0 sfda-list-files --list-run-id "$into" --lists "$kcsv"
          step knowledge-texts 0 sfda-list-texts --list-run-id "$into" --lists "$kcsv"
          echo "| knowledge-ocr | skipped: the OCR is Windows only, scanned PDFs get no text | |" >> "$summary"
          step knowledge-build 0 knowledge-build --run-id "$into" --lists "$kcsv" --additive
          step knowledge-embed 0 knowledge-embed
        fi
      fi
    fi
  fi
fi

# keep only the last few runs: the next day compares with the latest complete one
find data/sfda -maxdepth 1 -type d -name 'update-*' -mtime +4 -exec rm -rf {} + 2>/dev/null
find data/lists -maxdepth 2 -type d -name 'lists-20*' -mtime +4 -exec rm -rf {} + 2>/dev/null
find data/lists -maxdepth 2 -type d -name 'know-20*' -mtime +4 -exec rm -rf {} + 2>/dev/null

cat "$summary"
[ "$failed" -gt 0 ] && exit 1
exit 0
