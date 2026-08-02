#!/usr/bin/env python3
"""
Flatten subtasks into parent task descriptions.

Converts parent-subtask relationships to flat tasks where subtask content
becomes lines in the parent's description field. Subtasks are completed
(not deleted) to preserve history.

Safety features:
- Dry-run by default (--execute to apply)
- Backup to JSON before changes (--no-backup to skip)
- Restore from backup (--restore)
- Detects nested subtasks and aborts
- Checks description length limits
- Rate limit handling with retry

Usage:
    todoist-flatten "Project Name"              # Dry-run
    todoist-flatten "Project Name" --execute    # Apply changes (creates backup)
    todoist-flatten --restore path/to/backup.json  # Restore from backup
"""

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from todoist_gtd.common import (
    get_api,
    collect_paginated,
    to_dict,
    resolve_project_object,
    api_call_with_retry,
    RATE_LIMIT_DELAY,
)

DESCRIPTION_MAX_LENGTH = 16383  # Todoist's limit


def build_description(parent_desc: str, subtasks: list[dict]) -> str:
    """Build new description with subtasks appended as bullet list."""
    lines = []

    # Keep existing description if any
    if parent_desc and parent_desc.strip():
        lines.append(parent_desc.strip())
        lines.append("")  # Blank line before bullets

    # Sort subtasks by order field
    sorted_subtasks = sorted(subtasks, key=lambda t: t.get('order', 0))

    for st in sorted_subtasks:
        content = st.get('content', '').strip()
        desc = st.get('description', '').strip()

        lines.append(f"- {content}")
        if desc:
            # Indent description under the bullet
            for desc_line in desc.split('\n'):
                lines.append(f"  {desc_line}")

    return '\n'.join(lines)


def check_for_nested_subtasks(subtasks_by_parent: dict, tasks_dict: dict) -> list[str]:
    """
    Check if any subtasks themselves have subtasks (nested).
    Returns list of error messages for any nested subtasks found.
    """
    errors = []
    all_subtask_ids = set()
    for subtasks in subtasks_by_parent.values():
        for st in subtasks:
            all_subtask_ids.add(st.get('id'))

    # Check if any subtask is also a parent
    for subtask_id in all_subtask_ids:
        if subtask_id in subtasks_by_parent:
            subtask = tasks_dict.get(subtask_id, {})
            content = subtask.get('content', subtask_id)
            grandchildren = subtasks_by_parent[subtask_id]
            errors.append(
                f"'{content}' is a subtask but has {len(grandchildren)} "
                f"subtask(s) of its own"
            )

    return errors


def check_description_lengths(parents_with_subtasks: dict, tasks_dict: dict) -> list[str]:
    """
    Check if any new descriptions would exceed Todoist's limit.
    Returns list of error messages for any that would exceed.
    """
    errors = []
    for parent_id, subtasks in parents_with_subtasks.items():
        parent = tasks_dict[parent_id]
        current_desc = parent.get('description', '') or ''
        new_desc = build_description(current_desc, subtasks)

        if len(new_desc) > DESCRIPTION_MAX_LENGTH:
            content = parent.get('content', parent_id)
            errors.append(
                f"'{content}' would have {len(new_desc):,} chars "
                f"(limit is {DESCRIPTION_MAX_LENGTH:,})"
            )

    return errors


def save_backup(project_name: str, tasks_dict: dict,
                parents_with_subtasks: dict) -> Path:
    """
    Save backup of current state to JSON file.
    Returns path to backup file.
    """
    # Create backup directory
    backup_dir = Path.home() / ".claude" / "backups" / "todoist"
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Generate filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_name = project_name.replace(" ", "-").replace("/", "-")
    backup_file = backup_dir / f"flatten-{safe_name}-{timestamp}.json"

    # Build backup data
    backup_data = {
        "timestamp": datetime.now().isoformat(),
        "project_name": project_name,
        "operation": "flatten-subtasks",
        "parents": {},
    }

    for parent_id, subtasks in parents_with_subtasks.items():
        parent = tasks_dict[parent_id]
        backup_data["parents"][parent_id] = {
            "task": parent,
            "subtasks": subtasks,
        }

    # Write backup
    backup_file.write_text(json.dumps(backup_data, indent=2, default=str))

    return backup_file


