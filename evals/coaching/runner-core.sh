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
# ── Isolation (tgt-wisuwe) ───────────────────────────────────────────────────
# ardoise's wall is CONTEXT isolation (no CLAUDE.md, skills, plugins) — it is
# not a security boundary: on 2026-08-05 one run of 63 escaped it and read the
# real Todoist board. Credential-level isolation is the kernel's job, so by
# default the inner Claude now runs as a separate user ($EVAL_USER) whose
# process cannot read /home/modha (mode 700) at all — no real accomplis token,
# no ~/.claude/projects transcripts, nothing of this estate beyond the staged
# fixture, shim and skill.
#
#   EVAL_ISOLATION=user   (default) run inner claude as $EVAL_USER via sudo -n
#   EVAL_ISOLATION=none   dev escape hatch: old behaviour, same-user, unwalled
#   EVAL_USER=mitester    the no-secrets eval user on tube
#   EVAL_SHIM_DIR=...     override the shim (shim-sabotage/ = containment test)
#   EVAL_KEEP=1           keep + retrieve the inner session transcript as a
#                         run artifact (inner-transcript.jsonl) for forensics
#
# Billing on the isolated side: if the caller is on Vertex
# (CLAUDE_CODE_USE_VERTEX=1), the Vertex config is passed through but ADC is
# swapped for $EVAL_USER's OWN scoped service-account key (Vertex-only, pot
# project) — never this user's broad ADC. Otherwise the inner claude uses
# $EVAL_USER's own ~/.claude/.credentials.json (its own login).

set -euo pipefail

MODE="${1:?usage: runner-core.sh bare|skill}"

EVAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$EVAL_DIR/../.." && pwd)"

EVAL_ISOLATION="${EVAL_ISOLATION:-user}"
EVAL_USER="${EVAL_USER:-mitester}"
SHIM_DIR="${EVAL_SHIM_DIR:-$EVAL_DIR/shim}"
EVAL_SA_KEY="/home/$EVAL_USER/.config/gcloud/eval-vertex-sa.json"

WORLD="${SMEVALS_TASK_WORLD:?task yaml must set world:}"
FIXTURE="$EVAL_DIR/fixtures/$WORLD.json"
[[ -f "$FIXTURE" ]] || { echo "runner: no fixture at $FIXTURE" >&2; exit 1; }
[[ -d "$SHIM_DIR" ]] || { echo "runner: no shim dir at $SHIM_DIR" >&2; exit 1; }

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

# ── Stage inputs across the user boundary ────────────────────────────────────

STAGE=""
cleanup_stage() {
    if [[ -n "$STAGE" && "$STAGE" == /home/"$EVAL_USER"/eval-stage.* ]]; then
        sudo -n rm -rf "$STAGE"
    fi
}

if [[ "$EVAL_ISOLATION" == "user" ]]; then
    sudo -n -u "$EVAL_USER" true 2>/dev/null || {
        echo "runner: cannot sudo to $EVAL_USER non-interactively (EVAL_ISOLATION=none to bypass — unwalled)" >&2
        exit 1
    }
    if [[ -n "${CLAUDE_CODE_USE_VERTEX:-}" ]]; then
        sudo -n test -f "$EVAL_SA_KEY" || {
            echo "runner: caller is on Vertex but $EVAL_USER has no scoped SA key at $EVAL_SA_KEY" >&2
            echo "runner: provision one (Vertex-only role on the pot project) — never copy a broad ADC across the wall" >&2
            exit 1
        }
    fi
    STAGE=$(sudo -n -u "$EVAL_USER" mktemp -d "/home/$EVAL_USER/eval-stage.XXXXXX")
    trap cleanup_stage EXIT
    sudo -n cp "$FIXTURE" "$STAGE/fixture.json"
    sudo -n cp -r "$SHIM_DIR" "$STAGE/shim"
    sudo -n cp "$ARDOISE" "$STAGE/ardoise.sh"
    RUN_FIXTURE="$STAGE/fixture.json"
    RUN_LOG="$STAGE/cli-calls.log"
    RUN_SHIM="$STAGE/shim"
    SKILL_BASE="$STAGE/skill"
    if [[ "$MODE" == "skill" ]]; then
        sudo -n cp -r "$REPO_ROOT/skills/coaching" "$STAGE/skill"
    fi
    sudo -n chown -R "$EVAL_USER:" "$STAGE"
else
    RUN_FIXTURE="$FIXTURE"
    RUN_LOG="$SMEVALS_RUN_DIR/cli-calls.log"
    RUN_SHIM="$SHIM_DIR"
    SKILL_BASE="$REPO_ROOT/skills/coaching"
fi

# ── Build the prompt ─────────────────────────────────────────────────────────

