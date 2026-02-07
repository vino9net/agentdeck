from fastapi import APIRouter

from agentdeck.api import health, sessions

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(
    sessions.router,
    prefix="/sessions",
    tags=["sessions"],
)
