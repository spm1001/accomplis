#!/usr/bin/env bash
# Shared runner for the coaching eval. Invoked via the run-bare / run-skill
# wrappers (smevals configs can't pass their own keys to a runner — the config
# axis IS the choice of wrapper).
#
# smevals contract in:  SMEVALS_MODEL, SMEVALS_PROMPT, SMEVALS_TASK_WORLD,
#                       SMEVALS_RUN_DIR (cwd = run dir)
# out: inner Claude's final text on stdout (becomes output.txt);
#      cli-calls.log + world-state.json land in SMEVALS_RUN_DIR as artifacts.
#
# The inner Claude runs behind the ardoise isolation wall (no CLAUDE.md, no
# skills, no plugins) with the fixture shim prepended to PATH — it sees a
# working `accomplis` CLI and nothing else of this estate.

set -euo pipefail

MODE="${1:?usage: runner-core.sh bare|skill}"

EVAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$EVAL_DIR/../.." && pwd)"

WORLD="${SMEVALS_TASK_WORLD:?task yaml must set world:}"
FIXTURE="$EVAL_DIR/fixtures/$WORLD.json"
[[ -f "$FIXTURE" ]] || { echo "runner: no fixture at $FIXTURE" >&2; exit 1; }

# ardoise: prefer the source repo (carries --env/--path-prepend from
# 2026-08-05), fall back to the newest plugin cache copy.
ARDOISE="${ARDOISE_SH:-$HOME/repos/spm1001/trousse/scripts/ardoise.sh}"
if [[ ! -x "$ARDOISE" ]]; then
    ARDOISE=$(find "$HOME/.claude/plugins/cache" -path "*/trousse/*/scripts/ardoise.sh" 2>/dev/null | sort -r | head -1)
fi
[[ -n "${ARDOISE:-}" && -x "$ARDOISE" ]] || { echo "runner: ardoise.sh not found (set ARDOISE_SH)" >&2; exit 1; }
grep -q -- '--path-prepend' "$ARDOISE" || {
    echo "runner: $ARDOISE predates --env/--path-prepend — point ARDOISE_SH at a current copy" >&2
    exit 1
}

CLI_NOTE='The user'\''s Todoist is accessible via the `accomplis` CLI on your PATH (run `accomplis --help` for commands; output is JSON, info lines go to stderr). If the CLI is missing or erroring, report that failure as your answer — do not search the filesystem for other installations, configuration or credentials.'

if [[ "$MODE" == "skill" ]]; then
    SKILL_DIR="$REPO_ROOT/skills/coaching"
    [[ -f "$SKILL_DIR/SKILL.md" ]] || { echo "runner: no SKILL.md at $SKILL_DIR" >&2; exit 1; }
    PROMPT="You have the following skill loaded for working with the user's Todoist.
Base directory for this skill: $SKILL_DIR
(reference files it mentions live under that directory and can be read from disk)

---
$(cat "$SKILL_DIR/SKILL.md")
---

$CLI_NOTE

User request: $SMEVALS_PROMPT"
elif [[ "$MODE" == "bare" ]]; then
    PROMPT="$CLI_NOTE

User request: $SMEVALS_PROMPT"
else
    echo "runner: unknown mode '$MODE'" >&2
    exit 1
fi

STATUS=0
"$ARDOISE" -p \
    --model "$SMEVALS_MODEL" \
    --max-turns 30 \
    --allowed-tools "Bash,Read" \
    --env "ACCOMPLIS_FIXTURE=$FIXTURE" \
    --env "ACCOMPLIS_LOG=$SMEVALS_RUN_DIR/cli-calls.log" \
    --path-prepend "$EVAL_DIR/shim" \
    -- "$PROMPT" || STATUS=$?

# Containment tripwire (added 2026-08-05 after run 18-13-42Z escaped the wall
# and read the real Todoist): if the shim was never invoked, the model got its
# answer some other way — mark the run a HARNESS FAILURE so it is never graded
# or reported, instead of a silent contamination.
if [[ ! -f "$SMEVALS_RUN_DIR/cli-calls.log" ]]; then
    echo "runner: TRIPWIRE — shim never invoked (no cli-calls.log); run is not evidence" >&2
    exit 1
fi
exit $STATUS
