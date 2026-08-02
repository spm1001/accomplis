"""Smoke tests: every module imports and every entry point resolves.

The flatten entry point (then `todoist-flatten`) shipped broken for four
months (2026-03-30 to 2026-08-02) because a rename in common.py left
flatten.py importing a function that no longer existed — and nothing imported
flatten at test time. These tests make that class of breakage impossible to
ship silently.
"""

import importlib
from importlib.metadata import entry_points

import pytest

MODULES = [
    "accomplis.auth",
    "accomplis.cli",
    "accomplis.common",
    "accomplis.flatten",
    "accomplis.token_store",
]


@pytest.mark.parametrize("module", MODULES)
def test_module_imports(module):
    importlib.import_module(module)


def test_entry_points_resolve():
    """The functions pyproject.toml names as console scripts must exist."""
    from accomplis import cli, flatten

    assert callable(cli.main)
    assert callable(flatten.main)
