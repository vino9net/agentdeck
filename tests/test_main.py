from pathlib import Path

from agentdeck.main import (
    _is_whitelisted_session_dir,
    _normalize_whitelist_dirs,
)


def test_whitelist_empty_allows_any_dir(tmp_path: Path) -> None:
    assert _is_whitelisted_session_dir(str(tmp_path), []) is True


def test_whitelist_allows_same_or_child_dir(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    child = allowed / "repo"
    child.mkdir(parents=True)

    whitelist = _normalize_whitelist_dirs([str(allowed)])

    assert _is_whitelisted_session_dir(str(allowed), whitelist) is True
    assert _is_whitelisted_session_dir(str(child), whitelist) is True


def test_whitelist_blocks_outside_dir(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    other = tmp_path / "other"
    allowed.mkdir()
    other.mkdir()

    whitelist = _normalize_whitelist_dirs([str(allowed)])

    assert _is_whitelisted_session_dir(str(other), whitelist) is False


def test_whitelist_blocks_missing_working_dir_when_enabled(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()

    whitelist = _normalize_whitelist_dirs([str(allowed)])

    assert _is_whitelisted_session_dir(None, whitelist) is False
