"""Integration tests for TmuxBackend against real tmux."""

import time

import pytest

from agentdeck.sessions.tmux_backend import TmuxBackend

SESSION_PREFIX = "test-mcs-"


@pytest.fixture()
def backend():
    """Real TmuxBackend with cleanup of all test sessions."""
    b = TmuxBackend(pane_width=80, pane_height=24)
    yield b
    # Kill any test sessions left behind
    for name in b.list_sessions():
        if name.startswith(SESSION_PREFIX):
            b.kill_session(name)


@pytest.fixture()
def session(backend):
    """Create a bash session and return its name."""
    name = f"{SESSION_PREFIX}{int(time.time())}"
    backend.create_session(name, "bash")
    time.sleep(0.3)  # let bash start
    return name


def test_create_and_list(backend):
    name = f"{SESSION_PREFIX}create"
    backend.create_session(name, "bash")
    assert name in backend.list_sessions()


def test_send_keys_and_capture(backend, session):
    """Send a command and verify it appears in captured output."""
    backend.send_keys(session, "echo HELLO_TMUX", enter=True)
    time.sleep(0.3)
    output = backend.capture_pane(session)
    assert "HELLO_TMUX" in output


def test_kill_session(backend, session):
    assert backend.is_alive(session) is True
    backend.kill_session(session)
    assert backend.is_alive(session) is False


def test_kill_missing_session_is_silent(backend):
    """Killing a non-existent session should not raise."""
    backend.kill_session(f"{SESSION_PREFIX}nonexistent")


def test_send_keys_missing_session_raises(backend):
    with pytest.raises(ValueError, match="Session not found"):
        backend.send_keys(f"{SESSION_PREFIX}missing", "hello")


def test_capture_scrollback(backend, session):
    """Scrollback captures full history, not just visible pane."""
    backend.send_keys(session, "echo SCROLLBACK_TEST", enter=True)
    time.sleep(0.3)
    lines = backend.capture_scrollback(session)
    assert isinstance(lines, list)
    assert any("SCROLLBACK_TEST" in line for line in lines)


def test_get_history_size(backend, session):
    """history_size grows as output scrolls above the pane."""
    initial = backend.get_history_size(session)
    # Generate enough output to push lines into scrollback
    for i in range(30):
        backend.send_keys(session, f"echo line{i}", enter=True)
    time.sleep(0.5)
    after = backend.get_history_size(session)
    assert after > initial


def test_get_history_size_missing_session(backend):
    """Missing session returns 0."""
    assert backend.get_history_size(f"{SESSION_PREFIX}gone") == 0


def test_is_process_dead_alive(backend, session):
    """Running session reports process alive."""
    assert backend.is_process_dead(session) is False


def test_is_process_dead_after_exit(backend):
    """Exited process is detected as dead (remain-on-exit)."""
    name = f"{SESSION_PREFIX}die-{int(time.time())}"
    backend.create_session(name, "sleep 0.2")
    time.sleep(1)  # wait for sleep to finish
    assert backend.is_process_dead(name) is True


def test_is_process_dead_missing_session(backend):
    """Missing session returns False."""
    assert backend.is_process_dead(f"{SESSION_PREFIX}gone") is False
