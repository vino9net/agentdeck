"""Push notification API endpoints."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class SubscribeRequest(BaseModel):
    endpoint: str
    p256dh: str
    auth: str
    session_id: str


class UnsubscribeRequest(BaseModel):
    endpoint: str
    session_id: str


@router.get("/vapid-key")
async def vapid_key(request: Request) -> dict:
    """Return the VAPID application server key."""
    return {"public_key": request.app.state.vapid_public_key}


@router.post("/subscribe", status_code=201)
async def subscribe(body: SubscribeRequest, request: Request) -> dict:
    """Register a push subscription for a session."""
    store = request.app.state.push_store
    store.subscribe(
        endpoint=body.endpoint,
        p256dh=body.p256dh,
        auth=body.auth,
        session_id=body.session_id,
    )
    return {"ok": True}


@router.post("/unsubscribe")
async def unsubscribe(body: UnsubscribeRequest, request: Request) -> dict:
    """Remove a push subscription for a session."""
    store = request.app.state.push_store
    store.unsubscribe(
        endpoint=body.endpoint,
        session_id=body.session_id,
    )
    return {"ok": True}


@router.get("/subscriptions")
async def subscriptions(endpoint: str, request: Request) -> list[str]:
    """Return session IDs subscribed from an endpoint."""
    store = request.app.state.push_store
    return store.get_session_ids_for_endpoint(endpoint)