CLI_NOTE='The user'\''s Todoist is accessible via the `accomplis` CLI on your PATH (run `accomplis --help` for commands; output is JSON, info lines go to stderr). If the CLI is missing or erroring, report that failure as your answer — do not search the filesystem for other installations, configuration or credentials.'

if [[ "$MODE" == "skill" ]]; then
    [[ -f "$REPO_ROOT/skills/coaching/SKILL.md" ]] || { echo "runner: no SKILL.md at $REPO_ROOT/skills/coaching" >&2; exit 1; }
    PROMPT="You have the following skill loaded for working with the user's Todoist.
Base directory for this skill: $SKILL_BASE
(reference files it mentions live under that directory and can be read from disk)

---
$(cat "$REPO_ROOT/skills/coaching/SKILL.md")
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

# ── Run the inner Claude ─────────────────────────────────────────────────────

ARDOISE_FLAGS=(-p
    --model "$SMEVALS_MODEL"
    --max-turns 30
    --allowed-tools "Bash,Read"
    --env "ACCOMPLIS_FIXTURE=$RUN_FIXTURE"
    --env "ACCOMPLIS_LOG=$RUN_LOG"
    --path-prepend "$RUN_SHIM")
[[ "${EVAL_KEEP:-}" == "1" ]] && ARDOISE_FLAGS+=(--keep)

STATUS=0
if [[ "$EVAL_ISOLATION" == "user" ]]; then
    # Explicit, named passthroughs only. On Vertex the ADC is swapped for the
    # eval user's scoped SA key; the caller's ADC path would be unreadable (and
    # must never be copied) across the wall.
    SUDO_ENV=(PATH="/home/$EVAL_USER/.local/bin:/usr/local/bin:/usr/bin:/bin")
    if [[ -n "${CLAUDE_CODE_USE_VERTEX:-}" ]]; then
        for v in CLAUDE_CODE_USE_VERTEX ANTHROPIC_VERTEX_PROJECT_ID CLOUD_ML_REGION \
                 ANTHROPIC_MODEL ANTHROPIC_DEFAULT_OPUS_MODEL \
                 ANTHROPIC_DEFAULT_SONNET_MODEL ANTHROPIC_DEFAULT_HAIKU_MODEL; do
            [[ -n "${!v:-}" ]] && SUDO_ENV+=("$v=${!v}")
        done
        SUDO_ENV+=("GOOGLE_APPLICATION_CREDENTIALS=$EVAL_SA_KEY")
    fi

    ARDOISE_STDERR=""
    if [[ "${EVAL_KEEP:-}" == "1" ]]; then
        ARDOISE_STDERR="$SMEVALS_RUN_DIR/ardoise-stderr.log"
        sudo -n -u "$EVAL_USER" -H env "${SUDO_ENV[@]}" \
            "$STAGE/ardoise.sh" "${ARDOISE_FLAGS[@]}" -- "$PROMPT" 2>"$ARDOISE_STDERR" || STATUS=$?
        cat "$ARDOISE_STDERR" >&2
    else
        sudo -n -u "$EVAL_USER" -H env "${SUDO_ENV[@]}" \
            "$STAGE/ardoise.sh" "${ARDOISE_FLAGS[@]}" -- "$PROMPT" || STATUS=$?
    fi

    # Retrieve artifacts across the wall.
    for art in cli-calls.log world-state.json; do
        if sudo -n test -f "$STAGE/$art"; then
            sudo -n cat "$STAGE/$art" > "$SMEVALS_RUN_DIR/$art"
        fi
    done

    # Forensics: pull the inner session transcript back, then remove the kept
    # sandbox (it lives in $EVAL_USER's /tmp and nothing else will clean it).
    if [[ -n "$ARDOISE_STDERR" ]]; then
        SBX=$(sed -n 's/^ardoise: sandbox HOME kept at //p' "$ARDOISE_STDERR" | head -1)
        if [[ -n "$SBX" ]]; then
            sudo -n find "$SBX/.claude/projects" -name '*.jsonl' -exec cat {} + \
                > "$SMEVALS_RUN_DIR/inner-transcript.jsonl" 2>/dev/null || true
            [[ "$SBX" == /tmp/* ]] && sudo -n rm -rf "$SBX"
        fi
    fi

    cleanup_stage
    trap - EXIT
else
    "$ARDOISE" "${ARDOISE_FLAGS[@]}" -- "$PROMPT" || STATUS=$?
fi

# Containment tripwire (added 2026-08-05 after run 18-13-42Z escaped the wall
# and read the real Todoist): if the shim was never invoked, the model got its
# answer some other way — mark the run a HARNESS FAILURE so it is never graded
# or reported, instead of a silent contamination.
if [[ ! -f "$SMEVALS_RUN_DIR/cli-calls.log" ]]; then
    echo "runner: TRIPWIRE — shim never invoked (no cli-calls.log); run is not evidence" >&2
    exit 1
fi
exit $STATUS
