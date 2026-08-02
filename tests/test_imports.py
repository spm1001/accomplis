"""Smoke tests: every module imports and every entry point resolves.

todoist-flatten shipped broken for four months (2026-03-30 to 2026-08-02)
because a rename in common.py left flatten.py importing a function that no
longer existed — and nothing imported flatten at test time. These tests make
that class of breakage impossible to ship silently.
"""

import importlib
from importlib.metadata import entry_points

import pytest

MODULES = [
    "todoist_gtd.auth",
    "todoist_gtd.cli",
    "todoist_gtd.common",
    "todoist_gtd.flatten",
    "todoist_gtd.token_store",
]


@pytest.mark.parametrize("module", MODULES)
def test_module_imports(module):
    importlib.import_module(module)


def test_entry_points_resolve():
    """The functions pyproject.toml names as console scripts must exist."""
    from todoist_gtd import cli, flatten

    assert callable(cli.main)
    assert callable(flatten.main)
