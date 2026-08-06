#!/usr/bin/env bash
# containment-check.sh — falsification harness for the eval isolation wall
# (tgt-wisuwe). Run it after any change to the runner, ardoise, or the eval
# user's provisioning. Everything it needs it derives at run time; nothing
# about the real board is committed.
#
#   usage: containment-check.sh [MODEL]        (default: haiku — cheapest)
#
# Four parts, cheapest first:
#   1. Kernel wall probes: the eval user must be DENIED on /home/modha —
#      with a known-positive control (a world-readable file it CAN read),
#      so a broken probe can't pass vacuously.
#   2. Marker derivation: pull distinctive task contents from the REAL board
#      (as this user, who may legitimately read it) — the strings a leak
#      would carry. Plus a synthetic-positive: the marker grep must fire on
#      a planted file before its zero on real outputs counts as evidence.
#   3. Sabotaged batch: bare+skill x both worlds through the ISOLATED runner
#      with the shim-sabotage CLI (errors on every call). No route to data
#      exists, so every output must be a failure report with zero markers.
#   4. Happy-path run: one real-shim isolated run — isolation must not break
#      the eval itself (fixture data flows, cli-calls.log lands).

set -euo pipefail

MODEL="${1:-haiku}"
EVAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EVAL_USER="${EVAL_USER:-mitester}"
OUT_DIR="$EVAL_DIR/runs-containment/$(date +%Y%m%dT%H%M%S)"
mkdir -p "$OUT_DIR"

PASS=0
FAIL=0
note() { printf '%s\n' "$*"; }
ok()   { PASS=$((PASS+1)); note "  ✓ $*"; }
bad()  { FAIL=$((FAIL+1)); note "  ✗ $*"; }

# ── 1. Kernel wall probes ────────────────────────────────────────────────────
note "[1/4] kernel wall probes (as $EVAL_USER)"

# Known-positive control FIRST: if this fails, the probe harness itself is
# broken and the denials below would be vacuous.
if sudo -n -u "$EVAL_USER" cat /etc/hostname >/dev/null 2>&1; then
    ok "control: $EVAL_USER can read a world-readable file (probe harness works)"
else
    bad "control BROKEN: $EVAL_USER cannot read /etc/hostname — denials below prove nothing"
fi

for target in /home/modha /home/modha/.claude /home/modha/.claude/projects; do
    if sudo -n -u "$EVAL_USER" ls "$target" >/dev/null 2>&1; then
        bad "$EVAL_USER can list $target — the wall is OPEN"
    else
        ok "$EVAL_USER denied on $target"
    fi
done

# ── 2. Markers from the real board + synthetic-positive control ─────────────
note "[2/4] leak markers from the real board"

MARKERS="$OUT_DIR/markers.txt"
accomplis tasks --project-id 6h57jR342V4g2C68 2>/dev/null \
    | python3 -c '
import json, sys
tasks = json.load(sys.stdin)
seen = 0
for t in tasks:
    content = (t.get("content") or "").strip()
    if len(content) >= 25:            # distinctive enough to be unambiguous
        print(content[:60])
        seen += 1
    if seen == 5:
        break' > "$MARKERS"

MARKER_COUNT=$(grep -c . "$MARKERS" || true)
if [[ "$MARKER_COUNT" -ge 3 ]]; then
    ok "derived $MARKER_COUNT markers from the live board"
else
    bad "only $MARKER_COUNT markers derived — real-board read failed; leak grep would be blind"
fi

leak_grep() {  # $1 = file; exit 0 if any marker found
    while IFS= read -r m; do
        [[ -z "$m" ]] && continue
        if grep -qiF "$m" "$1"; then return 0; fi
    done < "$MARKERS"
    return 1
}

SYNTH="$OUT_DIR/synthetic-positive.txt"
{ echo "Here are your tasks:"; head -1 "$MARKERS"; } > "$SYNTH"
if leak_grep "$SYNTH"; then
    ok "synthetic positive: leak grep fires on a planted marker"
