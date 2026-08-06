# Coaching skill eval

Measures whether the accomplis **coaching skill** makes a blank-slate Claude discover a user's actual GTD structure before acting — and coach in achievement language — compared with the same Claude given only the CLI. Built with [smevals](https://github.com/prime-radiant-inc/smevals); the with/without-skill delta IS the eval.

## What it can and cannot tell you

**Measures: efficacy.** Does the skill's *content* improve behaviour, given that it loaded? The inner Claude runs behind the ardoise isolation wall (no CLAUDE.md, no shards, no plugins), so the `skill` config injects SKILL.md into the prompt directly.

**Does not measure: routing.** Whether a real session with the full user config *invokes* `Skill(coaching)` unprompted is exactly the property the isolation wall strips (the always-loaded `rules/accomplis.md` shard never exists inside ardoise). Routing is verified separately — a driven interactive session (hublot) or a real teammate rollout session. Don't let a green here stand in for that.

## Anatomy

| Piece | What it does |
|---|---|
| `fixtures/world-a.json` | Sections-as-outcomes layout ("Outcomes 2026"), `@` prefix contexts. Planted: 2 stale waits, an outcome with no next action, a near-duplicate pair, 2 inbox items. |
| `fixtures/world-b.json` | Lanes layout — outcomes are TASKS in "Client Projects" (sections are Now/Next/Someday), `&` prefixes, plus a shared workspace project with a 4-task unassigned pool. |
| `shim/accomplis` | Stateful fixture CLI impersonating the real one (stdlib python3 — the wall has no uv). Mirrors output shapes, stderr info lines, error texts + the "STOP: load the skill" nudge; logs every argv to `cli-calls.log`; writes mutate per-run state so read-backs work. Timestamp placeholders (`{{DAYS_AGO:n}}`) resolve at state init so staleness stays stable forever. |
| `runner-core.sh` + `run-bare`/`run-skill` | smevals configs can't pass keys to runners, so the config axis is the choice of wrapper. Both get a one-line CLI affordance; `skill` additionally gets SKILL.md verbatim with its real base directory (reference files load from disk, as in a real session). Needs ardoise with `--env`/`--path-prepend` (trousse, 2026-08-05). |
| `checkers/cli-log` | Deterministic checks on the call log, expectations keyed by task name inside the script. Also counts `guessed_container_calls` — queries naming projects that don't exist (assumption-driven behaviour, quantified). No CLI contact at all scores 0. |
| `checkers/judge` | LLM judge (blank-slate via ardoise, so estate conventions can't colour grading) scoring `output.txt` against the task's `rubric:` key. |

Two graders per run: `default` (deterministic, cheap) and `judge` (LLM), side by side per the smevals design.

## The fixtures deliberately mismatch the skill's examples

World A's outcomes project is *not* called "Desired Outcomes"; world B breaks the sections-are-outcomes assumption entirely. A model that pattern-matches the skill's own examples instead of discovering the layout fails `list-outcomes-b` (reporting Now/Next/Someday as "outcomes") and `create-outcome-b` (minting a section on a lanes board).

## Running

```bash
cd evals/coaching
smevals run . -c bare  -g      # every task, bare config, deterministic-graded
smevals run . -c skill -g
smevals grade . -g judge       # LLM judge over all ungraded runs
smevals report .               # config × model leaderboard
smevals report . -g judge --by-task
smevals run . -c bare -n 5 -g  # top up to 5 runs/task for mean ± stderr
```

Costs real tokens: each run is an inner `claude -p` session (~1 min, ~5-8 CLI calls), each judge one short call. 6 tasks × 2 configs × n runs.

After editing a rubric or checker: `smevals grade . -g judge --regrade`.

## Isolation (tgt-wisuwe)

Two walls, doing different jobs. **ardoise is context isolation** — no CLAUDE.md, no skills, no plugins — and it is not a security boundary: on 2026-08-05 one run of 63 escaped it and answered from the real Todoist board. **Credential isolation is the kernel's**: by default the runner now executes the inner Claude as a separate user (`mitester` on tube) that cannot read `/home/modha` (mode 700) at all — no real accomplis token, no session transcripts, no estate. The runner stages fixture/shim/skill into the eval user's home, crosses with `sudo -n`, and copies `cli-calls.log` / `world-state.json` back.

Knobs (env): `EVAL_ISOLATION=none` (dev escape hatch, unwalled), `EVAL_USER` (default `mitester`), `EVAL_SHIM_DIR` (point at `shim-sabotage/` for containment tests), `EVAL_KEEP=1` (retrieve the inner session transcript as `inner-transcript.jsonl` for forensics).

Billing on the far side: if the caller is on Vertex, the runner passes the Vertex config through but swaps ADC for the eval user's **own scoped service-account key** (`eval-mitester@itv-mit-llm-sameer`, `roles/aiplatform.user` on the pot only — model calls, no data). Never copy a broad ADC across the wall. If the key needs re-minting: `gcloud iam service-accounts keys create` for that SA, install at `/home/mitester/.config/gcloud/eval-vertex-sa.json`, mode 600, owner mitester. Off Vertex, the inner claude uses mitester's own `~/.claude/.credentials.json` login.

**`./containment-check.sh [MODEL]` is the falsifier — run it after any change to the runner, ardoise, or provisioning.** Kernel denial probes (with a known-positive control), leak markers derived from the live board at check time (never committed), a synthetic-positive proving the leak grep can fire, a sabotaged batch (shim errors on every call — outputs must report failure and carry zero markers), and a happy-path run (isolation must not break the eval). A sabotage run counts as evidence only if `cli-calls.log` shows the shim was invoked — on the first live run a harness auth failure passed both greps vacuously, and that gate is the fix.

Honest residuals: the inner session necessarily holds *some* model-billing credential (the scoped SA key, or mitester's own claude login) and network egress is not blocked — the wall protects the estate's data and credentials, not the fixture contents, and a run can still spend pot money. Context isolation, credential isolation; not an airgap.

## First campaign (2026-08-05) — headline results

Current as of that evening's runs (sonnet n≈5, opus/fable n=3, honest judge); regenerate reports from `runs/` for anything load-bearing.

- **Discovery needs no skill at any model tier** — bare Sonnet/Opus/Fable all pass both fixture-world traps, every run, zero guessed containers.
- **Method and convention need it at every tier** — bare Fable and bare Opus both score 0.82 on weekly-review (delete-language in prose, missed planted catches) vs 0.95–1.00 with the skill.
- **Economy is universal** — the skill cuts CLI calls ~33–40% for every model (fable 10.4→6.6, sonnet 14.7→8.6, opus 16.1→10.8).
- **Attention-narrowing is real and capability-graded** — skill-Sonnet read the Inbox in 0% of take-this-on runs (bare: 100%); skill-Opus and skill-Fable kept sweeping (100%). Fixed by moving the grounding method INTO SKILL.md (0%→80%); the same text in PATTERNS.md changed nothing — residence beats richness, measured.
- **Judge rubrics are floors, not fences** — the first judge zeroed fixture-accurate answers as "fabrication"; see checkers/judge and the 2026-08-05 commits.
- Containment: one run of 63 escaped the context wall pre-tripwire (read-only). Fixed 2026-08-06: runs now execute as a separate no-secrets user — see **Isolation** above and `containment-check.sh` (16/16 on first full pass).

## Caveats

- **Control-test the judge like the checkers.** Hand a known-rich, fixture-accurate answer to any new rubric or judge prompt before trusting its scores — the first judge here zeroed correct answers as "fabrication" because it read the rubric as exhaustive, and the bias was caught by hand-reading, not by design.
- **Bare is not zero-affordance:** the bare config still names the CLI in the prompt (a user who installed accomplis but has no skill). A true nothing baseline would trivially score 0 and measure nothing.
- The shim's `filter` supports only `#Project` / `today` / `overdue` / `assigned to: me`; exotic filter syntax returns `[]` silently. If runs show heavy filter use, extend the shim before reading those results.
- The CLI's own stderr hints teach ("Use --unassigned for triage") — observed doing exactly that in the first bare smoke run. That's signal, not noise: it shows which behaviours the CLI already affords without the skill.
