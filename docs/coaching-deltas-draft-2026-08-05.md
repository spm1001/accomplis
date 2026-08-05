# Coaching skill deltas — drafted with live-session context

Drafted 2026-08-05, same day as the sessions that produced them (Stef review 2026-08-04, Sameer review + team meta-review 2026-08-05). Spec and provenance: `tgt-nefoja`. This file is near-final prose for the executor to integrate — the job downstream is editorial (skill-forge lint, weave into existing files, publish), not creative. Written because Sameer flagged that rewriting with lived context beats rewriting from a spec; he was right.

## For COACHING.md

### The two-axis test (add near top)

Every outcome gets marked on two independent axes:

- **Outcome-ness**: past tense, a state of the world, binary done-test. Would you know the exact moment it became true?
- **Desire**: the stake in the headline. Would you fight for this? Does reading it pull you forward?

An item can pass one and fail the other — and the two failure modes need **opposite treatments**:

- **Phrasing gap** (the Stef pattern): real desire exists but is absent from the sentence. Fix: write the stake into the headline. The desire is almost always one "so that" away, and the human supplies it in seconds when asked.
- **Dilution** (the Sameer pattern): well-phrased outcomes drowned by wrong-altitude neighbours — next actions, raw captures, duplicate trackers. Fix: move the non-outcomes out. Do NOT inject fake desire into admin; "Get Billing ID resolved" doesn't want a pulse, it wants a different shelf.

### The so-that ladder (add)

Ask "so that…?" repeatedly. Stop when the answer stops sounding like the org chart and starts sounding like something the person would fight for — that rung is the outcome. One rung further up is usually the Goals shelf (H3), not a DO.

Worked example: "Got automated all-imps feed running to Adalyser" → so that? → "I don't have to babysit Household:Lift any more." That's a jailbreak, not plumbing. Headline: *"Freed from Household:Lift babysitting — the all-imps feed runs itself into Adalyser."* Done-test and desire are now the same sentence.

### The champagne test (add)

Two halves, both required: would you know the **exact moment** to open the bottle (done-test), and would you **want** to (desire)? "Got automated feed running" passes the first only; "Get 3 OEMs excited" passes the second only; "Completed analysis elements" passes neither.

### Observable-behaviour rewrites (add — and FIX an existing example)

Inferred states can't be done-tests. Rewrite as the behaviour that would evidence them:

- "excited enough to want to work with us" → "asked us for a follow-up" / "committed to a pilot"
- "had positive feedback" → "agreed to be the story we tell on stage"
- "handed over brand stuff" → "a brand request landed and got answered without touching me"

NOTE: the current strong-examples table includes *"gets good client feedback"* — that fails this standard. Replace with an observable (e.g. "client asked to extend the engagement").

### Your-slice scoping (add)

On shared work, a person's DO is their slice: the furthest rung they can cause by their own actions this cycle. "Brought Judi's World Cup analysis to life with visuals — sales lifted my charts into their own decks" is honest ownership; claiming the analysis isn't. Corollary: name the neighbouring slice in the description so the pairing is visible — delegator holds the Waiting For, delegate holds the DO. Complementary slices on one strand (Stef negotiates the Adalyser deal, Ella executes the contract) are healthy, not collisions; a delegation with NO counterpart on the delegate's board is the bug.

### Read-the-arc (add)

After item-level coaching, read the whole board for a personal narrative and say it back: "clear the decks → get back on the craft bike → make it sing in public." Name the card that doesn't fit the arc and ask whether it's really theirs. Often the single highest-value move for the human — it turns a list into a story they recognise. Guard: read each new person's board cold; don't project the previous person's arc onto it.

### Mode table (add — replaces one-size-fits-all Socratic)

| Situation | Mode |
|---|---|
| Solo deep coaching | One question at a time (existing guidance stands) |
| Paired/live review — human + teammate in the room | Propose REWRITES to react against; batch is fine (Stef: six rewrites, "all good", landed) |
| Human elects card-by-card | End each round with exactly ONE question (Sameer chose this) |

Let the human pick. The choice is itself data about how they think.

## For SKILL.md

### Canon vs house (new section, prominent)

- **Allen (canon):** a Project is ANY desired result requiring more than one action step. The list is a complete inventory — 20-30 in flight is normal, and dull projects are still projects. Never "demote" a dull-but-real multi-step commitment off the list. Desirable FRAMING applies to everything; that's writing discipline, not tier privilege.
- **House (the two-tier design, Sameer 2026-08-05):** within the full visible inventory, a highlighted 3-5 are the *delegated outcomes* — the review tier, marked **p1** in Todoist. THOSE, read side by side across the team, should add up to team strategy. The "3-5 outcomes" target applies to the highlighted tier ONLY — applying it to the whole inventory is a category error this skill previously invited.

### Review order (new)

**Structure → altitude → language → arc → tier.** Coaching words before fixing structure wastes the polish.

1. **Structure**: sync automations and mirrors (check `systemctl --user list-units | grep -iE 'todoist|sync'` and cron before diagnosing duplication as mess — one user had a systemd timer deliberately twinning team-assigned tasks into a personal project; edits go to the canonical side, which the unit's own description states). Twin boards, duplication across horizon layers, orphaned/unassigned cards.
2. **Altitude**: census every card — DO / project / next action / raw capture / already-done. Complete the done, demote the actions, fold the captures (a calendar invite is a date, not a commitment).
3. **Language**: two-axis coaching per card.
4. **Arc**: the narrative read.
5. **Tier**: mark the highlighted handful (p1).

## For PATTERNS.md (structural detectors, add)

- **Staleness hides in titles**: dates written into card titles rot silently ("by June 4th" in bold, two months gone). Sweep titles for date strings against today.
- **Cross-board delegation audit**: every delegation on a lead's board needs a counterpart on the delegate's board. Complementary slices are fine; absent counterparts are the finding.
- **Team read-across test**: a cold reader attempts to reconstruct team strategy from the boards alone, then reports what was legible and what wasn't (found live: an empty Vision project, no tier marks anywhere, and a fourth strategic theme — AI/agents — that existed in card mass but no section named).
- **Emergent conventions reveal appetite**: two people independently bolding their biggies means the team wants a highlight tier — codify it (p1) rather than letting folk conventions drift.
- **Same diseases, every layer**: altitude-mixing recurs at team scale (a 57-card Goals board hiding a literal next action). The per-board patterns apply at any horizon.

## For CLI_REFERENCE.md (paper cuts, add)

- Info lines ("Showing 23 of 68…") go to **stderr**; `2>&1 | jq` therefore breaks. Pipe stdout only.
- `done` has no `--note`. Pattern: `accomplis update ID --description "closing note" && accomplis done ID`.
- `--assignee` takes name or email, NOT the numeric id that `collaborators` emits (until tgt-husule lands).
- Todoist 5xx wobbles happen mid-sweep: retry after ~15s, then **read back everything the failed sweep touched** before reporting done — three of four parallel writes once failed while the fourth succeeded.
