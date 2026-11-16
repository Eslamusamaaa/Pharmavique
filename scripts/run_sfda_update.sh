#!/bin/sh
# Daily SFDA refresh for cron or a container. Usage: run_sfda_update.sh [recheck]
# Example crontab line (every day at 03:00):
#   0 3 * * * /path/to/repo/scripts/run_sfda_update.sh 300
cd "$(dirname "$0")/.." || exit 1
mkdir -p data/sfda
RECHECK="${1:-300}"
echo "==== $(date) sfda-update (recheck $RECHECK)" >> data/sfda/update.log
uv run pharmavique sfda-update --recheck "$RECHECK" >> data/sfda/update.log 2>&1
STATUS=$?
echo "==== finished with exit code $STATUS" >> data/sfda/update.log
exit $STATUS
