# todoist-gtd

> **Status:** Beta — actively developed
> **Works with:** Claude Code, standalone CLI
> **Install:** via the `batterie` marketplace (`spm1001/batterie`)
> **Requires:** Python 3.11+, Todoist account + API token

Todoist CLI with GTD coaching for Claude Code.

A Python CLI for Todoist that understands GTD semantics — outcomes vs actions, team priorities, weekly reviews. Designed as a Claude Code skill but works standalone too.

## Quick Start

Install via the batterie marketplace:

```bash
claude plugin marketplace add spm1001/batterie
/plugin install todoist-gtd@batterie
```

Then set up authentication and verify:

```bash
todoist auth                    # Prints setup instructions
todoist auth --token YOUR_TOKEN # Store your API token
todoist doctor                  # Verify everything works
```

## Authentication

Get your API token from [Todoist developer settings](https://app.todoist.com/app/settings/integrations/developer), then store it:

```bash
todoist auth --token YOUR_API_TOKEN
```

Token is stored in macOS Keychain (if available) or in a file with restricted permissions on Linux.

## CLI Usage

```bash
# List projects
todoist projects

# Tasks in a project
todoist tasks --project "@Work"

# Filter syntax (same as Todoist app)
todoist filter "today"
todoist filter "assigned to: Alex & @waiting-for"

# Complete a task
todoist done <task-id>

# Add a task
todoist add "Review proposal" --project "@Work" --section "Now"

# Utility commands
todoist doctor   # Check setup and diagnose issues
todoist version  # Show version and commit info
```

## As a Claude Code Skill

<!-- GENERATED:SKILLS:START -->
1 skill, tabled from `skills/*/SKILL.md` frontmatter by [render-skills.py](https://github.com/spm1001/batterie-de-savoir/blob/main/scripts/render-skills.py) — regenerate from this repo's root with
`uv run --script ../batterie-de-savoir/scripts/render-skills.py .`

| Skill | What it does |
|-------|--------------|
| `/coaching` | MANDATORY gate BEFORE any Todoist operation — orchestrates GTD semantics the CLI alone can't provide (outcomes are sections not tasks, workspace vs personal filtering, horizon alignment) |
<!-- GENERATED:SKILLS:END -->

When installed, Claude gains:
- **GTD vocabulary** — outcomes, areas, waiting-fors
- **Structure awareness** — outcomes as sections, 3-tier ontology
- **Weekly review support** — stale outcomes, overcommitment patterns
- **Outcome coaching** — activity language vs achievement language

Claude triggers this skill on phrases like:
- "check my @Claude inbox"
- "what's waiting for?"
- "is this a good outcome?"
- "weekly review"

## GTD Structure Expected

This skill assumes a specific Todoist setup:

| Concept | Todoist Implementation |
|---------|----------------------|
| **Outcomes** | Sections in "Desired Outcomes Q1" project |
| **Team Priorities** | Sections in a separate project |
| **Next Actions** | Tasks under outcome sections |
| **Waiting For** | `@Wait` project or `waiting-for` label |

Adapt the project names in SKILL.md to match your structure.

## Files

```
todoist-gtd/
├── src/todoist_gtd/      # Python package
│   ├── cli.py            # Main CLI (todoist command)
│   ├── auth.py           # Token-based authentication
│   ├── token_store.py    # Keychain integration
│   ├── common.py         # Shared utilities
│   └── flatten.py        # Subtask flattening (todoist-flatten)
├── skills/coaching/      # Claude Code skill
│   ├── SKILL.md          # Skill definition
│   └── references/       # GTD vocabulary, patterns, coaching
├── pyproject.toml        # Package config + entry points
└── docs/                 # Field reports and design docs
```

## Troubleshooting

### Auth Failures

**"Token revoked or expired"**
- Re-run `todoist auth --token TOKEN` with a fresh token from Todoist settings.

**"Keychain is locked"** (macOS)
- Unlock your macOS Keychain (Keychain Access app or `security unlock-keychain`).
- Or use `TODOIST_API_KEY` environment variable instead.

### Network Errors

**"Request timed out"**
- Slow connection or Todoist API issues. Retry in a moment.

**"Could not connect to Todoist"**
- Check your network connection.

### CLI Errors

**"Task not found or invalid"**
- Task ID doesn't exist or is malformed. Copy the full ID from Todoist.

**"Cannot move task between workspaces"**
- Todoist doesn't allow moving tasks between personal and team workspaces.
- Workaround: Complete the task and recreate it in the target project.

**"Rate limited by Todoist"**
- Too many requests. Wait a moment and retry.

## For Team Members

If you're joining as a contributor:

1. **Clone and install** as above
2. **Get your own API token** from [Todoist developer settings](https://app.todoist.com/app/settings/integrations/developer)
3. **Read CLAUDE.md** — repo conventions and contribution guidelines
4. **Check for open work** — `bon list --ready` shows available work

### Contributing via Claude

When using Claude to contribute:
- Claude reads CLAUDE.md at session start — conventions are discoverable
- Issue/PR templates appear at point of action — guidance when you need it
- See CONTRIBUTING.md for detailed guidelines

## Security

- **Tokens** stored in macOS Keychain or in a restricted-permissions file on Linux
- No secrets in this repo

## License

MIT
