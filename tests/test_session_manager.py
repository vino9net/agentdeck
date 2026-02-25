"""Tests for SessionManager with mocked TmuxBackend."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agentdeck.sessions.agent_output_log import AgentOutputLog
from agentdeck.sessions.manager import (
    SessionManager,
)
from agentdeck.sessions.models import AgentType


@pytest.fixture()
def mock_tmux():
    tmux = MagicMock()
    tmux.create_session.return_value = "agent-test"
    tmux.is_alive.return_value = True
    tmux.capture_pane.return_value = "$ hello"
    return tmux


@pytest.fixture()
def output_log(tmp_path):
    log = AgentOutputLog(tmp_path / "test.db")
    yield log
    log.close()


@pytest.fixture()
def manager(mock_tmux, tmp_path):
    recent_dirs_path = tmp_path / "recent_dirs.txt"
    return SessionManager(
        tmux=mock_tmux,
        recent_dirs_path=recent_dirs_path,
    )


@pytest.fixture()
def manager_with_log(mock_tmux, tmp_path, output_log):
    recent_dirs_path = tmp_path / "recent_dirs.txt"
    return SessionManager(
        tmux=mock_tmux,
        recent_dirs_path=recent_dirs_path,
        output_log=output_log,
    )


@pytest.mark.asyncio
async def test_create_session(manager, tmp_path):
    info = await manager.create_session(
        working_dir=str(tmp_path),
        agent_type=AgentType.CLAUDE,
    )
    assert info.session_id == f"agent-claude-{tmp_path.name[:20].lower()}"
    assert info.working_dir == str(tmp_path)
    assert info.agent_type == AgentType.CLAUDE


@pytest.mark.asyncio
async def test_create_session_bad_dir(manager):
    with pytest.raises(ValueError, match="Directory not found"):
        await manager.create_session(working_dir="/nonexistent/path")


@pytest.mark.asyncio
async def test_create_session_same_dir_suffix(manager, tmp_path):
    first = await manager.create_session(str(tmp_path))
    second = await manager.create_session(str(tmp_path))
    assert first.session_id == f"agent-claude-{tmp_path.name[:20].lower()}"
    assert second.session_id == f"agent-claude-{tmp_path.name[:20].lower()}-2"


@pytest.mark.asyncio
async def test_send_input_text(manager, mock_tmux, tmp_path):
    info = await manager.create_session(str(tmp_path))
    await manager.send_input(info.session_id, "explain this")
    calls = mock_tmux.send_keys.call_args_list
    # Text sent without enter, then Enter sent separately
    text_call = calls[-2]
    assert text_call == (
        (info.session_id, "explain this"),
        {"enter": False, "literal": True},
    )
    enter_call = calls[-1]
    assert enter_call == (
        (info.session_id, "Enter"),
        {"enter": False},
    )


@pytest.mark.asyncio
async def test_send_input_shortcut(manager, mock_tmux, tmp_path):
    info = await manager.create_session(str(tmp_path))
    await manager.send_input(info.session_id, "stop")
    mock_tmux.send_keys.assert_called_with(info.session_id, "Escape", enter=False)


@pytest.mark.asyncio
async def test_capture_output(manager, mock_tmux, tmp_path):
    info = await manager.create_session(str(tmp_path))
    output = await manager.capture_output(info.session_id)
    assert output.content == "$ hello"
    assert output.changed is True

    # Second call with same content
    output2 = await manager.capture_output(info.session_id)
    assert output2.changed is False


@pytest.mark.asyncio
async def test_unknown_session_raises(manager):
    with pytest.raises(KeyError, match="Unknown"):
        await manager.send_input("fake-id", "hello")


def test_record_recent_dir_persists_to_text_file(tmp_path, mock_tmux):
    """Recent dirs are stored in a separate text file, not config.json."""
    recent_dirs_path = tmp_path / "recent_dirs.txt"
    recent_dirs_path.write_text("~/old\n")
    mgr = SessionManager(
        tmux=mock_tmux,
        recent_dirs_path=recent_dirs_path,
    )

    workdir = str(Path.home() / "repo")
    mgr._record_recent_dir(workdir)

    lines = recent_dirs_path.read_text().splitlines()
    assert lines[0] == "~/repo"
    assert lines[1] == "~/old"


SELECTION_OUTPUT = """\
  Which option?
  ❯ 1. Allow
    2. Deny
    3. Other

