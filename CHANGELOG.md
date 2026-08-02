# Changelog

All notable changes to todoist-gtd.

## [2026-08-02] — review + field-report pass (ships with next suite bump)

### Fixed
- **`todoist-flatten` crashed on launch since 2026-03-30**: commit dc9f928 renamed `resolve_project_with_name` → `resolve_project_object` in common.py but flatten.py kept importing the old name. Four months of green CI never noticed because nothing imported flatten — `tests/test_imports.py` now smoke-imports every module and entry point.
- **Version-stable token storage never engaged** (tgt-kobale): the plugin-data gate pointed at the pre-cutover dir name `todoist-gtd-batterie-de-savoir`, which Claude Code stopped creating at the 2026-06-10 cutover, so storage always fell back to `~/.todoist-token`. Now `todoist-gtd-batterie`, with first-read migration from both older locations, test-backed (`tests/test_token_store.py`).
- SKILL.md's weekly-review summary contradicted GTD_METHODOLOGY.md — realigned to Peake's ordering (Get Current → Get Clear → Get Creative).

### Added (tgt-hiredu — first heavy live use surfaced these)
- `todoist update --no-section` — move a task out of its section to the project root.
- `todoist update --order N` and `todoist reorder ID [ID...]` — queue arrangement; `reorder` assigns positions 1..N in the sequence given. Verified live: a move resets order to 1, so order is applied after any move.
- CLI_REFERENCE: "Moving, Sections, and Ordering" section, and a data-model note that `created_at` carries the API's `added_at` (there is no `added_at` key in output — the field report's "added_at is null" was jq minting null for a missing key).

### Changed
- Skill teaches structure **discovery over assertion**: outcomes may be sections OR tasks (read the section names to tell), context-project prefixes are per-user convention (`@`, `&`, none), not a rule.
- References genericised for the public marketplace: real team outcomes replaced with generic examples, stale MCP-era references removed, obsolete "arc" tracker vocabulary replaced, Sublime/macOS-specific editor loop generalised, personal "freedom score" metric replaced with a generic headroom check (completes the 2026-03-30 decision).
- Python floor aligned on 3.11 everywhere (pyproject already enforced it; doctor and CLAUDE.md claimed 3.9). `doctor` and `auth --status` fetch one page instead of all projects. Removed unused imports, vestigial requirements.txt, and a reference to a CONTRIBUTING.md that doesn't exist.

## [0.4.8] - 2026-06-20

### Docs
- Post-cutover staleness sweep. README install used the pre-cutover marketplace name (`add spm1001/batterie-de-savoir` + unqualified `/plugin install todoist-gtd`) → `claude plugin marketplace add spm1001/batterie` + `todoist-gtd@batterie`. CLAUDE.md install paths fixed (`~/Repos` → `~/repos/spm1001`, git+https fallback, `--no-cache` on reinstall). The coaching skill's "install the CLI" step taught the plugin-cache `find ... pyproject.toml` pattern that fails post-cutover (cache ships no pyproject) — replaced with the source-repo / git+https logic the SessionStart hook already uses. CLI_REFERENCE install verb names the source repo.
- NOTE: the stale plugin-data token-dir name (`todoist-gtd-batterie-de-savoir` in token_store.py/ensure-todoist.sh/CLI_REFERENCE — CC now creates `todoist-gtd-batterie`) is tracked separately as tgt-kobale (migration-safe code fix, not shipped here).

## [0.4.7] - 2026-06-20

### Fixed
- `ensure-todoist.sh` auto-update is now diagnosable: installs run with `--no-cache` (a plugin.json-only bump leaves `src/` byte-identical, so without it uv reuses the cached build and the version never moves), and install/update stderr is captured to `~/.cache/todoist/auto-update.log` — the log path and a `--no-cache` recovery command are surfaced on failure instead of a bare "auto-update failed." Propagated from bon (bon-babuse / bon-mavemi).

