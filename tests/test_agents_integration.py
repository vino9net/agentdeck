"""Integration tests for real agent sessions (Claude, Codex).

These tests require:
- A real tmux server running
- The agent CLI installed and authenticated

Run with: uv run pytest -m integration -v
"""

import asyncio
import random
import shutil
import string
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from agentdeck.main import app, lifespan
from agentdeck.sessions.manager import SessionManager
from agentdeck.sessions.models import AgentType, ParsedOutput, UIState
from agentdeck.sessions.tmux_backend import TmuxBackend

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration

_TEST_SESSION_PREFIX = "agent-"
_SELECTION_PROMPT = "ask me a question about tmux and let me select answer"


async def _wait_for_state(
    mgr: SessionManager,
    session_id: str,
    target: UIState,
    *,
    retries: int = 15,
    interval: float = 2.0,
) -> ParsedOutput:
    """Poll until the session enters the target UI state."""
    parsed = None
    for _ in range(retries):
        output = await mgr.capture_output(session_id)
        parsed = mgr.parse_output(output.content)
        if parsed.state == target:
            return parsed
        await asyncio.sleep(interval)
    assert parsed is not None
    msg = f"Expected {target.value}, got {parsed.state.value}"
    raise AssertionError(msg)


async def _handle_startup_prompt(mgr: SessionManager, session_id: str) -> None:
    """Accept the agent's startup trust/approval prompt if shown.

    Claude shows a "trust this folder" selection.
    Codex shows an "approval mode" selection.
    In both cases, pick the first option to proceed.
    """
    output = await mgr.capture_output(session_id)
    parsed = mgr.parse_output(output.content)
    if parsed.state != UIState.SELECTION:
        return
    if parsed.items:
        await mgr.send_selection(session_id, parsed.items[0].number)
        await asyncio.sleep(2)


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture()
def tmux_backend():
    """Shared TmuxBackend with teardown that kills test sessions."""
    tmux = TmuxBackend(pane_width=120, pane_height=40)
    yield tmux
    for name in tmux.list_sessions():
        if name.startswith(_TEST_SESSION_PREFIX):
            tmux.kill_session(name)


@pytest.fixture()
def test_dir():
    """Create a temporary test directory, deleted after test."""
    project_root = Path(__file__).parent.parent
    tmp_dir = project_root / "tmp"
    tmp_dir.mkdir(exist_ok=True)

    suffix = "".join(random.choices(string.ascii_lowercase, k=3))
    path = tmp_dir / f"agent-test-{suffix}"
    path.mkdir(exist_ok=True)
    yield path
    if path.exists():
        shutil.rmtree(path)


@pytest.fixture()
def manager(tmux_backend, test_dir):
    """Create a real SessionManager."""
    recent_path = test_dir / "recent_dirs.txt"
    return SessionManager(tmux=tmux_backend, recent_dirs_path=recent_path)


# ── Lifecycle tests ──────────────────────────────────────


@pytest.mark.asyncio
async def test_claude_session_lifecycle(manager, test_dir):
    """Full lifecycle: create, select, confirm selection, kill."""
    # 1. Create session and wait for startup
    info = await manager.create_session(working_dir=str(test_dir))
    sid = info.session_id
    await asyncio.sleep(3)

    # 2. Handle trust folder prompt if shown
    await _handle_startup_prompt(manager, sid)

    # 3. Wait for prompt
    await _wait_for_state(manager, sid, UIState.PROMPT, retries=5, interval=1)

    # 4. Trigger a selection
    await manager.send_input(sid, _SELECTION_PROMPT)
    parsed = await _wait_for_state(manager, sid, UIState.SELECTION)

    assert len(parsed.items) > 1
    assert parsed.arrow_navigable is True

    # 5. Select option 2 → should return to prompt
    await manager.send_selection(sid, 2)
    await _wait_for_state(manager, sid, UIState.PROMPT)

    # 6. Verify session is listed
    sessions = await manager.list_sessions()
    assert sid in [s.session_id for s in sessions]

    # 7. Kill and verify dead
    await manager.kill_session(sid)
    sessions = await manager.list_sessions()
    dead = next(s for s in sessions if s.session_id == sid)
    assert not dead.is_alive
    assert dead.ended_at is not None


@pytest.mark.asyncio
async def test_codex_session_lifecycle(manager, test_dir):
    """Full lifecycle: create, select, confirm selection, kill."""
    # 1. Create session and wait for startup
    info = await manager.create_session(
        working_dir=str(test_dir),
        agent_type=AgentType.CODEX,
    )
    sid = info.session_id
    await asyncio.sleep(3)

    # 2. Handle approval mode prompt if shown
    await _handle_startup_prompt(manager, sid)

    # 3. Wait for prompt
    await _wait_for_state(manager, sid, UIState.PROMPT, retries=5, interval=1)

    # 4. Trigger a selection
    await manager.send_input(sid, _SELECTION_PROMPT)
    parsed = await _wait_for_state(manager, sid, UIState.SELECTION)

    assert len(parsed.items) > 1

    # 5. Select option 2 → should return to prompt
    await manager.send_selection(sid, 2)
    await _wait_for_state(manager, sid, UIState.PROMPT)

    # 6. Verify session is listed
    sessions = await manager.list_sessions()
    assert sid in [s.session_id for s in sessions]

    # 7. Kill and verify dead
    await manager.kill_session(sid)
    sessions = await manager.list_sessions()
    dead = next(s for s in sessions if s.session_id == sid)
    assert not dead.is_alive
    assert dead.ended_at is not None


# ── Background capture test ──────────────────────────────


@pytest_asyncio.fixture
async def live_client(tmux_backend):
    """HTTP client with real lifespan (capture loop + DB).

    Depends on tmux_backend so its teardown kills any
    leftover test sessions after the lifespan exits.
    """
    async with lifespan(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            yield ac


@pytest.mark.asyncio
async def test_background_capture_populates_history(live_client, test_dir):
    """Background capture loop persists output to history API."""
    mgr = app.state.session_manager

    info = await mgr.create_session(working_dir=str(test_dir))
    sid = info.session_id
    await asyncio.sleep(3)

    # Handle trust prompt if shown
    await _handle_startup_prompt(mgr, sid)

    # Wait for prompt, then send a long-output request
    parsed = await _wait_for_state(mgr, sid, UIState.PROMPT, retries=5, interval=1)
    if parsed.state == UIState.PROMPT:
        await mgr.send_input(
            sid,
            "write a 60-line python script that prints "
            "fibonacci numbers with comments on each line",
        )

    # Wait for output to scroll and capture loop to fire
    for _ in range(15):
        await asyncio.sleep(2)
        await mgr.capture_output(sid)

    # Verify history API returns captured output
    resp = await live_client.get(
        f"/api/v1/sessions/{sid}/output",
        params={"mode": "history"},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert len(data["chunks"]) > 0
    all_content = "\n".join(c["content"] for c in data["chunks"])
    assert len(all_content) > 10

    for chunk in data["chunks"]:
        assert isinstance(chunk["ts"], float)

    assert data["earliest_ts"] is not None