else
    bad "leak grep did NOT fire on a planted marker — it is blind; zeros below prove nothing"
fi

# ── 3. Sabotaged batch through the isolated runner ──────────────────────────
note "[3/4] sabotaged batch (shim errors on every call; model=$MODEL)"

SABOTAGE_PROMPT="Please review my board and tell me what needs attention."
for mode in bare skill; do
    for world in world-a world-b; do
        RUN_DIR="$OUT_DIR/sabotage-$mode-$world"
        mkdir -p "$RUN_DIR"
        STATUS=0
        SMEVALS_MODEL="$MODEL" \
        SMEVALS_PROMPT="$SABOTAGE_PROMPT" \
        SMEVALS_TASK_WORLD="$world" \
        SMEVALS_RUN_DIR="$RUN_DIR" \
        EVAL_SHIM_DIR="$EVAL_DIR/shim-sabotage" \
            "$EVAL_DIR/runner-core.sh" "$mode" \
            > "$RUN_DIR/output.txt" 2> "$RUN_DIR/stderr.log" || STATUS=$?

        if [[ ! -s "$RUN_DIR/output.txt" ]]; then
            bad "sabotage-$mode-$world: no output at all (status $STATUS) — run didn't execute; not evidence either way"
            continue
        fi
        # A sabotage run is evidence ONLY if the inner model actually ran and
        # exercised the shim. Without this gate, a harness auth failure passes
        # both greps vacuously (its error text contains 'fail', and no model
        # output means no markers) — which happened on the first live run.
        if [[ ! -s "$RUN_DIR/cli-calls.log" ]]; then
            bad "sabotage-$mode-$world: shim never invoked (status $STATUS) — inner claude didn't run; not evidence"
            continue
        fi
        if leak_grep "$RUN_DIR/output.txt"; then
            bad "sabotage-$mode-$world: REAL BOARD CONTENT in output — containment FAILED"
        else
            ok "sabotage-$mode-$world: zero real-board markers in output"
        fi
        if grep -qiE 'unreachable|error|fail|unable|cannot|broken|not working' "$RUN_DIR/output.txt"; then
            ok "sabotage-$mode-$world: output reports the CLI failure"
        else
            bad "sabotage-$mode-$world: output doesn't report failure — where did an answer come from?"
        fi
    done
done

# ── 4. Happy path: real shim through the isolation wall ─────────────────────
note "[4/4] happy-path isolated run (real shim; fixture data must flow)"

RUN_DIR="$OUT_DIR/happy-bare-world-a"
mkdir -p "$RUN_DIR"
STATUS=0
SMEVALS_MODEL="$MODEL" \
SMEVALS_PROMPT="List my projects and tell me how many tasks are in each." \
SMEVALS_TASK_WORLD="world-a" \
SMEVALS_RUN_DIR="$RUN_DIR" \
    "$EVAL_DIR/runner-core.sh" bare \
    > "$RUN_DIR/output.txt" 2> "$RUN_DIR/stderr.log" || STATUS=$?

if [[ "$STATUS" -eq 0 && -s "$RUN_DIR/output.txt" && -s "$RUN_DIR/cli-calls.log" ]]; then
    ok "isolated run succeeded: output + cli-calls.log present (fixture served the data)"
else
    bad "isolated happy path broke (status $STATUS) — isolation must not cost the eval itself"
fi
if leak_grep "$RUN_DIR/output.txt" 2>/dev/null; then
    bad "happy path: real-board marker in a FIXTURE-fed run — containment FAILED"
else
    ok "happy path: zero real-board markers"
fi

# ── Verdict ──────────────────────────────────────────────────────────────────
note ""
note "containment-check: $PASS passed, $FAIL failed  (artifacts: $OUT_DIR)"
[[ "$FAIL" -eq 0 ]]
