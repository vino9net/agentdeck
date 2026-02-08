"""Tests for the sessions REST API."""

import io
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from agentdeck.main import app
from agentdeck.sessions.agent_output_log import AgentOutputLog
from agentdeck.sessions.models import (
    AgentType,
    SessionInfo,
)


def _make_mock_manager():
    """Create a mock SessionManager."""
    mgr = MagicMock()
    info = SessionInfo(
        session_id="agent-test123",
        agent_type=AgentType.CLAUDE,
        working_dir="/tmp",
    )
    mgr.create_session = AsyncMock(return_value=info)
    mgr.list_sessions = AsyncMock(return_value=[info])
    mgr.get_session = AsyncMock(return_value=info)
    mgr.send_input = AsyncMock()
    mgr.send_selection = AsyncMock()
    mgr.paste_image = AsyncMock()
    mgr.kill_session = AsyncMock()
    mgr.list_recent_dirs = MagicMock(return_value=["/tmp"])
    return mgr


@pytest.fixture(autouse=True)
def _setup_mock_manager():
    app.state.session_manager = _make_mock_manager()


@pytest.fixture()
def output_log(tmp_path):
    log = AgentOutputLog(tmp_path / "test.db")
    app.state.output_log = log
    yield log
    log.close()
    app.state.output_log = None


@pytest.mark.asyncio
async def test_create_session(client):
    resp = await client.post(
        "/api/v1/sessions",
        json={"working_dir": "/tmp"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["session_id"] == "agent-test123"


@pytest.mark.asyncio
async def test_get_session_not_found(client):
    app.state.session_manager.get_session = AsyncMock(
        side_effect=KeyError("Unknown session")
    )
    resp = await client.get("/api/v1/sessions/missing")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_send_selection_not_found(client):
    app.state.session_manager.send_selection = AsyncMock(
        side_effect=KeyError("Unknown session")
    )
    resp = await client.post(
        "/api/v1/sessions/missing/select",
        json={"item_number": 1},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_send_selection_bad_item(client):
    app.state.session_manager.send_selection = AsyncMock(
        side_effect=ValueError("Item 99 not found")
    )
    resp = await client.post(
        "/api/v1/sessions/agent-test123/select",
        json={"item_number": 99},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_history_returns_chunks(client, output_log):
    """History mode returns seeded chunks from real SQLite."""
    output_log.append("agent-test123", ["hello world"])
    time.sleep(0.01)
    output_log.append("agent-test123", ["second chunk"])

    resp = await client.get(
        "/api/v1/sessions/agent-test123/output",
        params={"mode": "history"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["chunks"]) == 2
    assert data["chunks"][0]["content"] == "hello world"
    assert data["chunks"][1]["content"] == "second chunk"
    assert data["earliest_ts"] is not None


@pytest.mark.asyncio
async def test_history_pagination(client, output_log):
    """Passing before= returns only older chunks."""
    output_log.append("s1", ["old line"])
    time.sleep(0.01)
    output_log.append("s1", ["new line"])
    new_ts = output_log.latest_ts("s1")

    # Only chunks before the newest
    resp = await client.get(
        "/api/v1/sessions/s1/output",
        params={"mode": "history", "before": new_ts},
    )
    data = resp.json()
    assert len(data["chunks"]) == 1
    assert data["chunks"][0]["content"] == "old line"


@pytest.mark.asyncio
async def test_history_empty_session(client, output_log):
    """History for unknown session returns empty list."""
    resp = await client.get(
        "/api/v1/sessions/nonexistent/output",
        params={"mode": "history"},
    )
    data = resp.json()
    assert data["chunks"] == []
    assert data["earliest_ts"] is None


@pytest.mark.asyncio
async def test_history_respects_limit(client, output_log):
    """Limit caps the number of returned chunks."""
    for i in range(10):
        output_log.append("s1", [f"line{i}"])
    resp = await client.get(
        "/api/v1/sessions/s1/output",
        params={"mode": "history", "limit": 3},
    )
    data = resp.json()
    assert len(data["chunks"]) == 3
    # Should be the 3 most recent in chronological order
    contents = [c["content"] for c in data["chunks"]]
    assert contents == ["line7", "line8", "line9"]


# --- Dead session tests ---


@pytest.mark.asyncio
async def test_live_output_dead_session(client):
    """Live output for dead session returns 'Session ended'."""
    dead_info = SessionInfo(
        session_id="agent-dead",
        agent_type=AgentType.CLAUDE,
        working_dir="/tmp",
        is_alive=False,
        ended_at=1700000000.0,
    )
    mgr = app.state.session_manager
    mgr.get_session = AsyncMock(return_value=dead_info)

    resp = await client.get("/api/v1/sessions/agent-dead/output")
    assert resp.status_code == 200
    assert "Session ended" in resp.text


@pytest.mark.asyncio
async def test_send_input_dead_returns_409(client):
    """Sending input to a dead session returns 409."""
    mgr = app.state.session_manager
    mgr.send_input = AsyncMock(side_effect=ValueError("Session ended: agent-dead"))
    resp = await client.post(
        "/api/v1/sessions/agent-dead/input",
        json={"text": "hello"},
    )
    assert resp.status_code == 409


# --- Image paste tests ---

_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.mark.asyncio
async def test_paste_image_png(client):
    """Upload a PNG image and paste it into the session."""
    resp = await client.post(
        "/api/v1/sessions/agent-test123/image",
        files={"file": ("shot.png", io.BytesIO(_PNG_BYTES), "image/png")},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pasted"
    mgr = app.state.session_manager
    mgr.paste_image.assert_awaited_once()
    call_args = mgr.paste_image.call_args
    assert call_args[0][0] == "agent-test123"
    assert call_args[0][2] == "png"


@pytest.mark.asyncio
async def test_paste_image_jpeg(client):
    """Upload a JPEG image."""
    resp = await client.post(
        "/api/v1/sessions/agent-test123/image",
        files={"file": ("photo.jpg", io.BytesIO(b"\xff\xd8"), "image/jpeg")},
    )
    assert resp.status_code == 200
    call_args = app.state.session_manager.paste_image.call_args
    assert call_args[0][2] == "jpeg"


@pytest.mark.asyncio
async def test_paste_image_bad_type(client):
    """Non-image content type is rejected."""
    resp = await client.post(
        "/api/v1/sessions/agent-test123/image",
        files={"file": ("file.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert resp.status_code == 400
    assert "Unsupported" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_paste_image_dead_session(client):
    """Pasting to a dead session returns 409."""
    mgr = app.state.session_manager
    mgr.paste_image = AsyncMock(side_effect=ValueError("Session ended"))
    resp = await client.post(
        "/api/v1/sessions/agent-test123/image",
        files={"file": ("img.png", io.BytesIO(_PNG_BYTES), "image/png")},
    )
    assert resp.status_code == 409