def list_backups() -> list[Path]:
    """List available backup files, newest first."""
    backup_dir = Path.home() / ".claude" / "backups" / "todoist"
    if not backup_dir.exists():
        return []
    return sorted(backup_dir.glob("flatten-*.json"), reverse=True)


def cmd_restore(backup_path: str, execute: bool):
    """Restore from a backup file."""
    backup_file = Path(backup_path).expanduser()

    if not backup_file.exists():
        print(f"Error: Backup file not found: {backup_file}", file=sys.stderr)
        sys.exit(1)

    # Load backup
    try:
        backup_data = json.loads(backup_file.read_text())
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in backup file: {e}", file=sys.stderr)
        sys.exit(1)

    project_name = backup_data.get("project_name", "Unknown")
    timestamp = backup_data.get("timestamp", "Unknown")
    parents = backup_data.get("parents", {})

    if not parents:
        print("Error: No parent tasks found in backup", file=sys.stderr)
        sys.exit(1)

    print(f"Backup from: {timestamp}")
    print(f"Project: {project_name}")
    print(f"Contains: {len(parents)} parent task(s)\n")

    # Count subtasks
    total_subtasks = sum(len(p.get("subtasks", [])) for p in parents.values())

    print("=" * 50)
    print("RESTORE PLAN")
    print("=" * 50)
    print()

    # Part 1: Description restoration (automatable)
    print("PART 1: Restore parent descriptions (automatic)")
    print("-" * 50)
    for parent_id, data in parents.items():
        task = data.get("task", {})
        content = task.get("content", parent_id)
        original_desc = task.get("description", "") or "(empty)"
        desc_preview = original_desc[:80] + "..." if len(original_desc) > 80 else original_desc
        print(f"  • {content}")
        print(f"    → Restore to: {desc_preview}")
    print()

    # Part 2: Subtask restoration (manual)
    print("PART 2: Restore subtasks (MANUAL - Todoist UI required)")
    print("-" * 50)
    print(f"  {total_subtasks} subtask(s) need manual restoration.")
    print()
    print("  Steps:")
    print("  1. Open Todoist → Filters & Labels → Completed")
    print("  2. Find and restore each subtask listed below")
    print("  3. After restoring, drag each subtask under its parent")
    print()

    for parent_id, data in parents.items():
        task = data.get("task", {})
        parent_content = task.get("content", parent_id)
        subtasks = data.get("subtasks", [])

        if subtasks:
            print(f"  Under '{parent_content}':")
            for st in sorted(subtasks, key=lambda t: t.get("order", 0)):
                st_content = st.get("content", "")
                print(f"    [ ] {st_content}")
            print()

    if not execute:
        print("=" * 50)
        print("Run with --execute to restore descriptions automatically.")
        print("Subtasks must be restored manually in Todoist UI.")
        return

    # Execute description restoration
    print("=" * 50)
    print("Restoring descriptions...")
    print()

    api = get_api()
    success_count = 0
    failure_count = 0

    for parent_id, data in parents.items():
        task = data.get("task", {})
        content = task.get("content", parent_id)
        original_desc = task.get("description", "") or ""

        try:
            api_call_with_retry(api.update_task, parent_id, description=original_desc)
            print(f"  ✓ Restored: {content}")
            success_count += 1
        except Exception as e:
            error_str = str(e).lower()
            if "404" in str(e) or "not found" in error_str:
                print(f"  ✗ Task not found (deleted?): {content}", file=sys.stderr)
            else:
                print(f"  ✗ Failed to restore '{content}': {e}", file=sys.stderr)
            failure_count += 1

    print()
    print("=" * 50)
    print(f"Descriptions restored: {success_count}/{len(parents)}")
    if failure_count:
        print(f"Failures: {failure_count}")

    print()
    print("NEXT STEPS:")
    print("  Manually restore subtasks in Todoist UI using the checklist above.")


