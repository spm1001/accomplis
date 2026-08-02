#!/usr/bin/env python3
"""
Todoist CLI - MCP-free interface using official Python SDK.

Usage:
    accomplis <command> [options]

Commands:
    auth                Show setup instructions
    auth --token TOKEN  Store a personal API token
    auth --status       Check authentication status
    projects            List all projects
    add-project NAME    Create a new project (--parent, --color, --favorite)
    update-project P    Update a project (--name, --color, --favorite)
    sections            List sections (--project or --project-id to filter)
    add-section NAME    Create a new section (--project or --project-id)
    tasks               List tasks with comments inline
                        Supports --project, --section, --older-than, --include-section-name
                        Auto-filters workspace projects to your tasks (--unassigned for triage, --team for all)
    task ID             Get single task with comments inline
    filter QUERY        Filter tasks (no comments - can return many)
    done ID             Complete a task
    delete ID           Delete a task (works on completed tasks too)
    uncomplete ID       Uncomplete/reopen a task
    completed           List completed tasks (--since, --until, --project)
    add CONTENT         Create a new task (--project, --section for placement)
    update ID           Update/move task (--content, --project, --section, --no-section, --order, etc.)
    reorder ID [ID...]  Set task order to the sequence given (first = top)
    comments            Get comments standalone (rarely needed)
    collaborators       Get project collaborators (requires --project-id)
    whoami              Show current authenticated user

Authentication:
    Run `accomplis auth` to set up (opens Todoist settings, prompts for token).
    Token is stored in macOS Keychain or ~/.todoist-token.
    Or set TODOIST_API_KEY environment variable directly.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from typing import Any

from accomplis.common import (
    get_api,
    get_current_user,
    collect_paginated,
    to_dict,
    resolve_project,
    resolve_project_object,
    resolve_section,
    resolve_assignee,
    handle_task_not_found,
    api_call_with_retry,
    DEFAULT_TIMEOUT,
)


def output_json(data: Any):
    """Output data as JSON."""
    if isinstance(data, list):
        print(json.dumps([to_dict(item) for item in data], indent=2, default=str))
    else:
        print(json.dumps(to_dict(data), indent=2, default=str))


def cmd_get_projects(args):
    """List all projects."""
    api = get_api()
    projects = collect_paginated(api.get_projects())
    output_json(projects)


def cmd_get_sections(args):
    """List sections."""
    api = get_api()

    # Resolve project name to ID if provided
    project_id = args.project_id
    if args.project:
        project_id = resolve_project(api, args.project)

    sections = collect_paginated(api.get_sections(project_id=project_id))
    output_json(sections)


def cmd_get_tasks(args):
    """List tasks with optional filters."""
    api = get_api()

    # Resolve project name to ID, keeping the project object for workspace detection
    project_id = args.project_id
    project_obj = None
    if args.project:
        project_obj = resolve_project_object(api, args.project)
        project_id = project_obj.id
    elif args.project_id:
        # When using --project-id directly, fetch the project object for workspace detection
        try:
            project_obj = api.get_project(project_id=args.project_id)
        except Exception:
            pass  # Will fail later on get_tasks if invalid

    # Resolve section name to ID if provided
    section_id = args.section_id
    if args.section:
        if not project_id:
            print("Error: --section requires --project or --project-id", file=sys.stderr)
            sys.exit(1)
        section_id = resolve_section(api, project_id, args.section)

    tasks = collect_paginated(api.get_tasks(
        project_id=project_id,
        section_id=section_id,
        label=args.label
    ))

    # Fetch collaborators for shared projects (enrichment + explicit --assignee filtering)
    collabs = []
    assignee_map = {}
    if project_id:
        collabs = collect_paginated(api.get_collaborators(project_id))
        if collabs:
            assignee_map = {c.id: c.name for c in collabs}

    # Determine if this is a team workspace project (workspace_id set)
    is_workspace_project = (
        project_obj is not None
        and getattr(project_obj, 'workspace_id', None) is not None
    )

    # Assignee filtering: explicit --assignee, or auto-filter on workspace projects
    if args.assignee:
        if not project_id:
            print("Error: --assignee requires --project or --project-id to resolve collaborator", file=sys.stderr)
            sys.exit(1)
        assignee_id = resolve_assignee(api, project_id, args.assignee)
        tasks = [t for t in tasks if getattr(t, 'assignee_id', None) == assignee_id]
    elif is_workspace_project and collabs and not getattr(args, 'team', False):
        # Auto-filter workspace (team) projects to current user's tasks
        user = get_current_user()
        my_id = user['id']
        if getattr(args, 'unassigned', False):
            # Triage mode: show unassigned tasks only
            my_tasks = [t for t in tasks if getattr(t, 'assignee_id', None) is None]
            excluded = len(tasks) - len(my_tasks)
            if excluded > 0:
                print(f"Showing {len(my_tasks)} unassigned tasks of {len(tasks)} total. Use --team for all.", file=sys.stderr)
        else:
            # Default: assigned-to-me only (exclude unassigned)
            my_tasks = [t for t in tasks if getattr(t, 'assignee_id', None) == my_id]
            excluded = len(tasks) - len(my_tasks)
            if excluded > 0:
                print(f"Showing {len(my_tasks)} of {len(tasks)} tasks (assigned to {user['full_name']}). Use --unassigned for triage, --team for all.", file=sys.stderr)
        tasks = my_tasks

    # Filter by creation date if provided (client-side filter)
    if args.created_before and args.older_than:
        print("Error: Cannot use both --older-than and --created-before", file=sys.stderr)
        sys.exit(1)

    if args.created_before or args.older_than:
        def get_created(t):
            ca = t.created_at
            if isinstance(ca, str):
                return datetime.fromisoformat(ca[:19])
            return ca.replace(tzinfo=None)  # datetime object

        if args.older_than:
            match = re.match(r'(\d+)([dwm])', args.older_than)
            if not match:
                print("Error: --older-than format should be like '30d', '2w', or '3m'", file=sys.stderr)
                sys.exit(1)
            num, unit = int(match.group(1)), match.group(2)
            days = num * {'d': 1, 'w': 7, 'm': 30}[unit]
            cutoff = datetime.now() - timedelta(days=days)
        else:
            cutoff = datetime.fromisoformat(args.created_before + "T23:59:59")

        tasks = [t for t in tasks if get_created(t) < cutoff]

    # Enrich tasks with comments and assignee names
    enriched = []
    for t in tasks:
        task_dict = to_dict(t)
        # Resolve assignee_id to human-readable name
        aid = task_dict.get('assignee_id')
        task_dict['assignee_name'] = assignee_map.get(aid) if aid else None
        comments = collect_paginated(api.get_comments(task_id=t.id))
        task_dict['comments'] = [to_dict(c) for c in comments]
        enriched.append(task_dict)

    # Optionally include section names (requires extra API call)
    if args.include_section_name:
        if not project_id:
            print("Warning: --include-section-name requires --project to work, ignoring", file=sys.stderr)
        else:
            sections = {s.id: s.name for s in collect_paginated(api.get_sections(project_id=project_id))}
            for task_dict in enriched:
                sid = task_dict.get('section_id')
                task_dict['section_name'] = sections.get(sid) if sid else None

    print(json.dumps(enriched, indent=2, default=str))


def cmd_get_task(args):
    """Get a single task with comments."""
    api = get_api()
    try:
        task = api.get_task(args.id)
    except Exception as e:
        handle_task_not_found(e, args.id)
    task_dict = to_dict(task)
    # Resolve assignee name if task is in a shared project
    aid = task_dict.get('assignee_id')
    if aid:
        collabs = collect_paginated(api.get_collaborators(task.project_id))
        assignee_map = {c.id: c.name for c in collabs}
        task_dict['assignee_name'] = assignee_map.get(aid)
    else:
        task_dict['assignee_name'] = None
    comments = collect_paginated(api.get_comments(task_id=args.id))
    task_dict['comments'] = [to_dict(c) for c in comments]
    print(json.dumps(task_dict, indent=2, default=str))


def cmd_filter_tasks(args):
    """Filter tasks using Todoist filter syntax."""
    api = get_api()
    tasks = collect_paginated(api.filter_tasks(query=args.query))
    output_json(tasks)


def cmd_complete_task(args):
    """Complete a task."""
    api = get_api()
    try:
        success = api.complete_task(args.id)
    except Exception as e:
        handle_task_not_found(e, args.id)
    print(json.dumps({"success": success, "task_id": args.id}))


def cmd_delete_task(args):
    """Delete a task (works on completed tasks too)."""
    api = get_api()
    try:
        success = api.delete_task(args.id)
    except Exception as e:
        handle_task_not_found(e, args.id)
    print(json.dumps({"success": success, "task_id": args.id}))


def cmd_uncomplete_task(args):
    """Uncomplete/reopen a task."""
    api = get_api()
    try:
        success = api.uncomplete_task(args.id)
    except Exception as e:
        handle_task_not_found(e, args.id)
    print(json.dumps({"success": success, "task_id": args.id}))


def cmd_get_completed(args):
    """List completed tasks."""
    api = get_api()

    # Parse dates
    if args.since:
        since = datetime.fromisoformat(args.since)
    else:
        since = datetime.now() - timedelta(days=7)  # Default: last 7 days

    if args.until:
        until = datetime.fromisoformat(args.until)
    else:
        until = datetime.now()

    # Build filter query if project specified
    filter_query = None
    if args.project:
        filter_query = f"#{args.project}"

    try:
        completed = list(api.get_completed_tasks_by_completion_date(
            since=since,
            until=until,
            filter_query=filter_query
        ))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Flatten batches
    all_tasks = []
    for batch in completed:
        all_tasks.extend(batch)

    output_json(all_tasks)


def cmd_add_task(args):
    """Create a new task."""
    api = get_api()

    # Resolve project name to ID if provided
    project_id = args.project_id
    if args.project:
        project_id = resolve_project(api, args.project)

    # Resolve section name to ID if provided
    section_id = args.section_id
    if args.section:
        if not project_id:
            print("Error: --section requires --project or --project-id", file=sys.stderr)
            sys.exit(1)
        section_id = resolve_section(api, project_id, args.section)

    labels = args.labels.split(",") if args.labels else None

    task = api.add_task(
        content=args.content,
        description=args.description,
        project_id=project_id,
        section_id=section_id,
        parent_id=args.parent_id,
        labels=labels,
        priority=args.priority,
        due_string=args.due
    )
    output_json(task)


def cmd_update_task(args):
    """Update an existing task."""
    api = get_api()

    # Resolve project name to ID if provided
    project_id = args.project_id
    if args.project:
        project_id = resolve_project(api, args.project)

    # --no-section: move to the project root. The API has no "clear section"
    # field — the only way out of a section is a move targeting project_id.
    if args.no_section:
        if args.section or args.section_id:
            print("Error: --no-section cannot be combined with --section/--section-id", file=sys.stderr)
            sys.exit(1)
        if not project_id:
            # Staying in the current project, just leaving the section
            try:
                task = api.get_task(args.id)
            except Exception as e:
                handle_task_not_found(e, args.id)
            project_id = task.project_id

    # Resolve section name to ID if provided
    section_id = args.section_id
    if args.section:
        # Need a project context to resolve section name
        if project_id:
            # Moving to new project - resolve section in target project
            resolve_project_id = project_id
        else:
            # Not moving - resolve section in task's current project
            try:
                task = api.get_task(args.id)
            except Exception as e:
                handle_task_not_found(e, args.id)
            resolve_project_id = task.project_id
        section_id = resolve_section(api, resolve_project_id, args.section)

    # Resolve assignee name to ID if provided
    assignee_id = None
    if args.assignee:
        # Get task's project to look up collaborators
        try:
            task = api.get_task(args.id)
        except Exception as e:
            handle_task_not_found(e, args.id)
        collabs = collect_paginated(api.get_collaborators(task.project_id))
        match = [c for c in collabs if c.name.lower() == args.assignee.lower()]
        if not match:
            # Try partial match
            match = [c for c in collabs if args.assignee.lower() in c.name.lower()]
        if not match:
            names = [c.name for c in collabs]
            print(f"Error: No collaborator matching '{args.assignee}'. Available: {', '.join(names)}", file=sys.stderr)
            sys.exit(1)
        assignee_id = match[0].id

    # Separate update fields from move fields
    # update_task() handles: content, description, labels, priority, due, assignee_id
    # move_task() handles: project_id, section_id, parent_id
    update_kwargs = {}
    if args.content:
        update_kwargs['content'] = args.content
    if args.description is not None:
        update_kwargs['description'] = args.description
    if args.priority:
        update_kwargs['priority'] = args.priority
    if args.due:
        update_kwargs['due_string'] = args.due
    if args.labels:
        update_kwargs['labels'] = args.labels.split(",")
    if assignee_id is not None:
        update_kwargs['assignee_id'] = assignee_id
    # Order goes in update_kwargs, which runs AFTER any move — a move resets
    # the task's order to 1, so setting it in the same call would be undone.
    if args.order is not None:
        update_kwargs['order'] = args.order

    move_kwargs = {}
    if project_id:
        move_kwargs['project_id'] = project_id
    if section_id:
        move_kwargs['section_id'] = section_id

    if not update_kwargs and not move_kwargs:
        print("Error: No update parameters provided", file=sys.stderr)
        sys.exit(1)

    # Perform move first (if needed), then update
    if move_kwargs:
        try:
            api.move_task(args.id, **move_kwargs)
        except Exception as e:
            error_str = str(e).lower()
            if "404" in error_str or "not found" in error_str:
                print(f"Error: Task '{args.id}' not found", file=sys.stderr)
                sys.exit(1)
            if "429" in str(e) or "rate limit" in error_str:
                print("Error: Rate limited by Todoist. Wait a moment and retry.", file=sys.stderr)
                sys.exit(1)
            if "400" in str(e):
                # Try to give specific error messages for common 400 causes
                if "workspace" in error_str or "project_id" in error_str:
                    print("Error: Cannot move task between workspaces (personal ↔ team).", file=sys.stderr)
                    print("Workaround: Complete the task and recreate it in the target project.", file=sys.stderr)
                else:
                    # Unknown 400 error - show the actual message
                    print(f"Error: Move failed - {e}", file=sys.stderr)
                sys.exit(1)
            raise

    if update_kwargs:
        try:
            api.update_task(args.id, **update_kwargs)
        except Exception as e:
            handle_task_not_found(e, args.id)

    # Fetch and show the updated task
    try:
        task = api.get_task(args.id)
    except Exception as e:
        handle_task_not_found(e, args.id)
    output_json(task)


def cmd_reorder(args):
    """Set task order to the sequence given (first = position 1)."""
    api = get_api()

    results = []
    for position, task_id in enumerate(args.ids, start=1):
        try:
            api_call_with_retry(api.update_task, task_id, order=position)
        except Exception as e:
            # Report what landed before the failure, then the standard error
            if results:
                print(f"Reordered {len(results)} of {len(args.ids)} tasks before the failure:", file=sys.stderr)
                for r in results:
                    print(f"  {r['order']}. {r['task_id']}", file=sys.stderr)
            handle_task_not_found(e, task_id)
        results.append({"task_id": task_id, "order": position})

    print(json.dumps({"success": True, "reordered": results}, indent=2))


def cmd_add_section(args):
    """Create a new section."""
    api = get_api()

    # Resolve project name to ID if provided
    project_id = args.project_id
    if args.project:
        project_id = resolve_project(api, args.project)

    if not project_id:
        print("Error: --project-id or --project is required for add-section", file=sys.stderr)
        sys.exit(1)

    section = api.add_section(
        name=args.name,
        project_id=project_id
    )
    output_json(section)


def cmd_get_comments(args):
    """Get comments for a task or project."""
    api = get_api()

    if not args.task_id and not args.project_id:
        print("Error: --task-id or --project-id is required", file=sys.stderr)
        sys.exit(1)

    comments = collect_paginated(api.get_comments(
        task_id=args.task_id,
        project_id=args.project_id
    ))
    output_json(comments)


def cmd_get_collaborators(args):
    """Get collaborators for a project."""
    api = get_api()

    if not args.project_id:
        print("Error: --project-id is required", file=sys.stderr)
        sys.exit(1)

    collaborators = collect_paginated(api.get_collaborators(args.project_id))
    output_json(collaborators)


def cmd_auth(args):
    """Authenticate with Todoist."""
    from accomplis.auth import get_auth_status, store_api_token, print_setup_instructions

    if args.status:
        status = get_auth_status()
        print(status["message"])
        sys.exit(0 if status["authenticated"] else 1)

    if args.token:
        success = store_api_token(args.token)
        sys.exit(0 if success else 1)

    # No flags: print setup instructions
    print_setup_instructions()


def cmd_doctor(args):
    """Check CLI setup and diagnose issues."""
    import os
    import shutil
    from pathlib import Path

    checks_passed = 0
    checks_failed = 0

    def check(name: str, passed: bool, detail: str = ""):
        nonlocal checks_passed, checks_failed
        if passed:
            checks_passed += 1
            print(f"  ✓ {name}")
        else:
            checks_failed += 1
            print(f"  ✗ {name}")
            if detail:
                print(f"    → {detail}")

    print("Checking accomplis setup...\n")

    # Python version (pyproject.toml requires-python is the enforcement point)
    print("[Python]")
    py_version = sys.version_info
    check(
        f"Python {py_version.major}.{py_version.minor}.{py_version.micro}",
        py_version >= (3, 11),
        "Requires Python 3.11+" if py_version < (3, 11) else ""
    )

    # Dependencies
    print("\n[Dependencies]")
    for pkg in ["todoist_api_python", "httpx"]:
        try:
            __import__(pkg)
            check(pkg, True)
        except ImportError:
            check(pkg, False, f"pip install {pkg.replace('_', '-')}")

    # Installation
    print("\n[Installation]")
    accomplis_shim = shutil.which("accomplis")
    check(
        "accomplis on PATH",
        accomplis_shim is not None,
        "Run: uv tool install <path-to-clone>  (or 'accomplis @ git+https://github.com/spm1001/accomplis')" if not accomplis_shim else ""
    )
    if accomplis_shim:
        check(
            f"installed at {accomplis_shim}",
            True,
        )

    # Auth
    print("\n[Authentication]")
    from accomplis.auth import get_auth_status
    status = get_auth_status()
    check(
        "Todoist authenticated",
        status["authenticated"],
        status["message"] if not status["authenticated"] else ""
    )

    # Network (only if auth passed)
    if status["authenticated"]:
        print("\n[Network]")
        try:
            api = get_api()
            next(iter(api.get_projects()), None)  # First page only
            check("API connection", True)
        except Exception as e:
            check("API connection", False, str(e)[:60])

    # Summary
    print(f"\n{'─' * 40}")
    total = checks_passed + checks_failed
    if checks_failed == 0:
        print(f"All {total} checks passed. Setup looks good!")
    else:
        print(f"{checks_passed}/{total} checks passed, {checks_failed} failed.")
        sys.exit(1)


def cmd_add_project(args):
    """Create a new project."""
    api = get_api()

    kwargs = {"name": args.name}
    if args.parent:
        kwargs["parent_id"] = resolve_project(api, args.parent)
    if args.color:
        kwargs["color"] = args.color
    if args.favorite:
        kwargs["is_favorite"] = True

    project = api.add_project(**kwargs)
    output_json(project)


def cmd_update_project(args):
    """Rename an existing project."""
    api = get_api()

    project_id = resolve_project(api, args.project)

    kwargs = {}
    if args.name:
        kwargs["name"] = args.name
    if args.color:
        kwargs["color"] = args.color
    if args.favorite is not None:
        kwargs["is_favorite"] = args.favorite

    if not kwargs:
        print("Error: No update parameters provided (use --name, --color, or --favorite)", file=sys.stderr)
        sys.exit(1)

    project = api.update_project(project_id, **kwargs)
    output_json(project)


def cmd_whoami(args):
    """Show the current authenticated user."""
    user = get_current_user()
    if args.json:
        print(json.dumps(user, indent=2, default=str))
    else:
        print(f"{user['full_name']} <{user['email']}> (id: {user['id']})")


def cmd_version(args):
    """Show version and commit info."""
    from importlib.metadata import version as pkg_version, PackageNotFoundError

    # Get package version
    try:
        ver = pkg_version("accomplis")
    except PackageNotFoundError:
        ver = "dev"

    print(f"accomplis {ver}")
    print(f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")


def main():
    from importlib.metadata import version as pkg_version
    parser = argparse.ArgumentParser(
        description="Todoist CLI - MCP-free interface using official Python SDK",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--version', '-V', action='version',
                        version=f'accomplis {pkg_version("accomplis")}')
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Auth command
    p = subparsers.add_parser("auth", help="Authenticate with Todoist")
    p.add_argument("--token", help="API token to store (get from Todoist settings)")
    p.add_argument("--status", action="store_true", help="Check authentication status")

    # Natural command names (primary)
    subparsers.add_parser("projects", help="List all projects")

    p = subparsers.add_parser("sections", help="List sections")
    p.add_argument("--project-id", help="Filter by project ID")
    p.add_argument("--project", help="Filter by project name (e.g., 'Desired Outcomes Q4')")

    p = subparsers.add_parser("tasks", help="List tasks")
    p.add_argument("--project-id", help="Filter by project ID")
    p.add_argument("--project", help="Filter by project name (e.g., '@Wait')")
    p.add_argument("--section-id", help="Filter by section ID")
    p.add_argument("--section", help="Filter by section name (requires --project)")
    p.add_argument("--label", help="Filter by label")
    p.add_argument("--assignee", help="Filter by assignee name (requires --project or --project-id)")
    p.add_argument("--created-before", help="Filter by creation date (YYYY-MM-DD)")
    p.add_argument("--older-than", help="Filter by age (e.g., '30d', '2w', '3m')")
    p.add_argument("--team", action="store_true", help="Show all team members' tasks (default: only yours on workspace projects)")
    p.add_argument("--unassigned", action="store_true", help="Show unassigned tasks for triage (workspace projects only)")
    p.add_argument("--include-section-name", action="store_true", help="Include section name in output")

    p = subparsers.add_parser("task", help="Get a single task")
    p.add_argument("id", help="Task ID")

    p = subparsers.add_parser("filter", help="Filter tasks using Todoist filter syntax")
    p.add_argument("query", help="Filter query (e.g., 'today', 'overdue', '#project')")

    p = subparsers.add_parser("done", help="Complete a task")
    p.add_argument("id", help="Task ID")

    p = subparsers.add_parser("delete", help="Delete a task (works on completed tasks too)")
    p.add_argument("id", help="Task ID")

    p = subparsers.add_parser("uncomplete", help="Uncomplete/reopen a task")
    p.add_argument("id", help="Task ID")

    p = subparsers.add_parser("completed", help="List completed tasks")
    p.add_argument("--since", help="Start date (YYYY-MM-DD), default: 7 days ago")
    p.add_argument("--until", help="End date (YYYY-MM-DD), default: now")
    p.add_argument("--project", help="Filter by project name")

    p = subparsers.add_parser("add", help="Create a new task")
    p.add_argument("content", help="Task content/title")
    p.add_argument("--description", help="Task description")
    p.add_argument("--project-id", help="Project ID")
    p.add_argument("--project", help="Project by name (e.g., '@Work', 'Someday/Maybe')")
    p.add_argument("--section-id", help="Section ID")
    p.add_argument("--section", help="Section by name (e.g., 'Now') - requires --project")
    p.add_argument("--parent-id", help="Parent task ID (for subtasks)")
    p.add_argument("--labels", help="Comma-separated labels")
    p.add_argument("--priority", type=int, choices=[1, 2, 3, 4], help="Priority (1=normal, 4=urgent)")
    p.add_argument("--due", help="Due date in natural language")

    p = subparsers.add_parser("update", help="Update an existing task")
    p.add_argument("id", help="Task ID")
    p.add_argument("--content", help="New task content/title")
    p.add_argument("--description", help="New description (use '' to clear)")
    p.add_argument("--project-id", help="Move to project ID")
    p.add_argument("--project", help="Move to project by name (e.g., '@Ping')")
    p.add_argument("--section-id", help="Move to section ID")
    p.add_argument("--section", help="Move to section by name (e.g., 'Now')")
    p.add_argument("--no-section", action="store_true", help="Move task out of its section to the project root")
    p.add_argument("--order", type=int, help="Position among siblings (1 = top). Applied after any move (moves reset order to 1)")
    p.add_argument("--labels", help="New comma-separated labels (replaces existing)")
    p.add_argument("--priority", type=int, choices=[1, 2, 3, 4], help="Priority (1=normal, 4=urgent)")
    p.add_argument("--assignee", help="Reassign to collaborator by name")
    p.add_argument("--due", help="Due date in natural language")

    p = subparsers.add_parser("reorder", help="Set task order to the sequence given (first = top)")
    p.add_argument("ids", nargs="+", help="Task IDs in desired order. Unlisted siblings keep their old order and may interleave — list every task in the section for a full arrangement")

    p = subparsers.add_parser("comments", help="Get comments")
    p.add_argument("--task-id", help="Task ID")
    p.add_argument("--project-id", help="Project ID")

    p = subparsers.add_parser("collaborators", help="Get project collaborators")
    p.add_argument("--project-id", required=True, help="Project ID")

    p = subparsers.add_parser("add-project", help="Create a new project")
    p.add_argument("name", help="Project name")
    p.add_argument("--parent", help="Parent project name or ID (for nested projects)")
    p.add_argument("--color", help="Project color (e.g., 'berry_red', 'blue', 'green')")
    p.add_argument("--favorite", action="store_true", help="Mark as favorite")

    p = subparsers.add_parser("update-project", help="Update a project (rename, recolor, etc.)")
    p.add_argument("project", help="Project name or ID to update")
    p.add_argument("--name", help="New project name")
    p.add_argument("--color", help="New project color")
    p.add_argument("--favorite", action=argparse.BooleanOptionalAction, help="Set/unset favorite")

    p = subparsers.add_parser("add-section", help="Create a new section (outcome)")
    p.add_argument("name", help="Section name")
    p.add_argument("--project-id", help="Project ID")
    p.add_argument("--project", help="Project by name (e.g., 'Desired Outcomes Q1')")

    # Utility commands
    p = subparsers.add_parser("whoami", help="Show current authenticated user")
    p.add_argument("--json", action="store_true", help="Output full user object as JSON")

    subparsers.add_parser("doctor", help="Check CLI setup and diagnose issues")
    subparsers.add_parser("version", help="Show version and commit info")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Dispatch to command handler
    commands = {
        "auth": cmd_auth,
        "projects": cmd_get_projects,
        "sections": cmd_get_sections,
        "tasks": cmd_get_tasks,
        "task": cmd_get_task,
        "filter": cmd_filter_tasks,
        "done": cmd_complete_task,
        "delete": cmd_delete_task,
        "uncomplete": cmd_uncomplete_task,
        "completed": cmd_get_completed,
        "add": cmd_add_task,
        "update": cmd_update_task,
        "reorder": cmd_reorder,
        "add-project": cmd_add_project,
        "update-project": cmd_update_project,
        "add-section": cmd_add_section,
        "comments": cmd_get_comments,
        "collaborators": cmd_get_collaborators,
        "whoami": cmd_whoami,
        "doctor": cmd_doctor,
        "version": cmd_version,
    }

    handler = commands.get(args.command)
    if handler:
        try:
            handler(args)
        except Exception as e:
            # Catch network errors globally
            error_name = type(e).__name__
            error_str = str(e).lower()

            # Timeout errors
            if "timeout" in error_name.lower() or "timeout" in error_str:
                print(f"Error: Request timed out after {DEFAULT_TIMEOUT}s", file=sys.stderr)
                print("Check your network connection or try again.", file=sys.stderr)
                sys.exit(1)

            # Connection errors
            if "connect" in error_name.lower() or "connection" in error_str:
                print("Error: Could not connect to Todoist", file=sys.stderr)
                print("Check your network connection.", file=sys.stderr)
                sys.exit(1)

            # Token expired/revoked (401 Unauthorized)
            if "401" in str(e) or "unauthorized" in error_str:
                print("Error: Token expired or revoked.", file=sys.stderr)
                print("Run 'accomplis auth' to re-authenticate.", file=sys.stderr)
                sys.exit(1)

            # Re-raise unknown errors
            raise
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
