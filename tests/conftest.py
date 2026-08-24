"""Shared fixtures for the accomplis test suite."""

import pytest


@pytest.fixture(autouse=True)
def _hermetic_invocation_log(tmp_path_factory, monkeypatch):
    """Point XDG_DATA_HOME at a temp dir so test runs never write test noise
    into the real ~/.local/share/accomplis/invocations.jsonl (the _invlog
    shim's output is analysis data — test invocations would poison the
    caller-stamp baseline). Tests that probe the log override XDG_DATA_HOME
    themselves."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path_factory.mktemp("xdg")))
