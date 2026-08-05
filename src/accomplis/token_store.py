#!/usr/bin/env python3
"""
Portable secrets management for the accomplis CLI (Todoist API token).

Supports multiple backends:
1. Environment variable (TODOIST_API_KEY) - works everywhere
2. macOS Keychain - native Mac support
3. File-based fallback (plugin data dir, or ~/.todoist-token legacy) - last resort

The env var and Keychain service keep their todoist-* names deliberately:
they identify the SERVICE credential, not the tool, and renaming them would
force a pointless credential migration on every machine.

Usage:
    from accomplis.token_store import get_token, store_token

    token = get_token()  # Returns token or exits with error
    store_token(token)   # Stores using best available backend
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

KEYCHAIN_SERVICE = "todoist-api-key"

# Plugin data directory — version-stable, survives plugin cache upgrades.
# Claude Code creates ~/.claude/plugins/data/{name}-{marketplace}/ automatically.
_PLUGIN_DATA_DIR = Path.home() / ".claude" / "plugins" / "data" / "accomplis-batterie"
# Older names, newest first — each rung kept only as a migration source:
# pre-rename plugin name (to 2026-08-02), then pre-cutover marketplace name
# (to 2026-06-10).
_OLD_PLUGIN_DATA_DIRS = (
    Path.home() / ".claude" / "plugins" / "data" / "todoist-gtd-batterie",
    Path.home() / ".claude" / "plugins" / "data" / "todoist-gtd-batterie-de-savoir",
)
_LEGACY_TOKEN_FILE = Path.home() / ".todoist-token"

# Prefer plugin data dir (version-stable) over legacy home file.
TOKEN_FILE = (
    _PLUGIN_DATA_DIR / "token"
    if _PLUGIN_DATA_DIR.is_dir()
    else _LEGACY_TOKEN_FILE
)


def _has_keychain() -> bool:
    """Check if macOS Keychain is available."""
    return shutil.which("security") is not None


def _get_from_env() -> Optional[str]:
    """Get token from environment variable."""
    return os.environ.get("TODOIST_API_KEY")


def _get_from_keychain() -> Optional[str]:
    """Get token from macOS Keychain."""
    if not _has_keychain():
        return None
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-a", os.environ.get("USER", ""), "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        # Item not found is expected, return None silently
        if e.returncode == 44:  # errSecItemNotFound
            return None
        # Surface other errors to help user diagnose
        stderr = e.stderr.strip() if e.stderr else ""
        if "locked" in stderr.lower() or e.returncode == 51:  # errSecInteractionNotAllowed
            print("Warning: Keychain is locked. Unlock it or use TODOIST_API_KEY env var.", file=sys.stderr)
        elif "denied" in stderr.lower() or e.returncode == 36:  # errSecAuthFailed
            print("Warning: Keychain access denied. Check System Preferences > Privacy.", file=sys.stderr)
        else:
            print(f"Warning: Keychain read failed (code {e.returncode})", file=sys.stderr)
        return None


def _get_from_file() -> Optional[str]:
    """Get token from file, migrating from older locations if needed."""
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    if TOKEN_FILE == _LEGACY_TOKEN_FILE:
        return None
    # Migrate on first read: older plugin-data dirs newest-first, then the
    # legacy home file. Originals are left in place (cheap, and another
    # machine's older install may still read them).
    for old in (*(d / "token" for d in _OLD_PLUGIN_DATA_DIRS), _LEGACY_TOKEN_FILE):
        if old.exists():
            token = old.read_text().strip()
            if token:
                TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
                TOKEN_FILE.write_text(token + "\n")
                TOKEN_FILE.chmod(0o600)
                return token
    return None


def _store_to_keychain(token: str) -> bool:
    """Store token in macOS Keychain."""
    if not _has_keychain():
        return False
    user = os.environ.get("USER", "")
    try:
        # Delete existing entry (ignore errors)
        subprocess.run(
            ["security", "delete-generic-password", "-a", user, "-s", KEYCHAIN_SERVICE],
            capture_output=True, check=False
        )
        # Add new entry
        # Note: Token appears in process list briefly. macOS security command doesn't
        # support stdin for -w flag. Acceptable for local CLI (same-user visibility only).
        # For stricter environments, consider using Python's keyring library.
        subprocess.run(
            ["security", "add-generic-password", "-a", user, "-s", KEYCHAIN_SERVICE, "-w", token],
            check=True, capture_output=True
        )
        return True
    except subprocess.CalledProcessError as e:
        # Surface specific errors to help user diagnose
        stderr = e.stderr.strip() if e.stderr else ""
        if "locked" in stderr.lower() or e.returncode == 51:
            print("Warning: Keychain is locked. Unlock it to store token.", file=sys.stderr)
        elif "denied" in stderr.lower() or e.returncode == 36:
            print("Warning: Keychain access denied. Check System Preferences > Privacy.", file=sys.stderr)
        elif "duplicate" in stderr.lower() or e.returncode == 45:  # errSecDuplicateItem
            print("Warning: Could not update Keychain entry (duplicate conflict).", file=sys.stderr)
        else:
            print(f"Warning: Keychain write failed (code {e.returncode})", file=sys.stderr)
        return False


def _store_to_file(token: str) -> bool:
    """Store token in file with restricted permissions."""
    try:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(token + "\n")
        TOKEN_FILE.chmod(0o600)
        return True
    except OSError:
        return False


def get_token() -> str:
    """
    Get Todoist API token from available backends.

    Tries in order: env var -> Keychain -> file
    Exits with error if no token found.
    """
    # 1. Environment variable (works everywhere)
    token = _get_from_env()
    if token:
        return token

    # 2. macOS Keychain
    token = _get_from_keychain()
    if token:
        return token

    # 3. File fallback
    token = _get_from_file()
    if token:
        return token

    # No token found — name every location actually consulted, as RESOLVED
    # absolute paths with existence per rung. A diagnostic that names locations
    # must name resolved paths, never templates: '~' is a lie in any non-login
    # context, and a tilde in an error message is how a present credential gets
    # reported as absent (tgt-zanute — a token sitting in another HOME's
    # ~/.todoist-token was reported as 'not found' with three irrelevant
    # suggestions, and a day's Todoist reach was written off).
    env_val = os.environ.get("TODOIST_API_KEY")
    checked = [
        "$TODOIST_API_KEY environment variable — "
        + ("set but empty" if env_val is not None else "unset")
    ]
    user = os.environ.get("USER", "")
    if _has_keychain():
        checked.append(
            f"macOS Keychain service '{KEYCHAIN_SERVICE}' (account '{user}') — no entry"
        )
    # Mirror _get_from_file: TOKEN_FILE always; migration sources only when
    # TOKEN_FILE is the plugin data dir
    file_rungs = [TOKEN_FILE]
    if TOKEN_FILE != _LEGACY_TOKEN_FILE:
        file_rungs += [d / "token" for d in _OLD_PLUGIN_DATA_DIRS]
        file_rungs.append(_LEGACY_TOKEN_FILE)
    for p in file_rungs:
        state = "exists but empty" if p.exists() else "missing"
        checked.append(f"{p} — {state}")

    print("Error: no Todoist API token found. Checked, in order:", file=sys.stderr)
    for i, line in enumerate(checked, 1):
        print(f"  {i}. {line}", file=sys.stderr)
    print(f"\n(HOME={Path.home()}, USER={user or '<unset>'})", file=sys.stderr)
    print("\nFix: `accomplis auth` for setup instructions, or", file=sys.stderr)
    print("`accomplis auth --token TOKEN` to store one.", file=sys.stderr)
    sys.exit(1)


def get_token_quiet() -> Optional[str]:
    """Get token without exiting on failure. Returns None if not found."""
    return _get_from_env() or _get_from_keychain() or _get_from_file()


def store_token(token: str) -> bool:
    """
    Store token using best available backend.

    On macOS: uses Keychain
    On Linux: uses file with 600 permissions
    """
    if _has_keychain():
        if _store_to_keychain(token):
            print("  Token stored in macOS Keychain.", file=sys.stderr)
            return True
        print("  Warning: Keychain storage failed, falling back to file.", file=sys.stderr)

    if _store_to_file(token):
        print(f"  Token stored in {TOKEN_FILE} (mode 600).", file=sys.stderr)
        return True

    print("  Error: Could not store token.", file=sys.stderr)
    return False
