"""Tests for notification API endpoints."""

import pytest
import pytest_asyncio

from agentdeck.main import app
from agentdeck.notifications.store import (
    PushSubscriptionStore,
)


@pytest_asyncio.fixture
async def client(tmp_path):
    """Client with real push store on app.state."""
    import httpx

    store = PushSubscriptionStore(tmp_path / "subs.json")
    app.state.push_store = store
    app.state.vapid_public_key = "test-vapid-key-abc"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.mark.asyncio
async def test_vapid_key(client):
    resp = await client.get("/api/v1/notifications/vapid-key")
    assert resp.status_code == 200
    assert resp.json()["public_key"] == "test-vapid-key-abc"


@pytest.mark.asyncio
async def test_subscribe_and_query(client):
    resp = await client.post(
        "/api/v1/notifications/subscribe",
        json={
            "endpoint": "https://ep/1",
            "p256dh": "k",
            "auth": "a",
            "session_id": "s1",
        },
    )
    assert resp.status_code == 201

    resp = await client.get(
        "/api/v1/notifications/subscriptions",
        params={"endpoint": "https://ep/1"},
    )
    assert resp.status_code == 200
    assert resp.json() == ["s1"]


@pytest.mark.asyncio
async def test_unsubscribe(client):
    await client.post(
        "/api/v1/notifications/subscribe",
        json={
            "endpoint": "https://ep/1",
            "p256dh": "k",
            "auth": "a",
            "session_id": "s1",
        },
    )
    resp = await client.post(
        "/api/v1/notifications/unsubscribe",
        json={
            "endpoint": "https://ep/1",
            "session_id": "s1",
        },
    )
    assert resp.status_code == 200

    resp = await client.get(
        "/api/v1/notifications/subscriptions",
        params={"endpoint": "https://ep/1"},
    )
    assert resp.json() == []


@pytest.mark.asyncio
async def test_multi_session_subscribe(client):
    for sid in ["s1", "s2"]:
        await client.post(
            "/api/v1/notifications/subscribe",
            json={
                "endpoint": "https://ep/1",
                "p256dh": "k",
                "auth": "a",
                "session_id": sid,
            },
        )
    resp = await client.get(
        "/api/v1/notifications/subscriptions",
        params={"endpoint": "https://ep/1"},
    )
    assert set(resp.json()) == {"s1", "s2"}