## [2026-02-01]

### Added
- Validation tests for project and section resolution

### Changed
- Project/section resolution now fails gracefully with helpful error messages
  - Shows available options when project or section not found
  - Includes reminder to load todoist-gtd skill
- Migrated from beads to arc for issue tracking
- All SKILL.md examples now use absolute path `~/.claude/scripts/todoist`
- PATTERNS.md: Added "Bulk Action Intake (Sublime Loop)" pattern

### Fixed
- `--section` flag no longer throws raw 400 error when section doesn't exist

## [2026-01-29]

### Added
- `todoist delete ID` — delete tasks (works on completed tasks too)
- `todoist uncomplete ID` — reopen completed tasks
- `todoist completed` — list completed tasks with `--since`, `--until`, `--project`
- `flatten-subtasks.py` — convert subtask hierarchies to flat tasks with descriptions
  - Dry-run by default, `--execute` to apply
  - Automatic backup before changes
  - `--restore` to recover from backup
  - `--delete-subtasks` for permanent removal (vs completing)
  - Safety checks: nested subtasks, description length limits
- `todoist_common.py` — shared module for code reuse
- `test_todoist.py` — test suite with smoke tests and pytest classes
- pytest added to requirements.txt

### Changed
- Refactored todoist.py to use shared module (~100 lines reduced)
- Refactored flatten-subtasks.py to use shared module
- Replaced httpx with requests session (SDK compatibility)
- `doctor` command no longer checks for httpx

### Fixed
- SDK session bug: httpx Response lacks `.ok` attribute, breaking `complete_task`
- Timeout now properly configured via requests adapter with retry

### Removed
- httpx dependency (was causing SDK compatibility issues)

## [2026-01-16]

### Added
- `todoist doctor` command — checks Python, deps, wrapper, PATH, auth, network
- `todoist version` command — shows commit hash and date
- `scripts/install.sh` — automated setup script, now creates venv if missing
- `scripts/verify.sh` — acceptance tests (auth, project resolution, error handling)
- CLAUDE.md — repo instructions with contribution guidelines
- CONTRIBUTING.md — detailed guide for contributors (Claude-optimized)
- Issue templates — bug report and feature request
- PR template — focused scope, testing checklist
- LICENSE — MIT
- README: Troubleshooting section (auth, network, CLI errors)
- SKILL.md: Prerequisites section with pre-flight check
- SKILL.md: Error handling guidance table for Claude

### Changed
- README/SKILL.md: Consistent `todoist` wrapper usage throughout
- README: Quick Start now includes wrapper creation
- OAuth: Clear error when port 8080 is in use (no false fallback)
- OAuth manual mode: Prominent CSRF warning with user confirmation on state mismatch
- Errors: Rate limit detection, workspace-specific 400 handling
- Errors: 401/unauthorized detection with clear "run todoist auth" message
- Keychain: Surface locked/denied errors with actionable messages
- Keychain: Catch-all warning for unknown error codes

### Fixed
- Network: 30s timeout prevents indefinite hangs
- Dependencies: httpx now explicit in requirements.txt
- install.sh: Creates ~/.claude/.venv if missing (fresh system support)

### Removed
- AGENTS.md — redundant with /close skill

## [2026-01-15]

### Fixed
- Missing `requests` dependency in requirements.txt
- `resolve_project()` now handles names like "Personal", "Inbox"
- Invalid task IDs show clean error (catches 400 and 404)

### Added
- Initial issue tracking setup (tgt-h5o epic)

## [2026-01-07]

### Added
- Initial release: MCP-free Todoist CLI with GTD coaching
- OAuth authentication (auto and manual modes)
- Keychain integration for secure token storage
- Project, section, task queries with name resolution
- Filter command using Todoist filter syntax
- Task creation, completion, and updates
- GTD structure awareness (outcomes as sections)
- SKILL.md for Claude Code integration
