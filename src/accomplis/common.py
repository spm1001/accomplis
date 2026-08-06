"""
Shared utilities for Todoist CLI tools.

Provides common functions used across cli.py and flatten.py:
- API client with timeout and retry
- Pagination helpers
- Project/section resolution
- Object serialization
"""

import sys
import time
from typing import Any, Callable

# Lazy imports to allow --help without SDK installed
TodoistAPI = None

# Configuration
DEFAULT_TIMEOUT = 30  # seconds
RATE_LIMIT_DELAY = 0.2  # seconds between API calls
RATE_LIMIT_RETRY_DELAY = 5  # seconds to wait after 429
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.0  # seconds; doubles per retry, plus jitter
RETRY_AFTER_CAP = 30  # seconds; ceiling on server-requested Retry-After waits

# Which (method, status) pairs are safe to replay. 429 and 503 mean the request
# was rejected before processing (rate limit / load shedding), so any method can
# retry. 500/502/504 can arrive after the origin processed the request — a
# replayed POST there could double-create a task — so only idempotent methods
# retry on those.
_RETRY_ANY_METHOD = {429, 503}
_RETRY_IDEMPOTENT_ONLY = {500, 502, 504}
_IDEMPOTENT_METHODS = {"GET", "HEAD", "OPTIONS", "PUT", "DELETE"}


def _should_retry(method: str, status: int) -> bool:
    if status in _RETRY_ANY_METHOD:
        return True
    return status in _RETRY_IDEMPOTENT_ONLY and method.upper() in _IDEMPOTENT_METHODS


def _retry_wait(retry_after: str | None, backoff: float) -> float:
    """Server-directed wait when Retry-After is present (capped), else backoff+jitter."""
    import random

    if retry_after:
        try:
            return min(float(retry_after), RETRY_AFTER_CAP)
        except ValueError:
            pass  # HTTP-date form or garbage — fall back to backoff
    return backoff + random.uniform(0, backoff / 2)


def make_retry_transport(inner=None, sleep=time.sleep):
    """
    httpx transport that retries transient Todoist failures (tgt-radaji).

    httpx.HTTPTransport(retries=N) only retries CONNECTION errors; an HTTP 503
    sails straight through to raise_for_status() in the SDK. This wraps it with
    status-code retries: MAX_RETRIES attempts after the first, exponential
    backoff with jitter, honouring Retry-After. 4xx (bar 429) never retries —
    a 401 must fail loudly and fast.

    `inner` and `sleep` are injectable for tests (stub transport, no real waits).
    """
    import httpx

    class _RetryTransport(httpx.BaseTransport):
        def __init__(self):
            self._inner = inner or httpx.HTTPTransport(retries=MAX_RETRIES)

        def handle_request(self, request):
            request.read()  # materialise the body so a replay resends it
            backoff = RETRY_BACKOFF_BASE
            for attempt in range(MAX_RETRIES + 1):
                response = self._inner.handle_request(request)
                if attempt == MAX_RETRIES or not _should_retry(
                    request.method, response.status_code
                ):
                    return response
                wait = _retry_wait(response.headers.get("Retry-After"), backoff)
                response.close()
                print(
                    f"  ⏳ Todoist {response.status_code} on {request.method} "
                    f"{request.url.path} — retry {attempt + 1}/{MAX_RETRIES} "
                    f"in {wait:.1f}s",
                    file=sys.stderr,
                )
                sleep(wait)
                backoff *= 2
            return response  # unreachable; loop always returns

        def close(self):
            self._inner.close()

    return _RetryTransport()


def _build_client():
    """httpx.Client with timeout, connection retries, and transient-status retries."""
    import httpx

    return httpx.Client(timeout=DEFAULT_TIMEOUT, transport=make_retry_transport())


def get_api():
    """
    Get authenticated TodoistAPI instance with timeout and retry.

    todoist-api-python v4 switched from requests to httpx internally.
    We pass an httpx.Client with timeout and retry transport.
    """
    global TodoistAPI
    if TodoistAPI is None:
        try:
            from todoist_api_python.api import TodoistAPI as API
            TodoistAPI = API
        except ImportError:
            print("Error: todoist-api-python not installed", file=sys.stderr)
            print("\nInstall with: pip install todoist-api-python", file=sys.stderr)
            sys.exit(1)

    from accomplis.token_store import get_token

    token = get_token()
    return TodoistAPI(token, client=_build_client())


def get_current_user() -> dict:
    """
    Get the current authenticated user from Todoist REST API v1.

    Calls GET /api/v1/user directly (not wrapped by the SDK).
    Returns dict with id, full_name, email, and other user fields.
    """
    from accomplis.token_store import get_token

    token = get_token()
    with _build_client() as client:
        resp = client.get(
            "https://api.todoist.com/api/v1/user",
            headers={"Authorization": f"Bearer {token}"},
        )
    resp.raise_for_status()
    return resp.json()


def collect_paginated(iterator) -> list:
    """Collect all items from a paginated SDK iterator."""
    items = []
    for batch in iterator:
        items.extend(batch)
    return items


