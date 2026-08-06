"""
Transport-level retry behaviour (tgt-radaji).

The known-positive control the bon brief demands: a stub that returns 503
twice then 200 must succeed, and a persistent 401 must fail on the FIRST
attempt — proving the retry is confined to transient statuses and a broken
token still fails loudly and fast.
"""

import httpx

from accomplis.common import MAX_RETRIES, make_retry_transport


def make_client(responses, calls, sleeps):
    """
    Client over a stub transport that serves canned (status, headers) pairs.

    The last pair repeats forever; every request is recorded in `calls` and
    every retry wait in `sleeps` (no real sleeping).
    """

    def handler(request):
        calls.append((request.method, request.url.path))
        status, headers = responses[min(len(calls) - 1, len(responses) - 1)]
        return httpx.Response(status, headers=headers)

    transport = make_retry_transport(
        inner=httpx.MockTransport(handler), sleep=sleeps.append
    )
    return httpx.Client(transport=transport)


def test_transient_503_recovers():
    calls, sleeps = [], []
    with make_client([(503, {}), (503, {}), (200, {})], calls, sleeps) as client:
        resp = client.get("https://api.todoist.com/api/v1/comments")
    assert resp.status_code == 200
    assert len(calls) == 3
    assert len(sleeps) == 2


def test_401_fails_on_first_attempt():
    calls, sleeps = [], []
    with make_client([(401, {})], calls, sleeps) as client:
        resp = client.get("https://api.todoist.com/api/v1/tasks")
    assert resp.status_code == 401
    assert len(calls) == 1
    assert sleeps == []


def test_post_not_replayed_on_502():
    calls, sleeps = [], []
    with make_client([(502, {})], calls, sleeps) as client:
        resp = client.post("https://api.todoist.com/api/v1/tasks", json={"content": "x"})
    assert resp.status_code == 502
    assert len(calls) == 1


def test_post_retries_on_503():
    # 503 is load shedding — rejected before processing, so replaying a POST
    # cannot double-create.
    calls, sleeps = [], []
    with make_client([(503, {}), (200, {})], calls, sleeps) as client:
        resp = client.post("https://api.todoist.com/api/v1/tasks", json={"content": "x"})
    assert resp.status_code == 200
    assert len(calls) == 2


def test_get_retries_on_502():
    calls, sleeps = [], []
    with make_client([(502, {}), (200, {})], calls, sleeps) as client:
        resp = client.get("https://api.todoist.com/api/v1/projects")
    assert resp.status_code == 200
    assert len(calls) == 2


def test_429_honours_retry_after():
    calls, sleeps = [], []
    with make_client([(429, {"Retry-After": "7"}), (200, {})], calls, sleeps) as client:
        resp = client.get("https://api.todoist.com/api/v1/tasks")
    assert resp.status_code == 200
    assert sleeps == [7.0]


def test_persistent_503_gives_up():
    calls, sleeps = [], []
    with make_client([(503, {})], calls, sleeps) as client:
        resp = client.get("https://api.todoist.com/api/v1/comments")
    assert resp.status_code == 503
    assert len(calls) == MAX_RETRIES + 1