def cmd_list_backups():
    """List available backup files."""
    backups = list_backups()
    if not backups:
        print("No backup files found in ~/.claude/backups/todoist/")
        return

    print("Available backups (newest first):")
    print()
    for backup in backups[:10]:  # Show last 10
        try:
            data = json.loads(backup.read_text())
            timestamp = data.get("timestamp", "Unknown")[:19]
            project = data.get("project_name", "Unknown")
            num_parents = len(data.get("parents", {}))
            print(f"  {backup.name}")
            print(f"    Project: {project} | Parents: {num_parents} | Time: {timestamp}")
        except Exception:
            print(f"  {backup.name} (could not read)")
        print()

    if len(backups) > 10:
        print(f"  ... and {len(backups) - 10} more")
    print()
    print(f"Backup directory: ~/.claude/backups/todoist/")


def cmd_flatten(args):
    """Main flatten operation."""
    api = get_api()

    # Resolve project (by ID or name)
    if args.project_id:
        project_id = args.project_id
        # Fetch project name for display
        projects = collect_paginated(api.get_projects())
        project_name = next((p.name for p in projects if p.id == project_id), project_id)
    else:
        project = resolve_project_object(api, args.project)
        project_id, project_name = project.id, project.name

    # Fetch all tasks in project
    print(f"Fetching tasks from '{project_name}'...")
    tasks = collect_paginated(api.get_tasks(project_id=project_id))
    tasks_dict = {t.id: to_dict(t) for t in tasks}

    # Group subtasks by parent_id
    subtasks_by_parent = defaultdict(list)
    for task in tasks:
        parent_id = getattr(task, 'parent_id', None)
        if parent_id:
            subtasks_by_parent[parent_id].append(to_dict(task))

    # Find parents that have subtasks
    parents_with_subtasks = {
        task_id: subtasks
        for task_id, subtasks in subtasks_by_parent.items()
        if task_id in tasks_dict
    }

    if not parents_with_subtasks:
        print("No parent tasks with subtasks found.")
        return

    total_subtasks = sum(len(subs) for subs in parents_with_subtasks.values())
    print(f"Found {len(parents_with_subtasks)} parent tasks with "
          f"{total_subtasks} subtasks total\n")

    # === Safety checks ===

    # Check for nested subtasks
    nested_errors = check_for_nested_subtasks(subtasks_by_parent, tasks_dict)
    if nested_errors:
        print("ERROR: Nested subtasks detected (subtasks that have their own subtasks):",
              file=sys.stderr)
        for err in nested_errors:
            print(f"  • {err}", file=sys.stderr)
        print("\nFlatten the deepest level first, or manually reorganize.",
              file=sys.stderr)
        sys.exit(1)

    # Check description lengths
    length_errors = check_description_lengths(parents_with_subtasks, tasks_dict)
    if length_errors:
        print("ERROR: Some descriptions would exceed Todoist's limit:",
              file=sys.stderr)
        for err in length_errors:
            print(f"  • {err}", file=sys.stderr)
        print("\nConsider splitting these tasks or shortening subtask descriptions.",
              file=sys.stderr)
        sys.exit(1)

    # === Show what would change ===

    for parent_id, subtasks in parents_with_subtasks.items():
        parent = tasks_dict[parent_id]
        parent_content = parent.get('content', '')
        current_desc = parent.get('description', '') or ''

        new_desc = build_description(current_desc, subtasks)

        print(f"=== {parent_content} ===")
        if current_desc:
            # Truncate long descriptions for display
            desc_preview = current_desc[:100] + '...' if len(current_desc) > 100 else current_desc
            print(f"Current description: {desc_preview}")
        else:
            print("Current description: (empty)")
        print(f"Would append {len(subtasks)} subtask(s):")
        # Show just the subtasks portion
        for st in sorted(subtasks, key=lambda t: t.get('order', 0)):
            content = st.get('content', '').strip()
            desc = st.get('description', '').strip()
            print(f"  - {content}")
            if desc:
                # Truncate long descriptions for display
                desc_preview = desc[:60] + '...' if len(desc) > 60 else desc
                print(f"    {desc_preview}")
        print(f"New description length: {len(new_desc):,} chars")
        print()

    if not args.execute:
        print("─" * 50)
        action = "DELETED (permanent)" if args.delete_subtasks else "completed"
        print(f"Subtasks will be: {action}")
        print("Run with --execute to apply changes")
        return

    # === Execute changes ===

    # Save backup first
    if not args.no_backup:
        backup_file = save_backup(project_name, tasks_dict, parents_with_subtasks)
        print(f"Backup saved to: {backup_file}\n")

    print("Applying changes...\n")

    success_count = 0
    failure_count = 0

    for parent_id, subtasks in parents_with_subtasks.items():
        parent = tasks_dict[parent_id]
        parent_content = parent.get('content', '')
        current_desc = parent.get('description', '') or ''
        new_desc = build_description(current_desc, subtasks)

        print(f"Processing: {parent_content}")

        # Update parent description
        try:
            api_call_with_retry(api.update_task, parent_id, description=new_desc)
            print(f"  ✓ Updated description")
        except Exception as e:
            print(f"  ✗ Failed to update description: {e}", file=sys.stderr)
            failure_count += 1
            continue

        # Complete or delete each subtask
        subtask_failures = 0
        action = "delete" if args.delete_subtasks else "complete"
        for st in subtasks:
            st_id = st.get('id')
            st_content = st.get('content', '')
            try:
                time.sleep(RATE_LIMIT_DELAY)
                if args.delete_subtasks:
                    api.delete_task(st_id)
                    print(f"  ✓ Deleted: {st_content[:50]}")
                else:
                    api.complete_task(st_id)
                    print(f"  ✓ Completed: {st_content[:50]}")
            except Exception as e:
                print(f"  ✗ Failed to {action} '{st_content}': {e}", file=sys.stderr)
                subtask_failures += 1

        if subtask_failures == 0:
            success_count += 1
        else:
            failure_count += 1
        print()

    # Summary
    print("─" * 50)
    print(f"Complete: {success_count} parent(s) fully processed")
    if failure_count:
        print(f"Failures: {failure_count} parent(s) had errors")
        if not args.no_backup:
            print(f"\nBackup available at: {backup_file}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Flatten subtasks into parent task descriptions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s "Desired Outcomes"              # Dry-run by name
    %(prog)s --project-id 2349012345         # Dry-run by ID (more robust)
    %(prog)s "Desired Outcomes" --execute    # Apply (subtasks completed)
    %(prog)s "Project" --execute --delete-subtasks  # Apply (subtasks deleted permanently)
    %(prog)s --restore path/to/backup.json   # Show restore plan
    %(prog)s --restore backup.json --execute # Restore descriptions
    %(prog)s --list-backups                  # List available backups

Backup files are saved to ~/.claude/backups/todoist/
Use --project-id when the project name might change between dry-run and execute.
Use --delete-subtasks for permanent removal (default: complete, which preserves history).
"""
    )
    parser.add_argument("project", nargs="?", help="Project name")
    parser.add_argument("--project-id", help="Project ID (more robust than name)")
    parser.add_argument("--execute", action="store_true",
                        help="Actually make changes (default is dry-run)")
    parser.add_argument("--no-backup", action="store_true",
                        help="Skip backup (not recommended)")
    parser.add_argument("--delete-subtasks", action="store_true",
                        help="Delete subtasks instead of completing them (permanent, no undo)")
    parser.add_argument("--restore", metavar="FILE",
                        help="Restore from backup file")
    parser.add_argument("--list-backups", action="store_true",
                        help="List available backup files")

    args = parser.parse_args()

    # Handle --list-backups
    if args.list_backups:
        cmd_list_backups()
        return

    # Handle --restore
    if args.restore:
        cmd_restore(args.restore, args.execute)
        return

    # Handle flatten (requires project name or ID)
    if not args.project and not args.project_id:
        parser.print_help()
        sys.exit(1)

    cmd_flatten(args)


if __name__ == "__main__":
    main()
