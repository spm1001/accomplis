#!/usr/bin/env python3
"""
Todoist authentication module.

Stores API tokens portably: env var, macOS Keychain, or file (~/.todoist-token).

Usage:
    from accomplis.auth import get_auth_status

    # Check current status
    status = get_auth_status()

CLI:
    accomplis auth --token TOKEN   # Store a personal API token
    accomplis auth --status        # Check authentication status
    accomplis auth                 # Print setup instructions
"""

import sys

from accomplis.token_store import get_token_quiet, store_token

TODOIST_TOKEN_URL = "https://app.todoist.com/app/settings/integrations/developer"


def store_api_token(token: str) -> bool:
    """
    Validate and store a Todoist API token.

    Returns True on success, False on failure.
    """
    if not token:
        print("No token provided.", file=sys.stderr)
        return False

    # Quick validation: Todoist API tokens are 40-char hex strings
    if len(token) != 40 or not all(c in "0123456789abcdef" for c in token):
        print("Warning: Token doesn't look like a Todoist API token (expected 40 hex chars).", file=sys.stderr)
        print("Storing anyway -- accomplis doctor will verify it works.\n", file=sys.stderr)

    if not store_token(token):
        return False

    print("Token stored. Run `accomplis doctor` to verify.")
    return True


def get_auth_status() -> dict:
    """
    Check current authentication status.

    Returns dict with:
        - authenticated: bool
        - message: str describing status
    """
    token = get_token_quiet()

    if not token:
        return {
            "authenticated": False,
            "message": "Not authenticated. Run `accomplis auth --token TOKEN` to set up."
        }

    # Try to verify token works by making a simple API call
    try:
        from todoist_api_python.api import TodoistAPI
        api = TodoistAPI(token)
        # This will fail if token is revoked (first page is enough to verify)
        next(iter(api.get_projects()), None)
        return {
            "authenticated": True,
            "message": "Authenticated with Todoist."
        }
    except Exception as e:
        error_str = str(e).lower()
        if "401" in error_str or "unauthorized" in error_str:
            return {
                "authenticated": False,
                "message": "Token revoked or expired. Run `accomplis auth --token TOKEN` to re-authenticate."
            }
        # Network error or other issue - assume still authenticated
        return {
            "authenticated": True,
            "message": f"Token present (could not verify: {e})"
        }


def print_setup_instructions():
    """Print instructions for obtaining and storing an API token."""
    print("Todoist Authentication")
    print("=" * 40)
    print()
    print("1. Go to your Todoist developer settings:")
    print(f"   {TODOIST_TOKEN_URL}")
    print()
    print("2. Scroll to the bottom and copy your API token.")
    print()
    print("3. Run:")
    print("   accomplis auth --token YOUR_TOKEN_HERE")
    print()
    print("The token will be stored in macOS Keychain (if available)")
    print("or in a file with restricted permissions.")


def main():
    """CLI entry point for standalone testing."""
    import argparse

    parser = argparse.ArgumentParser(description="Todoist authentication")
    parser.add_argument("--token", help="API token to store (get from Todoist settings)")
    parser.add_argument("--status", action="store_true", help="Check authentication status")

    args = parser.parse_args()

    if args.status:
        status = get_auth_status()
        print(status["message"])
        sys.exit(0 if status["authenticated"] else 1)

    if args.token:
        success = store_api_token(args.token)
        sys.exit(0 if success else 1)

    # No flags: print instructions
    print_setup_instructions()


if __name__ == "__main__":
    main()
