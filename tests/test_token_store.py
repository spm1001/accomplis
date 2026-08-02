"""Tests for token file storage and migration (tgt-kobale).

The plugin-data dir was renamed at the 2026-06-10 marketplace cutover
(todoist-gtd-batterie-de-savoir → todoist-gtd-batterie). _get_from_file()
must read the new location and migrate from both older ones.
"""

import pytest

from todoist_gtd import token_store


@pytest.fixture
def stores(tmp_path, monkeypatch):
    """Point all three token locations into tmp_path."""
    new = tmp_path / "data" / "todoist-gtd-batterie" / "token"
    old = tmp_path / "data" / "todoist-gtd-batterie-de-savoir" / "token"
    legacy = tmp_path / ".todoist-token"
    monkeypatch.setattr(token_store, "TOKEN_FILE", new)
    monkeypatch.setattr(token_store, "_OLD_PLUGIN_DATA_DIR", old.parent)
    monkeypatch.setattr(token_store, "_LEGACY_TOKEN_FILE", legacy)
    return new, old, legacy


def test_reads_current_location(stores):
    new, _, _ = stores
    new.parent.mkdir(parents=True)
    new.write_text("tok-current\n")
    assert token_store._get_from_file() == "tok-current"


def test_migrates_from_old_plugin_dir(stores):
    new, old, _ = stores
    old.parent.mkdir(parents=True)
    old.write_text("tok-old-dir\n")
    assert token_store._get_from_file() == "tok-old-dir"
    assert new.read_text().strip() == "tok-old-dir"
    assert (new.stat().st_mode & 0o777) == 0o600


def test_migrates_from_legacy_home_file(stores):
    new, _, legacy = stores
    legacy.write_text("tok-legacy\n")
    assert token_store._get_from_file() == "tok-legacy"
    assert new.read_text().strip() == "tok-legacy"


def test_old_plugin_dir_wins_over_legacy(stores):
    new, old, legacy = stores
    old.parent.mkdir(parents=True)
    old.write_text("tok-old-dir\n")
    legacy.write_text("tok-legacy\n")
    assert token_store._get_from_file() == "tok-old-dir"
    assert new.read_text().strip() == "tok-old-dir"


def test_no_sources_returns_none(stores):
    assert token_store._get_from_file() is None


def test_legacy_only_layout_no_selfmigration(stores, monkeypatch):
    """When TOKEN_FILE IS the legacy file (no plugin data dir), no migration loop."""
    _, _, legacy = stores
    monkeypatch.setattr(token_store, "TOKEN_FILE", legacy)
    legacy.write_text("tok-legacy\n")
    assert token_store._get_from_file() == "tok-legacy"