Enter to select · ↑/↓ to navigate · Esc to cancel"""


@pytest.mark.asyncio
async def test_send_selection_navigates_down(manager, mock_tmux, tmp_path):
    """Selecting item 2 when ❯ is on item 1 sends one Down + Enter."""
    mock_tmux.capture_pane.return_value = SELECTION_OUTPUT
    info = await manager.create_session(str(tmp_path))
    await manager.send_selection(info.session_id, 2)

    calls = mock_tmux.send_keys.call_args_list
    # Filter to calls after create_session
    arrow_calls = [c for c in calls if c[0][1] == "Down"]
    enter_calls = [c for c in calls if c[0][1] == "Enter"]
    assert len(arrow_calls) == 1
    assert len(enter_calls) == 1


@pytest.mark.asyncio
async def test_send_selection_navigates_up(manager, mock_tmux, tmp_path):
    """Selecting item 1 when ❯ is on item 2 sends one Up + Enter."""
    output_cursor_on_2 = """\
  Which option?
    1. Allow
  ❯ 2. Deny
    3. Other

Enter to select · ↑/↓ to navigate · Esc to cancel"""
    mock_tmux.capture_pane.return_value = output_cursor_on_2
    info = await manager.create_session(str(tmp_path))
    await manager.send_selection(info.session_id, 1)

    calls = mock_tmux.send_keys.call_args_list
    up_calls = [c for c in calls if c[0][1] == "Up"]
    enter_calls = [c for c in calls if c[0][1] == "Enter"]
    assert len(up_calls) == 1
    assert len(enter_calls) == 1


@pytest.mark.asyncio
async def test_send_selection_unknown_item(manager, mock_tmux, tmp_path):
    """Selecting a non-existent item raises ValueError."""
    mock_tmux.capture_pane.return_value = SELECTION_OUTPUT
    info = await manager.create_session(str(tmp_path))
    with pytest.raises(ValueError, match="not found"):
        await manager.send_selection(info.session_id, 99)


@pytest.mark.asyncio
async def test_send_selection_freeform(manager, mock_tmux, tmp_path):
    """Freeform selection sends Enter then text + Enter."""
    mock_tmux.capture_pane.return_value = SELECTION_OUTPUT
    info = await manager.create_session(str(tmp_path))
    await manager.send_selection(info.session_id, 3, freeform_text="custom answer")

    calls = mock_tmux.send_keys.call_args_list
    # Should have arrow keys (2 Downs), Enter, then literal text
    text_calls = [c for c in calls if len(c[0]) >= 2 and c[0][1] == "custom answer"]
    assert len(text_calls) == 1
    assert text_calls[0][1]["literal"] is True


@pytest.mark.asyncio
async def test_capture_to_log_appends_delta(
    manager_with_log, mock_tmux, output_log, tmp_path
):
    """First capture stores scrollback, second only new lines."""
    mock_tmux.is_process_dead.return_value = False
    mock_tmux.get_history_size.return_value = 2
    mock_tmux.capture_scrollback.return_value = [
        "line1",
        "line2",
        "visible1",
    ]
    info = await manager_with_log.create_session(str(tmp_path))
    await manager_with_log.capture_to_log(info.session_id)

    page = output_log.read(info.session_id)
    assert len(page.chunks) == 1
    assert page.chunks[0].content == "line1\nline2"

    # Scrollback grows
    mock_tmux.get_history_size.return_value = 4
    mock_tmux.capture_scrollback.return_value = [
        "line1",
        "line2",
        "line3",
        "line4",
        "visible2",
    ]
    await manager_with_log.capture_to_log(info.session_id)

    page = output_log.read(info.session_id)
    assert len(page.chunks) == 2
    assert page.chunks[1].content == "line3\nline4"


@pytest.mark.asyncio
async def test_capture_skips_when_history_size_unchanged(
    manager_with_log, mock_tmux, output_log, tmp_path
):
    """Stable history_size means capture_scrollback is never called."""
    mock_tmux.is_process_dead.return_value = False
    mock_tmux.get_history_size.return_value = 5
    mock_tmux.capture_scrollback.return_value = [
        "a",
        "b",
        "c",
        "d",
        "e",
        "visible",
    ]
    info = await manager_with_log.create_session(str(tmp_path))
    await manager_with_log.capture_to_log(info.session_id)

    mock_tmux.capture_scrollback.reset_mock()
    # Three more calls with same history_size
    for _ in range(3):
        await manager_with_log.capture_to_log(info.session_id)

    mock_tmux.capture_scrollback.assert_not_called()
    page = output_log.read(info.session_id)
    assert len(page.chunks) == 1


@pytest.mark.asyncio
async def test_capture_final_on_death(manager_with_log, mock_tmux, output_log, tmp_path):
    """Process death triggers full capture + cleanup."""
    mock_tmux.is_process_dead.return_value = False
    mock_tmux.get_history_size.return_value = 2
    mock_tmux.capture_scrollback.return_value = [
        "line1",
        "line2",
        "visible1",
    ]
    info = await manager_with_log.create_session(str(tmp_path))
    await manager_with_log.capture_to_log(info.session_id)

    # Process dies — final capture includes visible pane
    mock_tmux.is_process_dead.return_value = True
    mock_tmux.capture_scrollback.return_value = [
        "line1",
        "line2",
        "line3",
        "final-visible",
    ]
    await manager_with_log.capture_to_log(info.session_id)

    page = output_log.read(info.session_id)
    assert len(page.chunks) == 2
    assert page.chunks[1].content == "line3\nfinal-visible"

    # kill_session called to clean up tmux
    mock_tmux.kill_session.assert_called_once_with(info.session_id)

    # Session marked dead
    sessions = await manager_with_log.list_sessions()
    dead = [s for s in sessions if s.session_id == info.session_id]
    assert dead[0].is_alive is False


@pytest.mark.asyncio
async def test_capture_to_log_skipped_without_log(manager, mock_tmux, tmp_path):
    """No-op when AgentOutputLog is not configured."""
    mock_tmux.capture_scrollback.return_value = ["line1"]
    info = await manager.create_session(str(tmp_path))
    await manager.capture_to_log(info.session_id)
    mock_tmux.capture_scrollback.assert_not_called()


# --- Dead session tests ---


@pytest.mark.asyncio
async def test_kill_marks_dead(manager, mock_tmux, tmp_path):
    """Kill marks session dead with ended_at."""
    info = await manager.create_session(str(tmp_path))
    await manager.kill_session(info.session_id)

    sessions = await manager.list_sessions()
    dead = [s for s in sessions if s.session_id == info.session_id]
    assert len(dead) == 1
    assert dead[0].is_alive is False
    assert dead[0].ended_at is not None


@pytest.mark.asyncio
async def test_active_ids_excludes_dead(manager, mock_tmux, tmp_path):
    """Capture loop skips dead sessions."""
    info = await manager.create_session(str(tmp_path))
    await manager.kill_session(info.session_id)

    assert info.session_id not in manager.active_session_ids()


@pytest.mark.asyncio
async def test_send_input_dead_raises(manager, mock_tmux, tmp_path):
    """Sending input to a dead session raises ValueError."""
    info = await manager.create_session(str(tmp_path))
    await manager.kill_session(info.session_id)

    with pytest.raises(ValueError, match="Session ended"):
        await manager.send_input(info.session_id, "hello")


@pytest.mark.asyncio
async def test_list_detects_tmux_death(manager, mock_tmux, tmp_path):
    """list_sessions auto-marks sessions dead when tmux dies."""
    info = await manager.create_session(str(tmp_path))
    mock_tmux.is_alive.return_value = False

    sessions = await manager.list_sessions()
    found = [s for s in sessions if s.session_id == info.session_id]
    assert found[0].is_alive is False
    assert found[0].ended_at is not None
