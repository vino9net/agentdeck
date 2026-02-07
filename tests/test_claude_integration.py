"""Integration tests for real Claude sessions.

These tests require:
- A real tmux server running
- Claude Code CLI installed and authenticated

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
from agentdeck.sessions.models import UIState
from agentdeck.sessions.tmux_backend import TmuxBackend

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


_TEST_SESSION_PREFIX = "agent-claude-test-"


@pytest.fixture()
def tmux_backend():
    """Shared TmuxBackend with teardown that kills all test sessions."""
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
    path = tmp_dir / f"claude-test-{suffix}"
    path.mkdir(exist_ok=True)
    yield path
    if path.exists():
        shutil.rmtree(path)


@pytest.fixture()
def manager(tmux_backend, test_dir):
    """Create a real SessionManager."""
    recent_path = test_dir / "recent_dirs.txt"
    return SessionManager(tmux=tmux_backend, recent_dirs_path=recent_path)


@pytest.mark.asyncio
async def test_claude_session_lifecycle(manager, test_dir):
    """Full lifecycle test: create, interact, detect states, shutdown."""
    # 1. Create a real Claude session
    info = await manager.create_session(working_dir=str(test_dir))
    session_id = info.session_id

    # Wait for Claude to start up
    await asyncio.sleep(3)

    # 2. Handle trust folder prompt if shown
    output = await manager.capture_output(session_id)
    parsed = manager.parse_output(output.content)

    if parsed.state == UIState.SELECTION:
        trust_item = next(
            (i for i in parsed.items if "trust" in i.label.lower()),
            None,
        )
        if trust_item:
            await manager.send_selection(session_id, trust_item.number)
            await asyncio.sleep(2)

    # 3. Wait for prompt state (ready for input)
    for _ in range(5):
        output = await manager.capture_output(session_id)
        parsed = manager.parse_output(output.content)
        if parsed.state == UIState.PROMPT:
            break
        await asyncio.sleep(1)

    assert parsed.state == UIState.PROMPT, f"Expected PROMPT state, got {parsed.state}"

    # 4. Send a prompt that triggers a selection
    await manager.send_input(
        session_id,
        "ask me a question about tmux and let me select answer",
    )

    # Wait for Claude to process and show selection
    selection_found = False
    for _ in range(15):
        await asyncio.sleep(2)
        output = await manager.capture_output(session_id)
        parsed = manager.parse_output(output.content)
        if parsed.state == UIState.SELECTION:
            selection_found = True
            break

    assert selection_found, (
        f"Claude did not show selection within timeout (state: {parsed.state})"
    )

    # 5. Assert selection has multiple choices
    assert len(parsed.items) > 1, f"Expected multiple choices, got {len(parsed.items)}"

    # 6. Verify session appears in list while alive
    sessions = await manager.list_sessions()
    session_ids = [s.session_id for s in sessions]
    assert session_id in session_ids

    # 7. Kill the session
    await manager.kill_session(session_id)

    # 8. Assert session is marked dead
    sessions = await manager.list_sessions()
    dead = next(s for s in sessions if s.session_id == session_id)
    assert not dead.is_alive
    assert dead.ended_at is not None


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
    """Background capture loop persists Claude output,
    retrievable via the history API."""
    mgr = app.state.session_manager

    info = await mgr.create_session(
        working_dir=str(test_dir),
    )
    session_id = info.session_id

    # Wait for Claude to start
    await asyncio.sleep(3)

    # Handle trust prompt if shown
    output = await mgr.capture_output(session_id)
    parsed = mgr.parse_output(output.content)

    if parsed.state == UIState.SELECTION:
        trust_item = next(
            (i for i in parsed.items if "trust" in i.label.lower()),
            None,
        )
        if trust_item:
            await mgr.send_selection(session_id, trust_item.number)
            await asyncio.sleep(2)

    # Wait for PROMPT state
    for _ in range(5):
        output = await mgr.capture_output(session_id)
        parsed = mgr.parse_output(output.content)
        if parsed.state == UIState.PROMPT:
            break
        await asyncio.sleep(1)

    # Send a prompt that generates enough output to push
    # content into scrollback (above the visible pane).
    # The capture loop only logs scrollback lines.
    if parsed.state == UIState.PROMPT:
        await mgr.send_input(
            session_id,
            "write a 60-line python script that prints "
            "fibonacci numbers with comments on each line",
        )

    # Wait for Claude to respond and output to scroll.
    # Capture loop runs every 2s; give it time to fire.
    for _ in range(15):
        await asyncio.sleep(2)
        output = await mgr.capture_output(session_id)
        parsed = mgr.parse_output(output.content)

    # Verify history API returns captured output
    resp = await live_client.get(
        f"/api/v1/sessions/{session_id}/output",
        params={"mode": "history"},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert len(data["chunks"]) > 0, "Expected at least one captured chunk"

    all_content = "\n".join(c["content"] for c in data["chunks"])
    assert len(all_content) > 10, f"Expected captured content, got: {all_content[:200]}"

    for chunk in data["chunks"]:
        assert isinstance(chunk["ts"], float)

    assert data["earliest_ts"] is not None