def to_dict(obj: Any) -> dict:
    """Convert SDK object to dict for JSON output."""
    if hasattr(obj, 'to_dict'):
        return obj.to_dict()
    if hasattr(obj, '__dict__'):
        return {k: v for k, v in obj.__dict__.items() if not k.startswith('_')}
    return obj


def resolve_project(api, name_or_id: str) -> str:
    """
    Resolve a project name to ID.

    Returns project ID string. Exits with error if not found.
    """
    projects = collect_paginated(api.get_projects())
    name_lower = name_or_id.lower()

    # Try name lookup
    for p in projects:
        if p.name.lower() == name_lower:
            return p.id

    # Try ID lookup
    for p in projects:
        if p.id == name_or_id:
            return p.id

    # Not found - show available projects
    available = sorted([p.name for p in projects])
    print(f"Error: Project '{name_or_id}' not found", file=sys.stderr)
    print(f"Available projects: {', '.join(available[:10])}", file=sys.stderr)
    if len(available) > 10:
        print(f"  ...and {len(available) - 10} more", file=sys.stderr)
    print("\n⚠️  STOP: Load the accomplis skill before using this CLI!", file=sys.stderr)
    sys.exit(1)


def resolve_project_object(api, name_or_id: str):
    """
    Resolve a project name or ID to the full Project object.

    Returns the SDK Project object. Exits with error if not found.
    """
    projects = collect_paginated(api.get_projects())
    name_lower = name_or_id.lower()

    for p in projects:
        if p.name.lower() == name_lower:
            return p

    for p in projects:
        if p.id == name_or_id:
            return p

    print(f"Error: Project '{name_or_id}' not found", file=sys.stderr)
    sys.exit(1)


def resolve_section(api, project_id: str, name_or_id: str) -> str:
    """
    Resolve a section name to ID within a project.

    Returns section ID string. Exits with error if not found.
    """
    sections = collect_paginated(api.get_sections(project_id=project_id))
    name_lower = name_or_id.lower()

    # Try name lookup
    for s in sections:
        if s.name.lower() == name_lower:
            return s.id

    # Try ID lookup
    for s in sections:
        if s.id == name_or_id:
            return s.id

    # Not found - show available sections
    available = [s.name for s in sections]
    print(f"Error: Section '{name_or_id}' not found in project", file=sys.stderr)
    if available:
        print(f"Available sections: {', '.join(available)}", file=sys.stderr)
    else:
        print("This project has no sections.", file=sys.stderr)
    print("\n⚠️  STOP: Load the accomplis skill before using this CLI!", file=sys.stderr)
    sys.exit(1)


def resolve_assignee(api, project_id: str, name_email_or_id: str) -> str:
    """Resolve an assignee to a user ID.

    Accepts a name (exact, then unique substring), an email, or the numeric id
    that `accomplis collaborators` emits — the tool's own output must round-trip
    into its own filter (tgt-husule).
    """
    collaborators = collect_paginated(api.get_collaborators(project_id))
    needle = name_email_or_id.lower()

    for c in collaborators:
        if (c.name.lower() == needle
                or c.email.lower() == needle
                or str(c.id) == name_email_or_id):
            return c.id

    partial = [c for c in collaborators if needle in c.name.lower()]
    if len(partial) == 1:
        return partial[0].id
    if len(partial) > 1:
        names = ", ".join(c.name for c in partial)
        print(f"Error: '{name_email_or_id}' matches several collaborators: {names}",
              file=sys.stderr)
        sys.exit(1)

    available = ", ".join(f"{c.name} <{c.email}> ({c.id})" for c in collaborators)
    print(f"Error: Collaborator '{name_email_or_id}' not found in project.",
          file=sys.stderr)
    print(f"Accepts name, email, or id. Available: {available or 'none — project has no collaborators'}",
          file=sys.stderr)
    sys.exit(1)


def api_call_with_retry(func: Callable, *args, **kwargs) -> Any:
    """
    Execute API call with rate limit handling and retry.

    Adds a small delay before each call to avoid hitting rate limits,
    and retries on 429 errors.
    """
    for attempt in range(MAX_RETRIES):
        try:
            time.sleep(RATE_LIMIT_DELAY)
            return func(*args, **kwargs)
        except Exception as e:
            error_str = str(e).lower()
            if "429" in str(e) or "rate limit" in error_str:
                if attempt < MAX_RETRIES - 1:
                    print(f"  ⏳ Rate limited, waiting {RATE_LIMIT_RETRY_DELAY}s...",
                          file=sys.stderr)
                    time.sleep(RATE_LIMIT_RETRY_DELAY)
                    continue
            raise
    raise Exception("Max retries exceeded")


def handle_task_not_found(e: Exception, task_id: str):
    """Handle task not found errors with clean message."""
    error_str = str(e).lower()
    # Todoist returns 400 for invalid IDs, 404 for valid-format but missing
    if "404" in error_str or "not found" in error_str or "400" in error_str:
        print(f"Error: Task '{task_id}' not found or invalid", file=sys.stderr)
        sys.exit(1)
    # Re-raise if it's a different error
    raise
