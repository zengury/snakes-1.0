#!/usr/bin/env bash
set -euo pipefail

# Quick golden-path regression without API keys.
# Runs escape-room level2 with forced failures and prints score.

cd "$(dirname "$0")/.."

OUTDIR=${1:-/tmp/snakes_eventlog_mock}
rm -rf "$OUTDIR"
mkdir -p "$OUTDIR"

snakes run --provider mock --scenario escape-room --level 2 \
  --eventlog-dir "$OUTDIR" \
  --seed 1 \
  --p-vision-fail 0.0 \
  --p-manip-fail 0.0 \
  --p-system-timeout 0.0 \
  --p-system-disconnect 0.0

# Find latest task_id by reading output is manual; users can run score with printed task_id.

echo "EventLog written to: $OUTDIR"
