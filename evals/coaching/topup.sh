#!/usr/bin/env bash
# Top up failed cells to target-n. Usage: topup.sh NEEDS_FILE CONFIG MODEL
# Reads lines "task config model count" from NEEDS_FILE, executes only rows
# matching CONFIG+MODEL, one smevals run per missing count. Aborts after 4
# consecutive RUN failures (rate-limit storm) — a graded fail is a result,
# not a failure, and does not count toward the abort.
set -uo pipefail
NEEDS="$1"; CFG="$2"; MDL="$3"
cd "$(dirname "${BASH_SOURCE[0]}")"
consec=0
while read -r t c m need; do
    [[ "$c" == "$CFG" && "$m" == "$MDL" ]] || continue
    for ((i = 0; i < need; i++)); do
        out=$(smevals run . -t "$t" -c "$c" -m "$m" -g 2>&1)
        echo "$out"
        if echo "$out" | grep -q 'FAILED'; then
            consec=$((consec + 1))
            if ((consec >= 4)); then
                echo "ABORT: $consec consecutive run failures — window looks dead"
                exit 1
            fi
        else
            consec=0
        fi
    done
done < "$NEEDS"
echo "topup complete for $CFG/$MDL"
