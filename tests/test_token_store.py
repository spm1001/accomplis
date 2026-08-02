"""Tests for token file storage and migration (tgt-kobale, extended for the rename).

The plugin-data dir has moved twice: at the 2026-06-10 marketplace cutover
(todoist-gtd-batterie-de-savoir → todoist-gtd-batterie) and at the 2026-08-02
plugin rename (todoist-gtd-batterie → accomplis-batterie). _get_from_file()
must read the current location and migrate from all three older ones,
newest-first.
"""

import pytest

from accomplis import token_store


@pytest.fixture
def stores(tmp_path, monkeypatch):
    """Point all four token locations into tmp_path."""
    new = tmp_path / "data" / "accomplis-batterie" / "token"
    old_rename = tmp_path / "data" / "todoist-gtd-batterie" / "token"
    old_cutover = tmp_path / "data" / "todoist-gtd-batterie-de-savoir" / "token"
    legacy = tmp_path / ".todoist-token"
    monkeypatch.setattr(token_store, "TOKEN_FILE", new)
    monkeypatch.setattr(
        token_store, "_OLD_PLUGIN_DATA_DIRS", (old_rename.parent, old_cutover.parent)
    )
    monkeypatch.setattr(token_store, "_LEGACY_TOKEN_FILE", legacy)
    return new, old_rename, old_cutover, legacy


def test_reads_current_location(stores):
    new, _, _, _ = stores
    new.parent.mkdir(parents=True)
    new.write_text("tok-current\n")
    assert token_store._get_from_file() == "tok-current"


def test_migrates_from_pre_rename_dir(stores):
    new, old_rename, _, _ = stores
    old_rename.parent.mkdir(parents=True)
    old_rename.write_text("tok-pre-rename\n")
    assert token_store._get_from_file() == "tok-pre-rename"
    assert new.read_text().strip() == "tok-pre-rename"
    assert (new.stat().st_mode & 0o777) == 0o600


def test_migrates_from_pre_cutover_dir(stores):
    new, _, old_cutover, _ = stores
    old_cutover.parent.mkdir(parents=True)
    old_cutover.write_text("tok-pre-cutover\n")
    assert token_store._get_from_file() == "tok-pre-cutover"
    assert new.read_text().strip() == "tok-pre-cutover"


def test_migrates_from_legacy_home_file(stores):
    new, _, _, legacy = stores
    legacy.write_text("tok-legacy\n")
    assert token_store._get_from_file() == "tok-legacy"
    assert new.read_text().strip() == "tok-legacy"


def test_ladder_order_newest_source_wins(stores):
    """When several rungs hold tokens, the newest one wins."""
    new, old_rename, old_cutover, legacy = stores
    old_rename.parent.mkdir(parents=True)
    old_rename.write_text("tok-pre-rename\n")
    old_cutover.parent.mkdir(parents=True)
    old_cutover.write_text("tok-pre-cutover\n")
    legacy.write_text("tok-legacy\n")
    assert token_store._get_from_file() == "tok-pre-rename"
    assert new.read_text().strip() == "tok-pre-rename"


def test_no_sources_returns_none(stores):
    assert token_store._get_from_file() is None


def test_legacy_only_layout_no_selfmigration(stores, monkeypatch):
    """When TOKEN_FILE IS the legacy file (no plugin data dir), no migration loop."""
    _, _, _, legacy = stores
    monkeypatch.setattr(token_store, "TOKEN_FILE", legacy)
    legacy.write_text("tok-legacy\n")
    assert token_store._get_from_file() == "tok-legacy"
